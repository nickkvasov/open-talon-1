from __future__ import annotations

from typing import Any
from uuid import UUID

from open_talon_contracts.models import ToolCallResult


APPROVAL_RISK_LEVELS = {"high", "destructive"}


def external_operation_requires_approval(
    policy: dict[str, Any],
    *,
    risk_level: str,
    operation_key: str,
) -> bool:
    preapproved_operations = {
        item
        for item in policy.get("preapproved_operations", [])
        if isinstance(item, str)
    }
    if operation_key in preapproved_operations:
        return False
    preapproved_risk_levels = {
        item
        for item in policy.get("preapproved_risk_levels", [])
        if isinstance(item, str)
    }
    if risk_level in preapproved_risk_levels:
        return False
    required_operations = {
        item
        for item in policy.get("approval_required_operations", [])
        if isinstance(item, str)
    } | {
        item
        for item in policy.get("require_approval_operations", [])
        if isinstance(item, str)
    }
    if operation_key in required_operations:
        return True
    required_risk_levels = {
        item
        for item in policy.get("approval_required_risk_levels", [])
        if isinstance(item, str)
    } | {
        item
        for item in policy.get("require_approval_risk_levels", [])
        if isinstance(item, str)
    }
    if risk_level in required_risk_levels:
        return True
    if bool(policy.get("require_approval")):
        return True
    return risk_level in APPROVAL_RISK_LEVELS


def redact_sensitive_metadata(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        return "[redacted]"
    sensitive_fragments = {
        "authorization",
        "token",
        "secret",
        "password",
        "api_key",
        "credential",
        "bearer",
    }
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if any(fragment in normalized for fragment in sensitive_fragments):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = redact_sensitive_metadata(
                    item,
                    depth=depth + 1,
                )
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive_metadata(item, depth=depth + 1)
            for item in value
        ]
    return value


def external_operation_request_metadata(raw: dict[str, object]) -> dict[str, object]:
    redacted = redact_sensitive_metadata(raw)
    return redacted if isinstance(redacted, dict) else {}


def external_operation_request_id_from_tool_metadata(
    metadata: dict[str, Any],
) -> UUID | None:
    approval = metadata.get("external_operation_approval")
    if not isinstance(approval, dict):
        return None
    raw_request_id = approval.get("operation_request_id")
    if isinstance(raw_request_id, UUID):
        return raw_request_id
    if isinstance(raw_request_id, str) and raw_request_id:
        try:
            return UUID(raw_request_id)
        except ValueError:
            return None
    return None


def external_operation_result_metadata(
    *,
    status: str,
    tool_call_id: UUID,
    tool_name: str,
    result: ToolCallResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "outcome": status,
        "execution": "tool_call_finalized",
        "tool_call_id": str(tool_call_id),
        "tool_name": tool_name,
    }
    if result.output_payload:
        metadata["output_keys"] = sorted(result.output_payload.keys())
    if result.error:
        metadata["error"] = result.error
    if result.exit_code is not None:
        metadata["exit_code"] = result.exit_code
    return metadata
