from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID, uuid4

from open_talon_contracts.models import (
    AgentCompactionPolicy,
    AgentExecutionContext,
    MemoryEntry,
    MemorySearchResponse,
    ParticipantInput,
    SearchMemoryRequest,
    TimelineMessage,
)

COMPACTION_SUMMARY_ENTRY_TYPE = "context_compaction_summary"
_COMPACTION_SUMMARY_SOURCE = "agent_runtime_compaction"
_RETRIEVED_MEMORY_METADATA_KEY = "_compaction_retrieved"


class RuntimeCompactionKernel(Protocol):
    async def search_thread_memory(
        self,
        thread_id: UUID,
        payload: SearchMemoryRequest,
    ) -> MemorySearchResponse: ...

    async def upsert_run_scratch(
        self,
        *,
        run_id: UUID,
        actor_input: ParticipantInput,
        entry_type: str,
        content: str,
        summary: str | None = None,
        metadata: dict[str, object] | None = None,
        visibility: str = "agents_only",
        source: str = "agent_runtime",
        memory_entry_id: UUID | None = None,
    ) -> MemoryEntry: ...


@dataclass(frozen=True)
class CompactedExecutionContext:
    context: AgentExecutionContext
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _CompactionCandidate:
    context: AgentExecutionContext
    strategy: str
    fallback_stage: str
    generated_summary: MemoryEntry | None
    source_message_count: int
    source_run_memory_count: int
    covered_sequence_end: int
    retrieved_memory_entry_ids: list[str]
    estimated_tokens_before: int = 0
    estimated_tokens_after: int = 0


async def compact_execution_context(
    context: AgentExecutionContext,
    *,
    kernel: RuntimeCompactionKernel,
    render_prompt: Callable[[AgentExecutionContext], str],
) -> CompactedExecutionContext:
    policy = _policy_for_context(context)
    estimated_before = _estimate_tokens(render_prompt(context))
    base_strategy = policy.strategy if policy.enabled else "full_context"
    candidates = await _build_candidates(
        context,
        kernel=kernel,
        policy=policy,
        base_strategy=base_strategy,
        estimated_before=estimated_before,
        render_prompt=render_prompt,
    )
    for candidate in candidates:
        if candidate.estimated_tokens_after <= policy.max_estimated_input_tokens:
            final_context, metadata = await _finalize_candidate(
                context,
                candidate,
                kernel=kernel,
            )
            return CompactedExecutionContext(context=final_context, metadata=metadata)
    raise ValueError(
        "Unable to fit agent execution context within compaction policy limit "
        f"({estimated_before}/{policy.max_estimated_input_tokens} estimated tokens) "
        "even after automatic fallback."
    )


