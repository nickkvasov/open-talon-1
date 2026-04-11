from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts"
if _CONTRACTS_DIR.is_dir():
    contracts_path = str(_CONTRACTS_DIR)
    if contracts_path not in sys.path:
        sys.path.insert(0, contracts_path)

from open_talon_contracts.models import (  # noqa: E402
    AgentDefinition,
    AgentExecutionContext,
    AgentInteractionContract,
    AgentRunResult,
    EventEnvelope,
)

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


class RuntimeObservation(Protocol):
    def update(self, **kwargs: Any) -> None: ...


class RuntimeObservability(Protocol):
    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def flush(self) -> None: ...


class _NoopObservation:
    def __enter__(self) -> "_NoopObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **kwargs: Any) -> None:
        return None


class LangfuseRuntimeObserver:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "LangfuseRuntimeObserver":
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        if not public_key or not secret_key:
            return cls()

        base_url = (
            os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST")
            or os.getenv("LANGFUSE_PUBLIC_URL")
        )
        if base_url and "LANGFUSE_BASE_URL" not in os.environ:
            os.environ["LANGFUSE_BASE_URL"] = base_url

        try:
            from langfuse import get_client
        except ImportError:
            logger.warning(
                "Langfuse credentials are configured but the Python SDK is not installed. "
                "Install the 'langfuse' package to enable runtime tracing."
            )
            return cls()

        try:
            return cls(get_client())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to initialize Langfuse client: %s", exc)
            return cls()

    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            return _NoopObservation()
        return self._client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        )

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            return _NoopObservation()
        return self._client.start_as_current_observation(
            name=name,
            as_type="generation",
            model=model,
            input=input,
            metadata=metadata,
        )

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Langfuse flush failed: %s", exc)


class RuntimeKernel(Protocol):
    async def list_system_agents(self) -> list[AgentDefinition]: ...

    async def list_pending_tasks_for_system_agent(
        self,
        system_agent_id: UUID,
        *,
        limit: int = 10,
    ) -> list[Any]: ...

    async def claim_task_for_system_agent(self, task_id: UUID, system_agent_id: UUID) -> Any: ...

    async def append_run_progress(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        content: str,
    ) -> Any: ...

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ) -> Any: ...

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: str = "tool_failure",
    ) -> Any: ...


class AgentExecutor(Protocol):
    async def execute(self, context: AgentExecutionContext) -> AgentRunResult: ...


class LocalOllamaExecutor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        observability: RuntimeObservability | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._observability = observability or LangfuseRuntimeObserver()

    async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
        endpoint = context.system_agent.endpoint
        url = endpoint.url or DEFAULT_OLLAMA_URL
        model = (
            endpoint.model
            or _definition_runtime_value(context, "model")
            or "gemma4:latest"
        )
        prompt = render_prompt(context)
        logger.debug(
            "LocalOllamaExecutor execute agent_id=%s model=%s thread_id=%s",
            context.system_agent.agent_id,
            model,
            context.thread.thread_id,
        )
        request_payload = {
            "model": model,
            "system": context.system_agent.system_prompt,
            "prompt": prompt,
            "stream": False,
        }
        _debug_prompt_payload("local-ollama", context, request_payload)
        with self._observability.start_generation(
            name="local-ollama-generate",
            model=model,
            input=request_payload,
            metadata=_langfuse_metadata(context, endpoint_url=url, provider="ollama"),
        ) as observation:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(url, json=request_payload)
                response.raise_for_status()
                payload = response.json()
        message = _format_thread_message(
            context,
            _extract_text_response(payload),
        )
        usage_details = _ollama_usage_details(payload)
        observation.update(
            output=message,
            model=model,
            usage_details=usage_details or None,
            metadata={
                "provider": "ollama",
                "endpoint_kind": endpoint.kind,
                "done": payload.get("done"),
                "done_reason": payload.get("done_reason"),
            },
        )
        return AgentRunResult(
            stop_reason="completed",
            message=message,
            summary="Completed with local Ollama",
            metadata={
                "provider": "ollama",
                "model": model,
                "endpoint_kind": endpoint.kind,
            },
        )


