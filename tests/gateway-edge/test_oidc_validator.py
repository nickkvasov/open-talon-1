from __future__ import annotations

import pytest

from gateway_edge.auth import oidc as oidc_auth


@pytest.mark.asyncio
async def test_validate_oidc_token_accepts_matching_azp_without_aud(monkeypatch):
    monkeypatch.setattr(oidc_auth.settings, "oidc_issuer_url", "http://issuer.test/realms/open-talon")
    monkeypatch.setattr(oidc_auth.settings, "oidc_client_id_tui", "open-talon-tui")
    monkeypatch.setattr(oidc_auth.settings, "oidc_audience", "open-talon-tui")

    async def _oidc_configuration():
        return {"issuer": "http://issuer.test/realms/open-talon"}

    async def _jwks():
        return {"keys": []}

    monkeypatch.setattr(oidc_auth, "_oidc_configuration", _oidc_configuration)
    monkeypatch.setattr(oidc_auth, "_jwks", _jwks)
    monkeypatch.setattr(oidc_auth, "_select_key", lambda token, jwks: "fake-key")

    class _Jwt:
        @staticmethod
        def decode(token, key, algorithms, issuer, options):
            assert options == {"verify_aud": False}
            return {
                "sub": "subject-123",
                "iss": issuer,
                "azp": "open-talon-tui",
                "preferred_username": "admin",
                "email": "admin@example.com",
            }

    monkeypatch.setattr(oidc_auth, "jwt", _Jwt)

    context = await oidc_auth.validate_oidc_token("good-token")

    assert context is not None
    assert context.subject == "subject-123"
    assert context.display_name == "admin"


@pytest.mark.asyncio
async def test_validate_oidc_token_rejects_missing_aud_and_wrong_azp(monkeypatch):
    monkeypatch.setattr(oidc_auth.settings, "oidc_issuer_url", "http://issuer.test/realms/open-talon")
    monkeypatch.setattr(oidc_auth.settings, "oidc_client_id_tui", "open-talon-tui")
    monkeypatch.setattr(oidc_auth.settings, "oidc_audience", "open-talon-tui")

    async def _oidc_configuration():
        return {"issuer": "http://issuer.test/realms/open-talon"}

    async def _jwks():
        return {"keys": []}

    monkeypatch.setattr(oidc_auth, "_oidc_configuration", _oidc_configuration)
    monkeypatch.setattr(oidc_auth, "_jwks", _jwks)
    monkeypatch.setattr(oidc_auth, "_select_key", lambda token, jwks: "fake-key")

    class _Jwt:
        @staticmethod
        def decode(token, key, algorithms, issuer, options):
            return {
                "sub": "subject-123",
                "iss": issuer,
                "azp": "different-client",
                "preferred_username": "admin",
            }

    monkeypatch.setattr(oidc_auth, "jwt", _Jwt)

    context = await oidc_auth.validate_oidc_token("bad-token")

    assert context is None
