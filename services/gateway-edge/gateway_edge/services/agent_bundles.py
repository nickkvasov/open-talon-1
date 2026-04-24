from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import posixpath
from typing import Any, Protocol
from uuid import UUID, uuid4

import yaml
from pydantic import ValidationError

from gateway_edge.models import (
    AgentBundleValidationDiagnostic,
    AgentBundleValidationResult,
    AgentDefinition,
    AgentEndpoint,
    AgentHarness,
    AgentInteractionContract,
    AgentPlanningPolicy,
    AgentToolUsePolicy,
    AgentMemoryPolicy,
    AgentCompactionPolicy,
    AgentCollaborationPolicy,
    AgentValidationPolicy,
    AgentStopPolicy,
)


class AgentBundleFileReader(Protocol):
    async def read_text(self, path: str) -> str: ...


@dataclass(frozen=True)
class CompiledAgentBundle:
    agent: AgentDefinition
    manifest_sha256: str
    source_files: dict[str, str]
    skill_asset_refs: list[dict[str, Any]] = field(default_factory=list)


def normalize_bundle_path(path: str) -> str:
    normalized = posixpath.normpath(path.strip().strip("/"))
    if normalized in {"", "."} or normalized.startswith("../") or normalized == "..":
        raise ValueError("Bundle path must be a relative path inside the repository")
    return normalized


def join_bundle_path(bundle_path: str, relative_path: str) -> str:
    clean_bundle = normalize_bundle_path(bundle_path)
    clean_relative = posixpath.normpath(str(relative_path).strip().strip("/"))
    if clean_relative in {"", "."} or clean_relative.startswith("../") or clean_relative == "..":
        raise ValueError(f"Invalid bundle-relative path: {relative_path!r}")
    joined = posixpath.normpath(posixpath.join(clean_bundle, clean_relative))
    if joined != clean_bundle and not joined.startswith(f"{clean_bundle}/"):
        raise ValueError(f"Path escapes bundle root: {relative_path!r}")
    return joined


def resolve_bundle_reference(bundle_path: str, base_file_path: str, referenced_path: str) -> str:
    clean_bundle = normalize_bundle_path(bundle_path)
    clean_reference = str(referenced_path).strip().strip("/")
    if clean_reference in {"", "."} or clean_reference.startswith("../") or clean_reference == "..":
        raise ValueError(f"Invalid bundle-relative path: {referenced_path!r}")
    if "/" in clean_reference:
        candidate = posixpath.normpath(posixpath.join(clean_bundle, clean_reference))
    else:
        candidate = posixpath.normpath(
            posixpath.join(posixpath.dirname(base_file_path), clean_reference)
        )
    if candidate != clean_bundle and not candidate.startswith(f"{clean_bundle}/"):
        raise ValueError(f"Path escapes bundle root: {referenced_path!r}")
    return candidate


def _load_yaml(text: str, *, path: str) -> dict[str, Any]:
    data = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _require_keys(data: dict[str, Any], keys: set[str], *, path: str) -> None:
    missing = sorted(key for key in keys if key not in data)
    if missing:
        raise ValueError(f"{path} is missing required field(s): {', '.join(missing)}")


def _principles_from_markdown(text: str) -> list[str]:
    principles: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        principles.append(stripped.removeprefix("-").strip())
    return principles


