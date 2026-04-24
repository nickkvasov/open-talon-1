from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.services.agent_bundles import (  # noqa: E402
    AgentBundleCompiler,
    MappingAgentBundleReader,
    join_bundle_path,
    normalize_bundle_path,
    resolve_bundle_reference,
)
from gateway_edge.services.collaboration import CollaborationService  # noqa: E402
from gateway_edge.services.git_worktrees import LocalManagedWorktreeStore  # noqa: E402
from gateway_edge.models import GitRepository, ParticipantInput  # noqa: E402


def _bundle_files(*, omit: str | None = None):
    files = {
        "agents/admin/agent.yaml": """
schema_version: 1
agent_key: admin
display_name: Admin Agent
description: Manages agent definitions.
role: agent_admin
capabilities: [agent_catalog, git_catalog]
endpoint:
  kind: remote
  model: gpt-5.4
system_prompt_path: PROMPT.md
interaction_contract_path: interaction.yaml
harness_path: harness/harness.yaml
skills:
  - ref: skill://review
    path: skills/review.md
""",
        "agents/admin/PROMPT.md": "You manage agent definitions.\n",
        "agents/admin/interaction.yaml": """
instructions: [Operate safely.]
response_contract:
  format: markdown
completion_criteria: [Publish only valid bundles.]
""",
        "agents/admin/harness/harness.yaml": """
version: 1
summary: Admin harness.
operating_principles_path: operating-principles.md
planning_path: planning.yaml
tool_use_policy_path: tool-use.yaml
memory_policy_path: memory.yaml
compaction_policy_path: compaction.yaml
collaboration_policy_path: collaboration.yaml
validation_policy_path: validation.yaml
stop_policy_path: stop.yaml
skill_refs: [skill://review]
metadata: {}
""",
        "agents/admin/harness/operating-principles.md": "- Be explicit\n- Validate before publish\n",
        "agents/admin/harness/planning.yaml": """
plan_before_act: true
incremental_execution: true
one_goal_at_a_time: true
explicit_uncertainty: true
guidance: []
""",
        "agents/admin/harness/tool-use.yaml": """
selection_principles: []
read_before_write: true
inspect_schema_before_use: true
prefer_existing_workspace_tools: true
cite_tool_results_in_reasoning: true
verify_side_effects_after_mutation: true
fallback_when_no_tool_fits: null
""",
        "agents/admin/harness/memory.yaml": """
use_run_memory: true
use_thread_memory: true
use_workspace_memory: true
""",
        "agents/admin/harness/compaction.yaml": """
enabled: true
strategy: full_context
overflow_behavior: auto_fallback
max_estimated_input_tokens: 12000
recent_message_count: 12
min_recent_message_count: 4
max_run_memory_entries: 6
max_thread_memory_entries: 6
max_workspace_memory_entries: 6
summary_max_chars: 3000
retrieval_limit: 5
retrieval_provider_key: null
""",
        "agents/admin/harness/collaboration.yaml": """
ask_user_when: []
escalate_when: []
delegation_guidance: []
handoff_guidance: []
""",
        "agents/admin/harness/validation.yaml": """
required_checks: []
require_evidence_for_claims: true
require_tool_results_for_completion: false
require_tests_before_done: false
""",
        "agents/admin/harness/stop.yaml": """
completion_conditions: []
stop_conditions: []
max_turns: null
""",
        "agents/admin/skills/review.md": "Review changes before publishing.\n",
    }
    if omit:
        files.pop(omit)
    return files


@pytest.mark.asyncio
async def test_agent_bundle_compiler_builds_complete_agent_definition():
    compiler = AgentBundleCompiler()
    compiled = await compiler.compile(
        reader=MappingAgentBundleReader(_bundle_files()),
        scope="global",
        organization_id=None,
        bundle_path="agents/admin",
        created_by=uuid4(),
        repository_id=uuid4(),
        resolved_revision="abc123",
    )

    assert compiled.agent.agent_key == "admin"
    assert compiled.agent.system_prompt == "You manage agent definitions.\n"
    assert compiled.agent.harness is not None
    assert compiled.agent.harness.planning.plan_before_act is True
    assert compiled.agent.harness.skill_refs == ["skill://review"]
    assert compiled.skill_asset_refs[0]["path"] == "agents/admin/skills/review.md"