class HttpEndpointExecutor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        endpoint_scope: str = "remote",
        observability: RuntimeObservability | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._endpoint_scope = endpoint_scope
        self._observability = observability or LangfuseRuntimeObserver()

    async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
        endpoint = context.system_agent.endpoint
        if not endpoint.url:
            raise ValueError(
                f"{self._endpoint_scope.capitalize()} agent {context.system_agent.agent_id} is missing an endpoint URL"
            )
        logger.debug(
            "HttpEndpointExecutor execute scope=%s agent_id=%s url=%s thread_id=%s",
            self._endpoint_scope,
            context.system_agent.agent_id,
            endpoint.url,
            context.thread.thread_id,
        )
        request_payload = {
            "agent": context.system_agent.model_dump(mode="json"),
            "participant": context.participant.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
            "system_prompt": context.system_agent.system_prompt,
            "interaction_contract": _interaction_contract(context).model_dump(mode="json"),
            "prompt": render_prompt(context),
        }
        _debug_prompt_payload(f"{self._endpoint_scope}-endpoint", context, request_payload)
        use_generation = bool(endpoint.model)
        start_observation = (
            self._observability.start_generation
            if use_generation
            else self._observability.start_span
        )
        kwargs = {
            "name": f"{self._endpoint_scope}-agent-execute",
            "input": request_payload,
            "metadata": _langfuse_metadata(
                context,
                endpoint_url=endpoint.url,
                provider=self._endpoint_scope,
            ),
        }
        if use_generation:
            kwargs["model"] = endpoint.model
        with start_observation(**kwargs) as observation:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(endpoint.url, json=request_payload)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    payload = response.json()
                else:
                    payload = {"message": response.text}
            observation.update(
                output=payload,
                metadata={
                    "provider": self._endpoint_scope,
                    "endpoint_kind": endpoint.kind,
                    "status_code": response.status_code,
                },
            )
        return _coerce_run_result(payload, context=context)