class AgentBundleCompiler:
    _MANIFEST_KEYS = {
        "schema_version",
        "agent_key",
        "display_name",
        "description",
        "role",
        "capabilities",
        "endpoint",
        "system_prompt_path",
        "interaction_contract_path",
        "harness_path",
    }
    _HARNESS_KEYS = {
        "version",
        "summary",
        "operating_principles_path",
        "planning_path",
        "tool_use_policy_path",
        "memory_policy_path",
        "compaction_policy_path",
        "collaboration_policy_path",
        "validation_policy_path",
        "stop_policy_path",
        "skill_refs",
        "metadata",
    }

    async def compile(
        self,
        *,
        reader: AgentBundleFileReader,
        scope: str,
        organization_id: UUID | None,
        bundle_path: str,
        created_by: UUID,
        repository_id: UUID | None = None,
        resolved_revision: str | None = None,
    ) -> CompiledAgentBundle:
        bundle_root = normalize_bundle_path(bundle_path)
        manifest_path = join_bundle_path(bundle_root, "agent.yaml")
        manifest_text = await reader.read_text(manifest_path)
        manifest = _load_yaml(manifest_text, path=manifest_path)
        _require_keys(manifest, self._MANIFEST_KEYS, path=manifest_path)
        if manifest["schema_version"] != 1:
            raise ValueError("Only agent bundle schema_version 1 is supported")

        agent_key = str(manifest["agent_key"]).strip()
        if not agent_key:
            raise ValueError("agent_key must not be empty")

        prompt_path = join_bundle_path(bundle_root, str(manifest["system_prompt_path"]))
        interaction_path = join_bundle_path(
            bundle_root,
            str(manifest["interaction_contract_path"]),
        )
        harness_root_path = join_bundle_path(bundle_root, str(manifest["harness_path"]))

        prompt_text = await reader.read_text(prompt_path)
        interaction = AgentInteractionContract.model_validate(
            _load_yaml(await reader.read_text(interaction_path), path=interaction_path)
        )
        harness, harness_files = await self._compile_harness(
            reader=reader,
            bundle_root=bundle_root,
            harness_root_path=harness_root_path,
        )

        now = datetime.now(timezone.utc)
        metadata = dict(manifest.get("metadata") or {})
        metadata["source"] = "git"
        metadata["git_bundle"] = {
            "repository_id": str(repository_id) if repository_id is not None else None,
            "resolved_revision": resolved_revision,
            "bundle_path": bundle_root,
            "manifest_path": manifest_path,
            "prompt_path": prompt_path,
            "interaction_contract_path": interaction_path,
            "harness_path": harness_root_path,
        }

        skill_asset_refs = []
        seen_skill_refs: set[str] = set()
        for item in manifest.get("skills") or []:
            if not isinstance(item, dict):
                raise ValueError("skills entries must be objects")
            ref = str(item.get("ref") or "").strip()
            path = str(item.get("path") or "").strip()
            if not ref or not path:
                raise ValueError("skills entries require ref and path")
            if ref in seen_skill_refs:
                raise ValueError(f"Duplicate skill ref: {ref}")
            seen_skill_refs.add(ref)
            skill_path = join_bundle_path(bundle_root, path)
            await reader.read_text(skill_path)
            skill_asset_refs.append(
                {
                    "ref": ref,
                    "path": skill_path,
                    "title": item.get("title"),
                    "purpose": "agent_skill",
                }
            )

        source_files = {
            "manifest": manifest_path,
            "prompt": prompt_path,
            "interaction_contract": interaction_path,
            **harness_files,
        }
        for skill in skill_asset_refs:
            source_files[f"skill:{skill['ref']}"] = skill["path"]

        try:
            endpoint = AgentEndpoint.model_validate(manifest["endpoint"])
            agent = AgentDefinition(
                agent_id=uuid4(),
                agent_key=agent_key,
                scope=scope,
                organization_id=organization_id,
                display_name=str(manifest["display_name"]),
                description=str(manifest["description"]),
                role=str(manifest["role"]),
                capabilities=list(manifest.get("capabilities") or []),
                endpoint=endpoint,
                system_prompt=prompt_text,
                harness=harness,
                interaction_contract=interaction,
                definition={
                    "source": "git",
                    "agent_key": agent_key,
                    "bundle_path": bundle_root,
                    "source_files": source_files,
                },
                created_by=created_by,
                created_at=now,
                updated_at=now,
                metadata=metadata,
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        return CompiledAgentBundle(
            agent=agent,
            manifest_sha256=hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
            source_files=source_files,
            skill_asset_refs=skill_asset_refs,
        )

    async def _compile_harness(
        self,
        *,
        reader: AgentBundleFileReader,
        bundle_root: str,
        harness_root_path: str,
    ) -> tuple[AgentHarness, dict[str, str]]:
        harness_root = _load_yaml(await reader.read_text(harness_root_path), path=harness_root_path)
        _require_keys(harness_root, self._HARNESS_KEYS, path=harness_root_path)

        paths = {
            "operating_principles": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["operating_principles_path"]),
            ),
            "planning": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["planning_path"]),
            ),
            "tool_use_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["tool_use_policy_path"]),
            ),
            "memory_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["memory_policy_path"]),
            ),
            "compaction_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["compaction_policy_path"]),
            ),
            "collaboration_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["collaboration_policy_path"]),
            ),
            "validation_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["validation_policy_path"]),
            ),
            "stop_policy": resolve_bundle_reference(
                bundle_root,
                harness_root_path,
                str(harness_root["stop_policy_path"]),
            ),
        }
        planning = _load_yaml(await reader.read_text(paths["planning"]), path=paths["planning"])
        tool_use = _load_yaml(
            await reader.read_text(paths["tool_use_policy"]),
            path=paths["tool_use_policy"],
        )
        memory = _load_yaml(await reader.read_text(paths["memory_policy"]), path=paths["memory_policy"])
        compaction = _load_yaml(
            await reader.read_text(paths["compaction_policy"]),
            path=paths["compaction_policy"],
        )
        collaboration = _load_yaml(
            await reader.read_text(paths["collaboration_policy"]),
            path=paths["collaboration_policy"],
        )
        validation = _load_yaml(
            await reader.read_text(paths["validation_policy"]),
            path=paths["validation_policy"],
        )
        stop = _load_yaml(await reader.read_text(paths["stop_policy"]), path=paths["stop_policy"])

        _require_keys(
            planning,
            {"plan_before_act", "incremental_execution", "one_goal_at_a_time", "explicit_uncertainty", "guidance"},
            path=paths["planning"],
        )
        _require_keys(
            tool_use,
            {
                "selection_principles",
                "read_before_write",
                "inspect_schema_before_use",
                "prefer_existing_workspace_tools",
                "cite_tool_results_in_reasoning",
                "verify_side_effects_after_mutation",
                "fallback_when_no_tool_fits",
            },
            path=paths["tool_use_policy"],
        )
        _require_keys(
            memory,
            {"use_run_memory", "use_thread_memory", "use_workspace_memory"},
            path=paths["memory_policy"],
        )
        _require_keys(
            compaction,
            {
                "enabled",
                "strategy",
                "overflow_behavior",
                "max_estimated_input_tokens",
                "recent_message_count",
                "min_recent_message_count",
                "max_run_memory_entries",
                "max_thread_memory_entries",
                "max_workspace_memory_entries",
                "summary_max_chars",
                "retrieval_limit",
                "retrieval_provider_key",
            },
            path=paths["compaction_policy"],
        )
        _require_keys(
            collaboration,
            {"ask_user_when", "escalate_when", "delegation_guidance", "handoff_guidance"},
            path=paths["collaboration_policy"],
        )
        _require_keys(
            validation,
            {
                "required_checks",
                "require_evidence_for_claims",
                "require_tool_results_for_completion",
                "require_tests_before_done",
            },
            path=paths["validation_policy"],
        )
        _require_keys(
            stop,
            {"completion_conditions", "stop_conditions", "max_turns"},
            path=paths["stop_policy"],
        )

        try:
            harness = AgentHarness(
                version=int(harness_root["version"]),
                summary=harness_root["summary"],
                operating_principles=_principles_from_markdown(
                    await reader.read_text(paths["operating_principles"])
                ),
                planning=AgentPlanningPolicy.model_validate(planning),
                tool_use_policy=AgentToolUsePolicy.model_validate(tool_use),
                memory_policy=AgentMemoryPolicy.model_validate(memory),
                compaction_policy=AgentCompactionPolicy.model_validate(compaction),
                collaboration_policy=AgentCollaborationPolicy.model_validate(collaboration),
                validation_policy=AgentValidationPolicy.model_validate(validation),
                stop_policy=AgentStopPolicy.model_validate(stop),
                skill_refs=list(harness_root.get("skill_refs") or []),
                metadata=dict(harness_root.get("metadata") or {}),
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return harness, {"harness": harness_root_path, **paths}


class GitAgentBundleReader:
    def __init__(self, git_service, *, repository_path: str, revision: str | None) -> None:
        self._git_service = git_service
        self._repository_path = repository_path
        self._revision = revision
        self.resolved_revision: str | None = None

    async def read_text(self, path: str) -> str:
        content, revision = await self._git_service.read_file(
            self._repository_path,
            self.resolved_revision or self._revision,
            path,
        )
        self.resolved_revision = revision
        return content.decode("utf-8")


class MappingAgentBundleReader:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    async def read_text(self, path: str) -> str:
        try:
            return self._files[path]
        except KeyError as exc:
            raise ValueError(f"Bundle file not found: {path}") from exc


def validation_error_result(
    *,
    scope: str,
    organization_id: UUID | None,
    repository_id: UUID | None,
    resolved_revision: str | None,
    bundle_path: str,
    message: str,
) -> AgentBundleValidationResult:
    return AgentBundleValidationResult(
        valid=False,
        scope=scope,
        organization_id=organization_id,
        repository_id=repository_id,
        resolved_revision=resolved_revision,
        bundle_path=bundle_path,
        diagnostics=[
            AgentBundleValidationDiagnostic(
                code="agent_bundle_invalid",
                message=message,
                severity="error",
            )
        ],
    )
