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


pytestmark = pytest.mark.unit


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
async def test_search_sends_structured_query_params_to_searxng(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [], "unresponsive_engines": ["slow-engine"]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["trust_env"] = kwargs.get("trust_env")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, **kwargs):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeAsyncClient)

    result = await web_search.search(
        {
            "query": "open talon plugins",
            "limit": 3,
            "language": "en-US",
            "categories": ["general", "it"],
            "time_range": "week",
            "safe_search": 2,
            "engines": ["duckduckgo", "brave"],
        }
    )

    assert captured["url"].endswith("/search")
    assert captured["trust_env"] is False
    assert captured["params"] == {
        "q": "open talon plugins",
        "format": "json",
        "safesearch": 2,
        "language": "en-US",
        "time_range": "week",
        "categories": "general,it",
        "engines": "duckduckgo,brave",
    }
    assert result["metadata"]["unresponsive_engines"] == ["slow-engine"]


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


@pytest.mark.asyncio
async def test_fetch_url_falls_back_when_crawl4ai_fails(monkeypatch):
    async def fake_crawl4ai_fetch(url, *, max_chars):
        raise RuntimeError("browser unavailable")

    async def fake_http_fallback_fetch(url, *, max_chars):
        return web_search.FetchResult(
            url=url,
            title="Fallback Page",
            markdown="Fallback markdown",
            metadata={"crawl_status": "completed", "extractor": "httpx_html_parser"},
        )

    monkeypatch.setattr(web_search, "_crawl4ai_fetch", fake_crawl4ai_fetch)
    monkeypatch.setattr(web_search, "_http_fallback_fetch", fake_http_fallback_fetch)

    result = await web_search.fetch_url("https://example.test/fallback", max_chars=2000)

    assert result.title == "Fallback Page"
    assert result.markdown == "Fallback markdown"
    assert result.metadata["crawl_status"] == "fallback"
    assert result.metadata["crawl4ai_error"] == "browser unavailable"


@pytest.mark.asyncio
async def test_search_and_fetch_preserves_citations_and_page_failures(monkeypatch):
    async def fake_search(arguments):
        return {
            "query": arguments["query"],
            "results": [
                {
                    "rank": 1,
                    "title": "Good",
                    "url": "https://example.test/good",
                    "snippet": "Good result",
                },
                {
                    "rank": 2,
                    "title": "Bad",
                    "url": "https://example.test/bad",
                    "snippet": "Bad result",
                },
            ],
            "citations": [{"id": "web-1", "title": "Good", "url": "https://example.test/good"}],
            "metadata": {"source": "searxng", "result_count": 2},
        }

    async def fake_fetch_url(url, *, max_chars):
        if url.endswith("/bad"):
            raise RuntimeError("fetch failed")
        return web_search.FetchResult(
            url=url,
            title="Good",
            markdown="# Good",
            metadata={"crawl_status": "completed", "extractor": "crawl4ai"},
        )

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr(web_search, "fetch_url", fake_fetch_url)

    result = await web_search.search_and_fetch(
        {
            "query": "open talon",
            "fetch_limit": 2,
            "max_chars_per_page": 4000,
            "persist_assets": True,
        }
    )

    assert result["citations"] == [
        {"id": "web-1", "title": "Good", "url": "https://example.test/good"}
    ]
    assert result["metadata"]["page_count"] == 2
    assert result["pages"][0]["markdown"] == "# Good"
    assert result["pages"][0]["asset_candidate"]["filename"] == "good.md"
    assert result["pages"][1]["url"] == "https://example.test/bad"
    assert result["pages"][1]["metadata"]["crawl_status"] == "failed"
    assert result["pages"][1]["error"] == "fetch failed"
