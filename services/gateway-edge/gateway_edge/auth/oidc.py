from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from gateway_edge.config import settings
from gateway_edge.models import AuthContext

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import availability depends on environment setup
    import jwt
    from jwt.algorithms import RSAAlgorithm
except ImportError:  # pragma: no cover - exercised indirectly by runtime configuration
    jwt = None
    RSAAlgorithm = None


@dataclass
class _CachedValue:
    value: dict[str, Any]
    expires_at: float


_DISCOVERY_CACHE: dict[str, _CachedValue] = {}
_JWKS_CACHE: dict[str, _CachedValue] = {}


def _cache_valid(item: _CachedValue | None) -> bool:
    return item is not None and item.expires_at > time.monotonic()


async def _fetch_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _oidc_configuration() -> dict[str, Any]:
    issuer = settings.oidc_issuer_url.rstrip("/")
    cached = _DISCOVERY_CACHE.get(issuer)
    if _cache_valid(cached):
        return cached.value
    config = await _fetch_json(f"{issuer}/.well-known/openid-configuration")
    _DISCOVERY_CACHE[issuer] = _CachedValue(
        value=config,
        expires_at=time.monotonic() + settings.oidc_cache_ttl_seconds,
    )
    return config


async def _jwks() -> dict[str, Any]:
    config = await _oidc_configuration()
    jwks_uri = config["jwks_uri"]
    cached = _JWKS_CACHE.get(jwks_uri)
    if _cache_valid(cached):
        return cached.value
    jwks = await _fetch_json(jwks_uri)
    _JWKS_CACHE[jwks_uri] = _CachedValue(
        value=jwks,
        expires_at=time.monotonic() + settings.oidc_cache_ttl_seconds,
    )
    return jwks


def _select_key(token: str, jwks: dict[str, Any]):
    if jwt is None or RSAAlgorithm is None:
        raise RuntimeError(
            "OIDC JWT support requires the 'pyjwt' and 'cryptography' packages to be installed"
        )
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    for jwk in jwks.get("keys", []):
        if kid is None or jwk.get("kid") == kid:
            return RSAAlgorithm.from_jwk(json.dumps(jwk))
    raise ValueError(f"No JWKS key found for kid={kid!r}")


def _extract_roles(claims: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        for role in realm_access.get("roles", []):
            if isinstance(role, str) and role not in roles:
                roles.append(role)
    resource_access = claims.get("resource_access")
    client_id = settings.oidc_client_id_tui
    if isinstance(resource_access, dict):
        client_roles = resource_access.get(client_id)
        if isinstance(client_roles, dict):
            for role in client_roles.get("roles", []):
                if isinstance(role, str) and role not in roles:
                    roles.append(role)
    return roles


def _expected_audiences() -> set[str]:
    audiences = {settings.oidc_client_id_tui}
    if settings.oidc_audience:
        audiences.add(settings.oidc_audience)
    return {value for value in audiences if value}


def _claims_match_expected_client(claims: dict[str, Any]) -> bool:
    expected = _expected_audiences()
    aud_claim = claims.get("aud")
    if isinstance(aud_claim, str):
        if aud_claim in expected:
            return True
    elif isinstance(aud_claim, list):
        for value in aud_claim:
            if isinstance(value, str) and value in expected:
                return True
    azp_claim = claims.get("azp")
    return isinstance(azp_claim, str) and azp_claim in expected


async def validate_oidc_token(token: str) -> AuthContext | None:
    try:
        config = await _oidc_configuration()
        key = _select_key(token, await _jwks())
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer_url.rstrip("/"),
            options={"verify_aud": False},
        )
        if not _claims_match_expected_client(claims):
            raise ValueError("OIDC token client does not match expected audience or azp")
        display_name = (
            claims.get("name")
            or claims.get("preferred_username")
            or claims.get("email")
            or claims.get("sub")
        )
        return AuthContext(
            kind="oidc",
            issuer=config.get("issuer", settings.oidc_issuer_url.rstrip("/")),
            subject=str(claims["sub"]),
            email=claims.get("email"),
            display_name=str(display_name),
            roles=_extract_roles(claims),
            claims=claims,
        )
    except Exception as exc:  # pragma: no cover - covered by route tests through monkeypatching
        logger.debug("OIDC token validation failed: %s", exc)
        return None