async def _build_candidates(
    context: AgentExecutionContext,
    *,
    kernel: RuntimeCompactionKernel,
    policy: AgentCompactionPolicy,
    base_strategy: str,
    estimated_before: int,
    render_prompt: Callable[[AgentExecutionContext], str],
) -> list[_CompactionCandidate]:
    candidates: list[_CompactionCandidate] = []
    candidate_specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            base_strategy,
            "assigned",
            {
                "recent_message_count": policy.recent_message_count,
                "max_run_memory_entries": policy.max_run_memory_entries,
                "max_thread_memory_entries": policy.max_thread_memory_entries,
                "max_workspace_memory_entries": policy.max_workspace_memory_entries,
                "allow_retrieval": base_strategy == "summary_plus_retrieval",
            },
        )
    ]
    if base_strategy == "summary_plus_retrieval":
        candidate_specs.append(
            (
                "summary_plus_retrieval",
                "drop_retrieval",
                {
                    "recent_message_count": policy.recent_message_count,
                    "max_run_memory_entries": policy.max_run_memory_entries,
                    "max_thread_memory_entries": policy.max_thread_memory_entries,
                    "max_workspace_memory_entries": policy.max_workspace_memory_entries,
                    "allow_retrieval": False,
                },
            )
        )

    reduced_strategy = (
        base_strategy
        if base_strategy in {"recent_window", "rolling_summary", "summary_plus_retrieval"}
        else "recent_window"
    )
    candidate_specs.append(
        (
            reduced_strategy,
            "reduced_retention",
            {
                "recent_message_count": min(
                    policy.recent_message_count,
                    max(policy.min_recent_message_count, 1),
                ),
                "max_run_memory_entries": min(policy.max_run_memory_entries, 1),
                "max_thread_memory_entries": min(policy.max_thread_memory_entries, 1),
                "max_workspace_memory_entries": min(policy.max_workspace_memory_entries, 1),
                "allow_retrieval": False,
            },
        )
    )
    candidate_specs.append(
        (
            "rolling_summary",
            "forced_rolling_summary",
            {
                "recent_message_count": max(policy.min_recent_message_count, 1),
                "max_run_memory_entries": 1,
                "max_thread_memory_entries": 1,
                "max_workspace_memory_entries": 1,
                "allow_retrieval": False,
            },
        )
    )

    seen: set[tuple[str, str, int, int, int, int, bool]] = set()
    for strategy, fallback_stage, spec in candidate_specs:
        signature = (
            strategy,
            fallback_stage,
            spec["recent_message_count"],
            spec["max_run_memory_entries"],
            spec["max_thread_memory_entries"],
            spec["max_workspace_memory_entries"],
            spec["allow_retrieval"],
        )
        if signature in seen:
            continue
        seen.add(signature)
        candidate = await _build_candidate(
            context,
            kernel=kernel,
            policy=policy,
            strategy=strategy,
            fallback_stage=fallback_stage,
            recent_message_count=spec["recent_message_count"],
            max_run_memory_entries=spec["max_run_memory_entries"],
            max_thread_memory_entries=spec["max_thread_memory_entries"],
            max_workspace_memory_entries=spec["max_workspace_memory_entries"],
            allow_retrieval=spec["allow_retrieval"],
        )
        estimated_after = _estimate_tokens(render_prompt(candidate.context))
        candidates.append(
            _CompactionCandidate(
                context=candidate.context,
                strategy=candidate.strategy,
                fallback_stage=candidate.fallback_stage,
                generated_summary=candidate.generated_summary,
                source_message_count=candidate.source_message_count,
                source_run_memory_count=candidate.source_run_memory_count,
                covered_sequence_end=candidate.covered_sequence_end,
                retrieved_memory_entry_ids=candidate.retrieved_memory_entry_ids,
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_after,
            )
        )
    return candidates


