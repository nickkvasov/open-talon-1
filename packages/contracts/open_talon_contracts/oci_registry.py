from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OciRegistryConfig:
    base_url: str | None = None
    username: str | None = None
    password_secret_config: dict[str, object] = field(default_factory=dict)
    repository_prefix: str | None = None
    validate_on_startup: bool = True


def is_registry_backed_image_ref(image_ref: str | None) -> bool:
    if image_ref is None:
        return False
    candidate = image_ref.strip()
    if not candidate or "://" in candidate:
        return False
    repository = strip_image_tag(candidate)
    if not repository or "/" not in repository:
        return False
    registry_host = repository.split("/", 1)[0]
    return "." in registry_host or ":" in registry_host or registry_host == "localhost"


def is_digest(value: str | None) -> bool:
    return bool(value and value.strip().startswith("sha256:"))


def is_digest_pinned_image_ref(image_ref: str | None) -> bool:
    if image_ref is None:
        return False
    repository, digest = image_ref.split("@", 1) if "@" in image_ref else (image_ref, None)
    return bool(repository and is_registry_backed_image_ref(repository) and is_digest(digest))


def strip_image_tag(image_ref: str) -> str:
    repository = image_ref.split("@", 1)[0].strip()
    if not repository:
        return repository
    last_slash = repository.rfind("/")
    last_colon = repository.rfind(":")
    if last_colon > last_slash:
        return repository[:last_colon]
    return repository


def digest_pinned_image_ref(image_ref: str | None, image_digest: str | None) -> str | None:
    if not is_registry_backed_image_ref(image_ref) or not is_digest(image_digest):
        return None
    return f"{strip_image_tag(str(image_ref).strip())}@{str(image_digest).strip()}"


__all__ = [
    "OciRegistryConfig",
    "digest_pinned_image_ref",
    "is_digest",
    "is_digest_pinned_image_ref",
    "is_registry_backed_image_ref",
    "strip_image_tag",
]
