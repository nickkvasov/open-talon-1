from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from open_talon_contracts.oci_registry import (
    digest_pinned_image_ref,
    is_digest_pinned_image_ref,
    is_registry_backed_image_ref,
    strip_image_tag,
)
from open_talon_contracts.models import (
    CreateOrganizationRequest,
    CreateRetrievalContextPackRequest,
    CreateRetrievalCorpusRequest,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalSearchHit,
    RetrievalSearchResponse,
    ExecutionSpec,
    PublicationReview,
    RetrievalChunk,
    WorkspaceHarness,
    WorkspaceModerationPolicy,
    normalize_organization_slug,
)
from open_talon_contracts.secrets import SecretReference, secret_references_from_config
from open_talon_contracts.telemetry import (
    PayloadRedactionPolicy,
    TelemetryContext,
    redact_payload,
    telemetry_metadata,
)

pytestmark = pytest.mark.unit


def test_telemetry_metadata_serializes_ids_and_preserves_explicit_metadata() -> None:
    request_id = UUID("11111111-1111-1111-1111-111111111111")
    workspace_id = UUID("22222222-2222-2222-2222-222222222222")
    context = TelemetryContext(
        source_service="gateway-edge",
        request_id=request_id,
        workspace_id=workspace_id,
        metadata={"tenant": "default", "override": "context"},
    )

    metadata = telemetry_metadata(context, metadata={"override": "call", "path": "/v1/me"})

    assert metadata == {
        "source_service": "gateway-edge",
        "request_id": str(request_id),
        "workspace_id": str(workspace_id),
        "tenant": "default",
        "override": "call",
        "path": "/v1/me",
    }


def test_redact_payload_removes_sensitive_keys_and_inline_secret_values() -> None:
    payload = {
        "Authorization": "Bearer live-token",
        "nested": {
            "message": "safe prefix token=abc123 safe suffix",
            "items": [{"password": "secret-value"}, ("sk-testvalue",)],
        },
        "request_id": UUID("33333333-3333-3333-3333-333333333333"),
    }

    redacted = redact_payload(payload, policy=PayloadRedactionPolicy(max_string_length=64))

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["message"] == "safe prefix [REDACTED] safe suffix"
    assert redacted["nested"]["items"][0]["password"] == "[REDACTED]"
    assert redacted["nested"]["items"][1] == ["[REDACTED]"]
    assert redacted["request_id"] == "33333333-3333-3333-3333-333333333333"


def test_registry_image_ref_helpers_distinguish_local_names_and_digest_refs() -> None:
    assert not is_registry_backed_image_ref("python:3.12")
    assert is_registry_backed_image_ref("localhost:5000/open-talon/tool:latest")
    assert strip_image_tag("registry.example/open-talon/tool:latest") == "registry.example/open-talon/tool"
    assert (
        digest_pinned_image_ref(
            "registry.example/open-talon/tool:latest",
            "sha256:abcd",
        )
        == "registry.example/open-talon/tool@sha256:abcd"
    )
    assert is_digest_pinned_image_ref("registry.example/open-talon/tool@sha256:abcd")


def test_secret_references_from_config_supports_env_and_openbao_shapes() -> None:
    references = secret_references_from_config(
        {
            "env": {"name": "OPENAI_API_KEY", "purpose": "llm"},
            "openbao": {
                "mount": "secret",
                "path": "open-talon/providers/openai",
                "field_name": "api_key",
            },
        }
    )

    assert references == [
        SecretReference(
            provider="env",
            name="OPENAI_API_KEY",
            metadata={"name": "OPENAI_API_KEY", "purpose": "llm"},
        ),
        SecretReference(
            provider="openbao",
            mount="secret",
            path="open-talon/providers/openai",
            field_name="api_key",
            metadata={
                "mount": "secret",
                "path": "open-talon/providers/openai",
                "field_name": "api_key",
            },
        ),
    ]


def test_workspace_moderation_policy_defaults_and_normalization() -> None:
    harness = WorkspaceHarness()

    assert harness.moderation_policy.enabled is True
    assert harness.moderation_policy.level == "balanced"

    policy = WorkspaceModerationPolicy(
        topic="  Runtime architecture  ",
        allowed_adjacent_topics=[" docs ", "", "tests"],
        blocked_topics=[" hiring  ", ""],
    )

    assert policy.topic == "Runtime architecture"
    assert policy.allowed_adjacent_topics == ["docs", "tests"]
    assert policy.blocked_topics == ["hiring"]
    assert policy.model_dump(mode="json")["explain_blocked_messages"] is True