@pytest.mark.asyncio
async def test_agent_bundle_compiler_rejects_missing_harness_section():
    compiler = AgentBundleCompiler()
    files = _bundle_files()
    files["agents/admin/harness/planning.yaml"] = """
plan_before_act: true
incremental_execution: true
one_goal_at_a_time: true
guidance: []
"""

    with pytest.raises(ValueError, match="explicit_uncertainty"):
        await compiler.compile(
            reader=MappingAgentBundleReader(files),
            scope="global",
            organization_id=None,
            bundle_path="agents/admin",
            created_by=uuid4(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda files: files.__setitem__(
                "agents/admin/agent.yaml",
                files["agents/admin/agent.yaml"].replace("schema_version: 1", "schema_version: 2"),
            ),
            "schema_version 1",
        ),
        (
            lambda files: files.__setitem__(
                "agents/admin/agent.yaml",
                files["agents/admin/agent.yaml"].replace("kind: remote", "kind: impossible"),
            ),
            "literal_error",
        ),
        (
            lambda files: files.__setitem__(
                "agents/admin/interaction.yaml",
                "instructions: invalid-string\nresponse_contract:\n  format: markdown\n",
            ),
            "list_type",
        ),
        (
            lambda files: files.__setitem__(
                "agents/admin/agent.yaml",
                files["agents/admin/agent.yaml"] + "  - ref: skill://review\n    path: skills/review.md\n",
            ),
            "Duplicate skill ref",
        ),
    ],
)
async def test_agent_bundle_compiler_rejects_invalid_bundle_shapes(mutate, match):
    compiler = AgentBundleCompiler()
    files = _bundle_files()
    mutate(files)

    with pytest.raises(ValueError, match=match):
        await compiler.compile(
            reader=MappingAgentBundleReader(files),
            scope="global",
            organization_id=None,
            bundle_path="agents/admin",
            created_by=uuid4(),
        )


def test_bundle_path_helpers_reject_traversal_and_anchor_references():
    assert normalize_bundle_path("/agents/admin/") == "agents/admin"
    assert join_bundle_path("agents/admin", "harness/planning.yaml") == "agents/admin/harness/planning.yaml"
    assert (
        resolve_bundle_reference("agents/admin", "agents/admin/harness/harness.yaml", "planning.yaml")
        == "agents/admin/harness/planning.yaml"
    )
    assert (
        resolve_bundle_reference("agents/admin", "agents/admin/harness/harness.yaml", "harness/planning.yaml")
        == "agents/admin/harness/planning.yaml"
    )

    for path in ["../agent.yaml", "", "."]:
        with pytest.raises(ValueError):
            normalize_bundle_path(path)
    with pytest.raises(ValueError):
        join_bundle_path("agents/admin", "../PROMPT.md")
    with pytest.raises(ValueError):
        resolve_bundle_reference("agents/admin", "agents/admin/harness/harness.yaml", "../secret.yaml")


def test_archive_upload_member_paths_can_be_bundle_relative():
    service = CollaborationService()

    assert (
        service._archive_member_worktree_path("agents/admin", "agent.yaml")
        == "agents/admin/agent.yaml"
    )
    assert (
        service._archive_member_worktree_path("agents/admin", "agents/admin/PROMPT.md")
        == "agents/admin/PROMPT.md"
    )
    with pytest.raises(ValueError):
        service._archive_member_worktree_path("agents/admin", "../secret.md")


class _FakeGitService:
    def __init__(self) -> None:
        self.created_worktrees = []
        self.pushed = []

    async def create_worktree(self, local_path, *, worktree_path, branch, base_revision=None):
        self.created_worktrees.append((local_path, worktree_path, branch, base_revision))
        Path(worktree_path).mkdir(parents=True, exist_ok=True)
        return base_revision or "main"

    async def diff(self, worktree_path):
        return "diff --git a/agent.yaml b/agent.yaml", ["agents/admin/agent.yaml"]

    async def commit(self, worktree_path, *, message, author_name, author_email):
        return "abc123", ["agents/admin/agent.yaml"]

    async def push(self, worktree_path, branch):
        self.pushed.append((worktree_path, branch))


def _git_repository(tmp_path):
    now = datetime.now(timezone.utc)
    return GitRepository(
        repo_id=uuid4(),
        scope="global",
        organization_id=None,
        workspace_id=None,
        name="agent-definitions",
        forgejo_url=None,
        clone_url=None,
        local_path=str(tmp_path / "repo"),
        default_branch="main",
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={},
    )


def _participant():
    participant_id = uuid4()
    return ParticipantInput(
        participant_id=participant_id,
        participant_type="user",
        user_id=participant_id,
        display_name="Admin",
    )


@pytest.mark.asyncio
async def test_managed_worktree_store_guards_paths_and_commits(tmp_path):
    git = _FakeGitService()
    store = LocalManagedWorktreeStore(root=str(tmp_path / "worktrees"), git_service=git)
    actor = _participant()
    session = await store.create_session(
        repository=_git_repository(tmp_path),
        branch="agents/admin",
        bundle_path="agents/admin",
        base_revision="main",
        actor=actor,
        metadata={"purpose": "test"},
    )

    await store.write_file(
        session=session,
        path="agents/admin/agent.yaml",
        content="schema_version: 1\n",
    )
    content = await store.read_file(session=session, path="agents/admin/agent.yaml")
    diff = await store.diff(session=session)
    commit = await store.commit(
        session=session,
        actor=actor,
        message="Update agent",
        push=True,
    )

    assert content.content == "schema_version: 1\n"
    assert diff.changed_files == ["agents/admin/agent.yaml"]
    assert commit.commit_sha == "abc123"
    assert commit.pushed is True
    assert git.pushed == [(session.worktree_path, "agents/admin")]

    with pytest.raises(ValueError, match="inside the session bundle path"):
        await store.write_file(session=session, path="agents/other/agent.yaml", content="x")
    with pytest.raises(ValueError, match="Unsupported"):
        await store.write_file(session=session, path="agents/admin/script.py", content="x")

    await store.discard(session=session)
    assert not Path(session.worktree_path).exists()
