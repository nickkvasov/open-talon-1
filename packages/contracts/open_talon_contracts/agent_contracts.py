from __future__ import annotations

from .models import AgentInteractionContract, AgentResponseContract


def interaction_contract_is_empty(contract: AgentInteractionContract | None) -> bool:
    if contract is None:
        return True
    return (
        not contract.instructions
        and not contract.thread_reply_template
        and not contract.completion_criteria
        and not contract.metadata
        and not contract.response_contract.title
        and not contract.response_contract.required_sections
        and not contract.response_contract.guidance
        and not contract.response_contract.json_schema
        and contract.response_contract.format == "markdown"
    )


def build_default_interaction_contract(
    *,
    display_name: str,
    role: str,
    description: str,
    capabilities: list[str],
) -> AgentInteractionContract:
    normalized = f"{role} {' '.join(capabilities)} {description}".lower()
    required_sections = _required_sections(normalized)
    guidance = _guidance(normalized)
    title = _title_for_role(role)
    return AgentInteractionContract(
        instructions=[
            f"Operate as {display_name}, fulfilling the role {role}.",
            "Use only the provided Open Talon execution context and be explicit about uncertainty.",
            "Return a collaborator-friendly reply suitable for the shared thread.",
        ],
        response_contract=AgentResponseContract(
            format="markdown",
            title=title,
            required_sections=required_sections,
            guidance=guidance,
        ),
        completion_criteria=[
            "Address the latest visible request.",
            "Explain evidence or lack of evidence clearly.",
            "Make the next action obvious to collaborators.",
        ],
        metadata={
            "contract_version": 1,
            "generated": True,
        },
    )


def _required_sections(normalized: str) -> list[str]:
    if "test" in normalized or "review" in normalized or "qa" in normalized:
        return [
            "Summary",
            "Checks performed",
            "Findings",
            "Residual risk",
            "Next action",
        ]
    if "research" in normalized or "analysis" in normalized:
        return [
            "Summary",
            "Evidence",
            "Open questions",
            "Next action",
        ]
    if "implement" in normalized or "coding" in normalized or "backend" in normalized:
        return [
            "Summary",
            "Proposed change",
            "Validation",
            "Residual risk",
            "Next action",
        ]
    return [
        "Summary",
        "Findings",
        "Next action",
    ]


def _guidance(normalized: str) -> list[str]:
    guidance = [
        "Keep the response concise and thread-ready.",
        "Reference concrete evidence from the visible context when possible.",
    ]
    if "test" in normalized or "review" in normalized or "qa" in normalized:
        guidance.append("State clearly whether conclusions come from actual evidence or only from the available context.")
    if "research" in normalized or "analysis" in normalized:
        guidance.append("Separate confirmed evidence from inference.")
    if "implement" in normalized or "coding" in normalized or "backend" in normalized:
        guidance.append("Call out residual implementation risk honestly.")
    return guidance


def _title_for_role(role: str) -> str:
    words = role.strip().split()
    if not words:
        return "Agent Response"
    return f"{' '.join(word.capitalize() for word in words)} Response"