def test_publication_review_serialization_is_generic() -> None:
    review_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    message_id = uuid4()
    reviewer_id = uuid4()
    participant_id = uuid4()

    review = PublicationReview(
        review_id=review_id,
        review_kind="workspace_topic_alignment",
        workspace_id=workspace_id,
        thread_id=thread_id,
        message_id=message_id,
        reviewer_system_agent_id=reviewer_id,
        candidate_actor_participant_id=participant_id,
        phase="pre_publish",
        level="strict",
        status="suppressed",
        decision="suppress",
        policy_snapshot={"topic": "Runtime architecture"},
    )

    payload = review.model_dump(mode="json")

    assert payload["review_kind"] == "workspace_topic_alignment"
    assert payload["decision"] == "suppress"
    assert payload["policy_snapshot"]["topic"] == "Runtime architecture"


def test_organization_slug_normalization_is_shared_by_request_models() -> None:
    assert normalize_organization_slug("  Platform Ops!!Team  ") == "platform-ops-team"

    request = CreateOrganizationRequest(
        actor={
            "participant_id": "00000000-0000-0000-0000-000000000001",
            "participant_type": "user",
            "display_name": "Admin",
        },
        slug="  Platform Ops!!Team  ",
        name="Platform Ops Team",
    )

    assert request.slug == "platform-ops-team"


def test_retrieval_contracts_serialize_scoped_search_payloads() -> None:
    actor = {
        "participant_id": "00000000-0000-0000-0000-000000000001",
        "participant_type": "user",
        "display_name": "Researcher",
    }
    corpus = RetrievalCorpus(
        corpus_id=uuid4(),
        scope="workspace",
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name="Playbook",
        created_by=uuid4(),
    )
    chunk = RetrievalChunk(
        chunk_id=uuid4(),
        corpus_id=corpus.corpus_id,
        source_id=uuid4(),
        scope="workspace",
        organization_id=corpus.organization_id,
        workspace_id=corpus.workspace_id,
        content="A cited retrieval chunk.",
        content_hash="sha256",
    )
    hit = RetrievalSearchHit(chunk=chunk, score=0.9, rank=1)
    response = RetrievalSearchResponse(
        run={
            "run_id": uuid4(),
            "run_kind": "search",
            "scope": "workspace",
            "organization_id": corpus.organization_id,
            "workspace_id": corpus.workspace_id,
            "query": "chunk",
            "created_by": uuid4(),
        },
        hits=[hit],
    )
    context_request = CreateRetrievalContextPackRequest(
        actor=actor,
        query="chunk",
        corpus_ids=[corpus.corpus_id],
        provider_overrides={"embedding_model": "local-test"},
    )

    assert CreateRetrievalCorpusRequest(actor=actor, name="Playbook").name == "Playbook"
    assert response.model_dump(mode="json")["hits"][0]["rank"] == 1
    assert context_request.provider_overrides["embedding_model"] == "local-test"
    assert RetrievalContextPack(
        context_pack_id=uuid4(),
        query="chunk",
        content="[1] source\nA cited retrieval chunk.",
        hits=[hit],
        created_by=uuid4(),
    ).hits[0].chunk.content == "A cited retrieval chunk."


def test_execution_spec_accepts_legacy_workspace_ref_alias() -> None:
    spec = ExecutionSpec.model_validate(
        {
            "invocation_id": str(uuid4()),
            "handler_ref": "registry.example/open-talon/tool@sha256:abcd",
            "workspace_ref": {
                "mode": "local_path",
                "path": "/workspace",
            },
        }
    )

    assert spec.execution_workspace is not None
    assert spec.execution_workspace.mode == "local_path"
    assert spec.execution_workspace.path == "/workspace"
    assert "workspace_ref" not in spec.model_dump(mode="json")
    assert spec.model_dump(mode="json", by_alias=True)["execution_workspace"] == {
        "mode": "local_path",
        "workspace_id": None,
        "uri": None,
        "path": "/workspace",
        "metadata": {},
    }
