from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from gateway_edge.config import settings
from gateway_edge.main import create_app


def _cors_options(app):
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware.kwargs
    raise AssertionError("CORS middleware not found")


def test_create_app_keeps_explicit_cors_origins_when_wildcard_is_mixed(monkeypatch):
    monkeypatch.setattr(
        settings,
        "cors_origins",
        "https://admin.example.com, http://localhost:5173, *",
    )

    app = create_app()

    assert _cors_options(app)["allow_origins"] == [
        "https://admin.example.com",
        "http://localhost:5173",
    ]


def test_create_app_preserves_wildcard_cors_configuration(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "*")

    app = create_app()

    assert _cors_options(app)["allow_origins"] == ["*"]