class AgentTaskRuntime:
    def __init__(
        self,
        *,
        kernel: RuntimeKernel,
        publish_events: Callable[[list[EventEnvelope]], Awaitable[None]],
        poll_interval_seconds: float = 1.0,
        max_pending_tasks_per_agent: int = 4,
        progress_events_enabled: bool = True,
        model_timeout_seconds: float = 60.0,
        executors: dict[str, AgentExecutor] | None = None,
        observability: RuntimeObservability | None = None,
    ) -> None:
        self._kernel = kernel
        self._publish_events = publish_events
        self._poll_interval_seconds = poll_interval_seconds
        self._max_pending_tasks_per_agent = max_pending_tasks_per_agent
        self._progress_events_enabled = progress_events_enabled
        self._loop_task: asyncio.Task[None] | None = None
        self._processing_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._observability = observability or LangfuseRuntimeObserver.from_env()
        self._executors = executors or {
            "local": LocalOllamaExecutor(
                timeout_seconds=model_timeout_seconds,
                observability=self._observability,
            ),
            "remote": HttpEndpointExecutor(
                timeout_seconds=model_timeout_seconds,
                endpoint_scope="remote",
                observability=self._observability,
            ),
            "system": HttpEndpointExecutor(
                timeout_seconds=model_timeout_seconds,
                endpoint_scope="system",
                observability=self._observability,
            ),
        }

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        logger.info("Agent task runtime started")
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        pending = list(self._processing_tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._processing_tasks.clear()
        self._observability.flush()
        logger.info("Agent task runtime stopped")

    async def _run_loop(self) -> None:
        try:
            while True:
                await self._run_iteration()
                await asyncio.sleep(self._poll_interval_seconds)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            logger.debug("Agent task runtime loop cancelled")
            raise

    async def _run_iteration(self) -> None:
        agents = await self._kernel.list_system_agents()
        logger.debug("Agent task runtime poll agents=%s", len(agents))
        for agent in agents:
            pending_tasks = await self._kernel.list_pending_tasks_for_system_agent(
                agent.agent_id,
                limit=self._max_pending_tasks_per_agent,
            )
            for task in pending_tasks:
                if task.task_id in self._processing_tasks:
                    continue
                logger.debug(
                    "Agent task runtime scheduling task_id=%s system_agent_id=%s",
                    task.task_id,
                    agent.agent_id,
                )
                background = asyncio.create_task(
                    self._process_task(agent.agent_id, task.task_id)
                )
                self._processing_tasks[task.task_id] = background
                background.add_done_callback(
                    lambda done, task_id=task.task_id: self._processing_tasks.pop(
                        task_id,
                        None,
                    )
                )

    async def _process_task(self, system_agent_id: UUID, task_id: UUID) -> None:
        logger.debug(
            "Agent task runtime processing task_id=%s system_agent_id=%s",
            task_id,
            system_agent_id,
        )
        run_id: UUID | None = None
        try:
            claim = await self._kernel.claim_task_for_system_agent(task_id, system_agent_id)
            if not claim.events:
                return
            await self._publish_events(claim.events)
            if claim.run is None or claim.context is None:
                raise RuntimeError(
                    f"Task {task_id} did not produce a run/context during claim"
                )
            run_id = claim.run.run_id
            context = claim.context
            with self._observability.start_span(
                name="agent-task-run",
                input={
                    "task_id": str(task_id),
                    "run_id": str(run_id),
                    "system_agent_id": str(system_agent_id),
                    "thread_id": str(context.thread.thread_id),
                },
                metadata=_langfuse_metadata(
                    context,
                    task_id=task_id,
                    run_id=run_id,
                    provider=context.system_agent.endpoint.kind,
                ),
            ) as observation:
                if self._progress_events_enabled:
                    progress = await self._kernel.append_run_progress(
                        run_id,
                        system_agent_id,
                        f"Executing {context.system_agent.display_name}",
                    )
                    await self._publish_events(progress.events)
                executor = self._executor_for(context)
                result = await executor.execute(context)
                result = _normalize_run_result(result, context=context)
                observation.update(
                    output=result.model_dump(mode="json"),
                    metadata={"stop_reason": result.stop_reason},
                )
                completion = await self._kernel.complete_run(run_id, system_agent_id, result)
                await self._publish_events(completion.events)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception as exc:
            logger.exception(
                "Agent task runtime failed task_id=%s system_agent_id=%s: %s",
                task_id,
                system_agent_id,
                exc,
            )
            if run_id is not None:
                failed = await self._kernel.fail_run(
                    run_id,
                    system_agent_id,
                    str(exc),
                )
                await self._publish_events(failed.events)
        finally:
            self._observability.flush()

    def _executor_for(self, context: AgentExecutionContext) -> AgentExecutor:
        kind = context.system_agent.endpoint.kind
        try:
            return self._executors[kind]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"No executor configured for endpoint kind {kind!r}") from exc