async def _build_candidate(
    context: AgentExecutionContext,
    *,
    kernel: RuntimeCompactionKernel,
    policy: AgentCompactionPolicy,
    strategy: str,
    fallback_stage: str,
    recent_message_count: int,
    max_run_memory_entries: int,
    max_thread_memory_entries: int,
    max_workspace_memory_entries: int,
    allow_retrieval: bool,
) -> _CompactionCandidate:
    if strategy == "full_context":
        return _CompactionCandidate(
            context=context,
            strategy=strategy,
            fallback_stage=fallback_stage,
            generated_summary=None,
            source_message_count=0,
            source_run_memory_count=0,
            covered_sequence_end=0,
            retrieved_memory_entry_ids=[],
        )

    selected_messages = _select_recent_messages(
        context.messages,
        recent_message_count=recent_message_count,
        trigger_message=context.trigger_message,
    )
    selected_thread_memory = _select_recent_memory_entries(
        context.thread_memory,
        max_thread_memory_entries,
    )
    selected_workspace_memory = _select_recent_memory_entries(
        context.workspace_memory,
        max_workspace_memory_entries,
    )
    selected_run_memory = _select_recent_memory_entries(
        [
            entry
            for entry in context.run_memory
            if entry.entry_type != COMPACTION_SUMMARY_ENTRY_TYPE
        ],
        max_run_memory_entries,
    )

    if strategy == "recent_window":
        compacted_context = context.model_copy(
            update={
                "messages": selected_messages,
                "run_memory": selected_run_memory,
                "thread_memory": selected_thread_memory,
                "workspace_memory": selected_workspace_memory,
            }
        )
        return _CompactionCandidate(
            context=compacted_context,
            strategy=strategy,
            fallback_stage=fallback_stage,
            generated_summary=None,
            source_message_count=0,
            source_run_memory_count=0,
            covered_sequence_end=0,
            retrieved_memory_entry_ids=[],
        )

    summary_entry, summary_source_messages, summary_source_run_memory = _build_context_summary_entry(
        context,
        selected_messages=selected_messages,
        selected_run_memory=selected_run_memory,
        summary_max_chars=policy.summary_max_chars,
        max_run_memory_entries=max_run_memory_entries,
    )
    compacted_run_memory = list(selected_run_memory)
    if summary_entry is not None and max_run_memory_entries > 0:
        compacted_run_memory = [summary_entry, *compacted_run_memory]
    compacted_thread_memory = list(selected_thread_memory)
    retrieved_memory_entry_ids: list[str] = []
    if strategy == "summary_plus_retrieval" and allow_retrieval:
        retrieval_hits = await _retrieve_thread_memory_hits(context, kernel=kernel, policy=policy)
        if retrieval_hits:
            compacted_thread_memory = _merge_retrieval_hits(
                compacted_thread_memory,
                retrieval_hits,
            )
            retrieved_memory_entry_ids = [str(entry.memory_entry_id) for entry in retrieval_hits]

    compacted_context = context.model_copy(
        update={
            "messages": selected_messages,
            "run_memory": compacted_run_memory,
            "thread_memory": compacted_thread_memory,
            "workspace_memory": selected_workspace_memory,
        }
    )
    return _CompactionCandidate(
        context=compacted_context,
        strategy=strategy,
        fallback_stage=fallback_stage,
        generated_summary=summary_entry,
        source_message_count=len(summary_source_messages),
        source_run_memory_count=len(summary_source_run_memory),
        covered_sequence_end=max(
            (message.sequence for message in summary_source_messages),
            default=0,
        ),
        retrieved_memory_entry_ids=retrieved_memory_entry_ids,
    )


async def _finalize_candidate(
    source_context: AgentExecutionContext,
    candidate: _CompactionCandidate,
    *,
    kernel: RuntimeCompactionKernel,
) -> tuple[AgentExecutionContext, dict[str, Any]]:
    metadata = {
        "assigned_strategy": _policy_for_context(source_context).strategy,
        "strategy": candidate.strategy,
        "fallback_stage": candidate.fallback_stage,
        "estimated_tokens_before": candidate.estimated_tokens_before,
        "estimated_tokens_after": candidate.estimated_tokens_after,
        "source_message_count": candidate.source_message_count,
        "source_run_memory_count": candidate.source_run_memory_count,
        "covered_sequence_end": candidate.covered_sequence_end,
        "retrieved_memory_entry_ids": candidate.retrieved_memory_entry_ids,
    }
    context = candidate.context
    existing_summary = _existing_compaction_summary(source_context.run_memory)
    if candidate.generated_summary is not None:
        summary_entry = candidate.generated_summary.model_copy(update={"metadata": metadata})
        if _summary_matches_existing(existing_summary, summary_entry):
            summary_entry = existing_summary  # type: ignore[assignment]
        else:
            summary_entry = await kernel.upsert_run_scratch(
                run_id=source_context.run.run_id,
                actor_input=_participant_input(source_context),
                entry_type=summary_entry.entry_type,
                content=summary_entry.content,
                summary=summary_entry.summary,
                metadata=summary_entry.metadata,
                visibility=summary_entry.visibility,
                source=summary_entry.source or _COMPACTION_SUMMARY_SOURCE,
                memory_entry_id=(
                    existing_summary.memory_entry_id if existing_summary is not None else None
                ),
            )
        context = context.model_copy(
            update={"run_memory": _replace_compaction_summary(context.run_memory, summary_entry)}
        )
    system_agent = context.system_agent.model_copy(
        update={
            "metadata": {
                **dict(context.system_agent.metadata),
                "_runtime_compaction": metadata,
            }
        }
    )
    return context.model_copy(update={"system_agent": system_agent}), metadata


