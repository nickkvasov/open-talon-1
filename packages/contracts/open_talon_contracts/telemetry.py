from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class TelemetryContext:
    source_service: str | None = None
    source_component: str | None = None
    request_id: UUID | None = None
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    thread_id: UUID | None = None
    participant_id: UUID | None = None
    system_agent_id: UUID | None = None
    task_id: UUID | None = None
    run_id: UUID | None = None
    run_step_id: UUID | None = None
    tool_call_id: UUID | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PayloadRedactionPolicy:
    rich_payloads_enabled: bool = True
    max_string_length: int = 4096
    redacted_text: str = "[REDACTED]"
    blocked_keys: tuple[str, ...] = (
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api_key",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
        "prompt",
        "messages",
        "tool_args",
        "tool_arguments",
    )


_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]+|token=[^&\s]+|authorization:\s*[^\s]+|secret=[^&\s]+)"
)


def redact_payload(
    value: Any,
    *,
    policy: PayloadRedactionPolicy,
) -> Any:
    if not policy.rich_payloads_enabled:
        return None
    if isinstance(value, dict):
        return {
            str(key): (
                policy.redacted_text
                if str(key).lower() in policy.blocked_keys
                else redact_payload(item, policy=policy)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item, policy=policy) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item, policy=policy) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        redacted = _SECRET_VALUE_PATTERN.sub(policy.redacted_text, value)
        return redacted[: policy.max_string_length]
    return value


def telemetry_metadata(
    context: TelemetryContext | None,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if context is not None:
        fields = {
            "source_service": context.source_service,
            "source_component": context.source_component,
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "causation_id": context.causation_id,
            "organization_id": context.organization_id,
            "workspace_id": context.workspace_id,
            "thread_id": context.thread_id,
            "participant_id": context.participant_id,
            "system_agent_id": context.system_agent_id,
            "task_id": context.task_id,
            "run_id": context.run_id,
            "run_step_id": context.run_step_id,
            "tool_call_id": context.tool_call_id,
            "trace_id": context.trace_id,
        }
        merged.update(
            {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in fields.items()
                if value is not None
            }
        )
        merged.update(context.metadata)
    if metadata:
        merged.update(metadata)
    return merged