def render_prompt(context: AgentExecutionContext) -> str:
    contract = _interaction_contract(context)
    participant_lines = []
    for participant in context.participants:
        role_text = ", ".join(participant.roles) if participant.roles else "no declared role"
        capability_text = (
            ", ".join(participant.capabilities)
            if participant.capabilities
            else "no declared capabilities"
        )
        participant_lines.append(
            f"- {participant.display_name} ({participant.participant_type}) | "
            f"roles: {role_text} | capabilities: {capability_text}"
        )

    memory_lines = []
    for entry in context.memory_entries:
        memory_lines.append(
            f"- [{entry.entry_type}] {entry.title}: {entry.content}"
        )

    message_lines = []
    for message in context.messages:
        author = _message_author_name(context, message.actor.id)
        message_lines.append(
            f"[{message.sequence}] {author}: {message.content}"
        )

    role_lines = []
    for role_definition in context.role_definitions:
        role_lines.append(f"- {role_definition.name}: {role_definition.definition}")

    tool_lines = []
    for tool in context.workspace_tools:
        tool_lines.append(
            f"- {tool.name} | enabled: {'yes' if tool.enabled else 'no'} | {tool.description}"
        )

    tool_result_lines = []
    for tool_result in context.tool_results:
        if tool_result.result is None:
            continue
        status_text = tool_result.status
        summary = tool_result.result.error or json.dumps(
            tool_result.result.output_payload,
            sort_keys=True,
        )
        tool_result_lines.append(
            f"- {tool_result.tool_name} | status: {status_text} | result: {summary}"
        )

    trigger_text = context.trigger_message.content if context.trigger_message else ""
    sections = [
        f"Workspace: {context.workspace.name}",
        f"Thread: {context.thread.title}",
        f"Agent role: {context.system_agent.role}",
        f"Agent description: {context.system_agent.description}",
        f"Sequence ceiling: {context.sequence_ceiling}",
        "",
        "Workspace participants:",
        "\n".join(participant_lines) or "- none",
        "",
        "Workspace role catalog:",
        "\n".join(role_lines) or "- none",
        "",
        "Workspace tools:",
        "\n".join(tool_lines) or "- none",
        "",
        "Completed tool results:",
        "\n".join(tool_result_lines) or "- none",
        "",
        "Workspace memory:",
        "\n".join(memory_lines) or "- none",
        "",
        "Visible thread messages:",
        "\n".join(message_lines) or "- none",
        "",
        "Triggering message:",
        trigger_text or "- none",
        "",
        "Instructions:",
        "Respond as the attached agent participant for this workspace.",
        "Use only the visible context above.",
        "Return a concise, thread-ready response that matches the agent role.",
    ]
    if contract.instructions:
        sections.extend(["", "Agent instructions:", *[f"- {item}" for item in contract.instructions]])
    response_contract = contract.response_contract
    sections.extend(
        [
            "",
            "Response contract:",
            f"- format: {response_contract.format}",
            f"- title: {response_contract.title or 'none'}",
            f"- required sections: {', '.join(response_contract.required_sections) or 'none'}",
        ]
    )
    if response_contract.guidance:
        sections.extend(
            ["- guidance:"] + [f"  - {item}" for item in response_contract.guidance]
        )
    if contract.completion_criteria:
        sections.extend(
            ["", "Completion criteria:", *[f"- {item}" for item in contract.completion_criteria]]
        )
    return "\n".join(sections)


def _message_author_name(context: AgentExecutionContext, actor_id: UUID) -> str:
    for participant in context.participants:
        if participant.participant_id == actor_id:
            return participant.display_name
    return str(actor_id)


def _definition_runtime_value(context: AgentExecutionContext, key: str) -> Any:
    runtime = context.system_agent.definition.get("runtime")
    if isinstance(runtime, dict):
        return runtime.get(key)
    return None