def _policy_for_context(context: AgentExecutionContext) -> AgentCompactionPolicy:
    harness = context.agent_harness or context.system_agent.harness
    if harness is None:
        return AgentCompactionPolicy()
    return harness.compaction_policy


def _select_recent_messages(
    messages: list[TimelineMessage],
    *,
    recent_message_count: int,
    trigger_message: TimelineMessage | None,
) -> list[TimelineMessage]:
    selected = list(messages[-max(recent_message_count, 0) :]) if recent_message_count > 0 else []
    if trigger_message is not None:
        selected.append(trigger_message)
    deduped: dict[UUID, TimelineMessage] = {}
    for message in selected:
        deduped[message.message_id] = message
    return sorted(deduped.values(), key=lambda item: item.sequence)


def _select_recent_memory_entries(
    entries: list[MemoryEntry],
    max_entries: int,
) -> list[MemoryEntry]:
    if max_entries <= 0:
        return []
    return list(entries[:max_entries])


def _build_context_summary_entry(
    context: AgentExecutionContext,
    *,
    selected_messages: list[TimelineMessage],
    selected_run_memory: list[MemoryEntry],
    summary_max_chars: int,
    max_run_memory_entries: int,
) -> tuple[MemoryEntry | None, list[TimelineMessage], list[MemoryEntry]]:
    if not _run_memory_enabled(context):
        return None, [], []
    selected_message_ids = {message.message_id for message in selected_messages}
    selected_run_memory_ids = {entry.memory_entry_id for entry in selected_run_memory}
    source_messages = [
        message for message in context.messages if message.message_id not in selected_message_ids
    ]
    source_run_memory = [
        entry
        for entry in context.run_memory
        if entry.entry_type != COMPACTION_SUMMARY_ENTRY_TYPE
        and entry.memory_entry_id not in selected_run_memory_ids
    ]
    if max_run_memory_entries <= 0 or (not source_messages and not source_run_memory):
        return None, source_messages, source_run_memory
    content = _summarize_older_context(
        source_messages,
        source_run_memory,
        summary_max_chars=summary_max_chars,
    )
    covered_sequence_end = max((message.sequence for message in source_messages), default=0)
    label = (
        f"Compacted context through sequence {covered_sequence_end}"
        if covered_sequence_end > 0
        else "Compacted earlier run context"
    )
    entry = MemoryEntry(
        memory_entry_id=uuid4(),
        scope="run",
        state="scratch",
        workspace_id=context.workspace.workspace_id,
        thread_id=context.thread.thread_id,
        run_id=context.run.run_id,
        entry_type=COMPACTION_SUMMARY_ENTRY_TYPE,
        content=content,
        summary=label,
        source=_COMPACTION_SUMMARY_SOURCE,
        created_by=context.participant.participant_id,
        updated_by=context.participant.participant_id,
        visibility="agents_only",
        metadata={},
    )
    return entry, source_messages, source_run_memory


async def _retrieve_thread_memory_hits(
    context: AgentExecutionContext,
    *,
    kernel: RuntimeCompactionKernel,
    policy: AgentCompactionPolicy,
) -> list[MemoryEntry]:
    if not _thread_memory_enabled(context):
        return []
    query = _retrieval_query(context)
    if not query:
        return []
    response = await kernel.search_thread_memory(
        context.thread.thread_id,
        SearchMemoryRequest(
            actor=_participant_input(context),
            query=query,
            limit=policy.retrieval_limit,
            use_provider=policy.retrieval_provider_key,
        ),
    )
    return [
        hit.entry.model_copy(
            update={
                "metadata": {
                    **dict(hit.entry.metadata),
                    _RETRIEVED_MEMORY_METADATA_KEY: True,
                }
            }
        )
        for hit in response.results
    ]


