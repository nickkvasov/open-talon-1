from __future__ import annotations

import os
import sys

import pytest

_SERVICE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/web-search-mcp")
)
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from web_search_mcp import main as web_search  # noqa: E402


@pytest.mark.asyncio
async def test_mcp_lists_web_search_tools():
    response = await web_search._handle_rpc(  # noqa: SLF001
        {"jsonrpc": "2.0", "id": "test", "method": "tools/list", "params": {}}
    )

    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"search", "fetch", "search_and_fetch"}
    assert tools[0]["inputSchema"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_search_returns_citations_from_searxng(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Open Talon",
                        "url": "https://example.test/open-talon",
                        "content": "Local-first collaboration.",
                        "engine": "fake",
                        "score": 1,
                    }
                ],
                "unresponsive_engines": [],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.params = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, **kwargs):
            self.params = params
            return FakeResponse()

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeAsyncClient)

    result = await web_search.search({"query": "open talon", "limit": 1})

    assert result["results"][0]["url"] == "https://example.test/open-talon"
    assert result["citations"] == [
        {"id": "web-1", "title": "Open Talon", "url": "https://example.test/open-talon"}
    ]
    assert result["metadata"]["source"] == "searxng"


@pytest.mark.asyncio
async def test_fetch_returns_crawl_markdown_and_asset_candidate(monkeypatch):
    async def fake_fetch_url(url, *, max_chars):
        assert max_chars == 4000
        return web_search.FetchResult(
            url=url,
            title="Example Page",
            markdown="# Example\n\nExtracted by Crawl4AI.",
            metadata={"crawl_status": "completed", "extractor": "crawl4ai"},
        )

    monkeypatch.setattr(web_search, "fetch_url", fake_fetch_url)

    result = await web_search.fetch(
        {
            "url": "https://example.test/page",
            "max_chars": 4000,
            "persist_asset": True,
        }
    )

    assert result["markdown"].startswith("# Example")
    assert result["metadata"]["crawl_status"] == "completed"
    assert result["asset_candidate"]["filename"] == "example-page.md"
    assert result["asset_candidate"]["metadata"]["source_url"] == "https://example.test/page"