def _extract_text_response(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("response"), str):
            return payload["response"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        if isinstance(payload.get("text"), str):
            return payload["text"]
    if isinstance(payload, str):
        return payload
    return json.dumps(payload)


def _coerce_run_result(
    payload: Any,
    *,
    context: AgentExecutionContext | None = None,
) -> AgentRunResult:
    if isinstance(payload, AgentRunResult):
        return payload
    if isinstance(payload, dict):
        if any(key in payload for key in {"stop_reason", "message", "artifacts", "tool_calls"}):
            result = AgentRunResult.model_validate(payload)
            if context is not None and result.message:
                result = result.model_copy(
                    update={"message": _format_thread_message(context, result.message)}
                )
            return result
        if isinstance(payload.get("response"), str):
            return AgentRunResult(
                stop_reason="completed",
                message=_format_thread_message(context, payload["response"])
                if context is not None
                else payload["response"],
                summary="Completed with remote agent endpoint",
                metadata={"raw_payload": payload},
            )
        if isinstance(payload.get("message"), str):
            return AgentRunResult(
                stop_reason="completed",
                message=_format_thread_message(context, payload["message"])
                if context is not None
                else payload["message"],
                summary="Completed with remote agent endpoint",
                metadata={"raw_payload": payload},
            )
    return AgentRunResult(
        stop_reason="completed",
        message=_format_thread_message(context, _extract_text_response(payload))
        if context is not None
        else _extract_text_response(payload),
        summary="Completed with remote agent endpoint",
    )


def _normalize_run_result(
    result: AgentRunResult,
    *,
    context: AgentExecutionContext,
) -> AgentRunResult:
    if result.message is None:
        return result
    return result.model_copy(update={"message": _format_thread_message(context, result.message)})


def _format_thread_message(
    context: AgentExecutionContext | None,
    body: str,
) -> str:
    if context is None:
        return body.strip()
    contract = _interaction_contract(context)
    header = f"{context.system_agent.display_name} ({context.system_agent.role})"
    title = contract.response_contract.title
    template = contract.thread_reply_template
    cleaned = body.strip()
    if template:
        try:
            rendered = template.format(
                agent_name=context.system_agent.display_name,
                agent_role=context.system_agent.role,
                body=cleaned,
                title=title or "",
            ).strip()
            return rendered
        except KeyError:
            logger.warning(
                "Invalid thread_reply_template for agent_id=%s",
                context.system_agent.agent_id,
            )
    if title:
        return f"{header}\n\n{title}\n\n{cleaned}"
    return f"{header}\n\n{cleaned}"


def _interaction_contract(context: AgentExecutionContext) -> AgentInteractionContract:
    return (
        context.thread_reply_contract
        or context.system_agent.interaction_contract
        or AgentInteractionContract()
    )


def _langfuse_metadata(
    context: AgentExecutionContext,
    *,
    endpoint_url: str | None = None,
    provider: str | None = None,
    task_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "workspace_id": str(context.workspace.workspace_id),
        "thread_id": str(context.thread.thread_id),
        "system_agent_id": str(context.system_agent.agent_id),
        "participant_id": str(context.participant.participant_id),
        "trigger_message_id": (
            str(context.trigger_message.message_id) if context.trigger_message else None
        ),
        "endpoint_kind": context.system_agent.endpoint.kind,
        "endpoint_url": endpoint_url,
        "provider": provider,
        "task_id": str(task_id) if task_id else None,
        "run_id": str(run_id) if run_id else None,
    }


def _ollama_usage_details(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    prompt_tokens = payload.get("prompt_eval_count")
    completion_tokens = payload.get("eval_count")
    usage: dict[str, int] = {}
    if isinstance(prompt_tokens, int):
        usage["prompt_tokens"] = prompt_tokens
    if isinstance(completion_tokens, int):
        usage["completion_tokens"] = completion_tokens
    if usage:
        usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
            "completion_tokens", 0
        )
    return usage


def _debug_prompt_payload(
    source: str,
    context: AgentExecutionContext,
    request_payload: dict[str, Any],
) -> None:
    if os.getenv("AGENT_RUNTIME_DEBUG_PROMPTS", "").lower() not in {"1", "true", "yes", "on"}:
        return

    record = {
        "source": source,
        "workspace_id": str(context.workspace.workspace_id),
        "thread_id": str(context.thread.thread_id),
        "system_agent_id": str(context.system_agent.agent_id),
        "task_id": str(context.task.task_id),
        "run_id": str(context.run.run_id),
        "message_count": len(context.messages),
        "trigger_message_id": (
            str(context.trigger_message.message_id) if context.trigger_message is not None else None
        ),
        "request": request_payload,
    }

    target = os.getenv("AGENT_RUNTIME_DEBUG_PROMPTS_FILE")
    if target:
        target_path = Path(target)
    else:
        target_path = Path.cwd() / ".run" / "agent-runtime-prompts.jsonl"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, default=str))
        handle.write("\n")