def _merge_retrieval_hits(
    selected_thread_memory: list[MemoryEntry],
    retrieval_hits: list[MemoryEntry],
) -> list[MemoryEntry]:
    merged = list(selected_thread_memory)
    seen = {entry.memory_entry_id for entry in merged}
    for entry in retrieval_hits:
        if entry.memory_entry_id in seen:
            merged = [
                candidate.model_copy(
                    update={
                        "metadata": {
                            **dict(candidate.metadata),
                            _RETRIEVED_MEMORY_METADATA_KEY: True,
                        }
                    }
                )
                if candidate.memory_entry_id == entry.memory_entry_id
                else candidate
                for candidate in merged
            ]
            continue
        seen.add(entry.memory_entry_id)
        merged.append(entry)
    return merged


def _retrieval_query(context: AgentExecutionContext) -> str:
    parts: list[str] = []
    if context.task.title.strip():
        parts.append(context.task.title.strip())
    if context.trigger_message is not None and context.trigger_message.content.strip():
        parts.append(context.trigger_message.content.strip())
    latest_visible_user_message = next(
        (
            message
            for message in reversed(context.messages)
            if message.actor.type == "user"
        ),
        None,
    )
    if (
        latest_visible_user_message is not None
        and (
            context.trigger_message is None
            or latest_visible_user_message.message_id != context.trigger_message.message_id
        )
        and latest_visible_user_message.content.strip()
    ):
        parts.append(latest_visible_user_message.content.strip())
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return "\n\n".join(deduped)


def _summarize_older_context(
    source_messages: list[TimelineMessage],
    source_run_memory: list[MemoryEntry],
    *,
    summary_max_chars: int,
) -> str:
    lines = ["Compacted older visible context."]
    if source_messages:
        lines.append("Messages:")
        for message in source_messages:
            lines.append(f"- [{message.sequence}] {_trim_text(message.content, 220)}")
    if source_run_memory:
        lines.append("Run scratch:")
        for entry in source_run_memory:
            label = entry.summary or entry.entry_type
            lines.append(f"- {label}: {_trim_text(entry.content, 220)}")
    content = "\n".join(lines)
    if len(content) <= summary_max_chars:
        return content
    return _trim_text(content, summary_max_chars)


def _replace_compaction_summary(
    entries: list[MemoryEntry],
    summary_entry: MemoryEntry,
) -> list[MemoryEntry]:
    replaced = False
    updated: list[MemoryEntry] = []
    for entry in entries:
        if entry.entry_type == COMPACTION_SUMMARY_ENTRY_TYPE:
            if not replaced:
                updated.append(summary_entry)
                replaced = True
            continue
        updated.append(entry)
    if not replaced:
        updated.insert(0, summary_entry)
    return updated


def _existing_compaction_summary(entries: list[MemoryEntry]) -> MemoryEntry | None:
    return next(
        (entry for entry in entries if entry.entry_type == COMPACTION_SUMMARY_ENTRY_TYPE),
        None,
    )


def _summary_matches_existing(
    existing: MemoryEntry | None,
    candidate: MemoryEntry,
) -> bool:
    if existing is None:
        return False
    return (
        existing.content == candidate.content
        and existing.summary == candidate.summary
        and dict(existing.metadata) == dict(candidate.metadata)
        and existing.visibility == candidate.visibility
        and existing.source == candidate.source
    )


def _participant_input(context: AgentExecutionContext) -> ParticipantInput:
    return ParticipantInput(
        participant_id=context.participant.participant_id,
        participant_type=context.participant.participant_type,
        user_id=context.participant.user_id,
        display_name=context.participant.display_name,
        description=context.participant.description,
        roles=list(context.participant.roles),
        capabilities=list(context.participant.capabilities),
        visibility_scope=context.participant.visibility_scope,
    )


def _estimate_tokens(text: str) -> int:
    return max((len(text) + 3) // 4, 1)


def _trim_text(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return cleaned[:limit]
    return cleaned[: limit - 3] + "..."


def _run_memory_enabled(context: AgentExecutionContext) -> bool:
    harness = context.agent_harness or context.system_agent.harness
    if harness is None:
        return True
    return harness.memory_policy.use_run_memory


def _thread_memory_enabled(context: AgentExecutionContext) -> bool:
    harness = context.agent_harness or context.system_agent.harness
    if harness is None:
        return True
    return harness.memory_policy.use_thread_memory
