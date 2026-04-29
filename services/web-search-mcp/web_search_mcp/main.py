from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
import json
import os
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import uvicorn


SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_MCP_TIMEOUT_SECONDS", "30"))
DEFAULT_MAX_MARKDOWN_CHARS = int(os.getenv("WEB_SEARCH_MCP_DEFAULT_MAX_MARKDOWN_CHARS", "12000"))
MAX_SEARCH_LIMIT = int(os.getenv("WEB_SEARCH_MCP_MAX_SEARCH_LIMIT", "20"))
MAX_FETCH_LIMIT = int(os.getenv("WEB_SEARCH_MCP_MAX_FETCH_LIMIT", "5"))

app = FastAPI(title="Open Talon Web Search MCP", version="0.1.0")


SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query."},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT, "default": 5},
        "language": {"type": "string", "description": "SearXNG language code."},
        "categories": {"type": "array", "items": {"type": "string"}},
        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "safe_search": {"type": "integer", "minimum": 0, "maximum": 2, "default": 1},
        "engines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["query"],
    "additionalProperties": False,
}

FETCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
        "query_context": {"type": "string", "description": "Optional query context for citations."},
        "max_chars": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 100000,
            "default": DEFAULT_MAX_MARKDOWN_CHARS,
        },
        "persist_asset": {
            "type": "boolean",
            "default": False,
            "description": "Return an asset candidate for authorized Open Talon persistence.",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}

SEARCH_AND_FETCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        **SEARCH_INPUT_SCHEMA["properties"],
        "fetch_limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_FETCH_LIMIT,
            "default": 3,
        },
        "max_chars_per_page": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 100000,
            "default": 8000,
        },
        "persist_assets": {
            "type": "boolean",
            "default": False,
            "description": "Return asset candidates for authorized Open Talon persistence.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "search",
        "title": "Search",
        "description": "Search the web through the configured self-hosted SearXNG instance.",
        "inputSchema": SEARCH_INPUT_SCHEMA,
    },
    {
        "name": "fetch",
        "title": "Fetch",
        "description": "Fetch a URL and extract clean Markdown with Crawl4AI.",
        "inputSchema": FETCH_INPUT_SCHEMA,
    },
    {
        "name": "search_and_fetch",
        "title": "Search and Fetch",
        "description": "Search the web, then fetch and extract Markdown for the top matching results.",
        "inputSchema": SEARCH_AND_FETCH_INPUT_SCHEMA,
    },
]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str | None = None
    score: float | None = None
    published_date: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class FetchResult:
    url: str
    title: str | None
    markdown: str
    metadata: dict[str, Any]


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "searxng_base_url": SEARXNG_BASE_URL}


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    payload = await request.json()
    if isinstance(payload, list):
        responses = [await _handle_rpc(item) for item in payload if isinstance(item, dict)]
        return JSONResponse(responses)
    if not isinstance(payload, dict):
        return JSONResponse(_error(None, -32600, "Invalid Request"), status_code=400)
    response = await _handle_rpc(payload)
    headers = {}
    if payload.get("method") == "initialize":
        headers["MCP-Session-Id"] = str(uuid4())
    return JSONResponse(response, headers=headers)


async def _handle_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "open-talon-web-search-mcp", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = await _call_tool(params)
        elif method == "notifications/initialized":
            result = {}
        else:
            return _error(rpc_id, -32601, f"Method not found: {method}")
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except Exception as exc:
        return _error(rpc_id, -32000, str(exc))


async def _call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if name == "search":
        payload = await search(arguments)
    elif name == "fetch":
        payload = await fetch(arguments)
    elif name == "search_and_fetch":
        payload = await search_and_fetch(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": False,
    }


async def search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = _required_str(arguments, "query")
    limit = _bounded_int(arguments.get("limit"), default=5, minimum=1, maximum=MAX_SEARCH_LIMIT)
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "safesearch": _bounded_int(arguments.get("safe_search"), default=1, minimum=0, maximum=2),
    }
    for key in ("language", "time_range"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            params[key] = value.strip()
    for key in ("categories", "engines"):
        value = arguments.get(key)
        if isinstance(value, list):
            entries = [str(item).strip() for item in value if str(item).strip()]
            if entries:
                params[key] = ",".join(entries)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False) as client:
        response = await client.get(f"{SEARXNG_BASE_URL}/search", params=params)
        response.raise_for_status()
        data = response.json()
    results = [
        result
        for item in data.get("results", [])
        if isinstance(item, dict)
        for result in [_search_result_from_searxng(item)]
        if result.url
    ]
    trimmed = results[:limit]
    citations = [_citation(index, result.title, result.url) for index, result in enumerate(trimmed, start=1)]
    return {
        "query": query,
        "results": [_search_result_payload(result, index) for index, result in enumerate(trimmed, start=1)],
        "citations": citations,
        "metadata": {
            "source": "searxng",
            "searxng_base_url": SEARXNG_BASE_URL,
            "fetched_at": datetime.now(UTC).isoformat(),
            "result_count": len(trimmed),
            "unresponsive_engines": data.get("unresponsive_engines") or [],
        },
    }


async def fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = _required_url(arguments, "url")
    max_chars = _bounded_int(
        arguments.get("max_chars"),
        default=DEFAULT_MAX_MARKDOWN_CHARS,
        minimum=1000,
        maximum=100000,
    )
    result = await fetch_url(url, max_chars=max_chars)
    payload = {
        "url": result.url,
        "title": result.title,
        "markdown": result.markdown,
        "citations": [_citation(1, result.title or result.url, result.url)],
        "metadata": {
            **result.metadata,
            "query_context": arguments.get("query_context") if isinstance(arguments.get("query_context"), str) else None,
        },
    }
    if arguments.get("persist_asset"):
        payload["asset_candidate"] = _asset_candidate(result)
    return payload


async def search_and_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    search_payload = await search(arguments)
    fetch_limit = _bounded_int(arguments.get("fetch_limit"), default=3, minimum=1, maximum=MAX_FETCH_LIMIT)
    max_chars = _bounded_int(
        arguments.get("max_chars_per_page"),
        default=8000,
        minimum=1000,
        maximum=100000,
    )
    pages: list[dict[str, Any]] = []
    for item in search_payload["results"][:fetch_limit]:
        try:
            page = await fetch_url(item["url"], max_chars=max_chars)
            page_payload: dict[str, Any] = {
                "source_result_index": item["rank"],
                "url": page.url,
                "title": page.title or item["title"],
                "snippet": item["snippet"],
                "markdown": page.markdown,
                "metadata": page.metadata,
            }
            if arguments.get("persist_assets"):
                page_payload["asset_candidate"] = _asset_candidate(page)
            pages.append(page_payload)
        except Exception as exc:
            pages.append(
                {
                    "source_result_index": item["rank"],
                    "url": item["url"],
                    "title": item["title"],
                    "snippet": item["snippet"],
                    "error": str(exc),
                    "metadata": {"crawl_status": "failed"},
                }
            )
    return {
        "query": search_payload["query"],
        "results": search_payload["results"],
        "pages": pages,
        "citations": search_payload["citations"],
        "metadata": {
            **search_payload["metadata"],
            "fetch_limit": fetch_limit,
            "page_count": len(pages),
        },
    }


async def fetch_url(url: str, *, max_chars: int) -> FetchResult:
    try:
        return await _crawl4ai_fetch(url, max_chars=max_chars)
    except Exception as exc:
        fallback = await _http_fallback_fetch(url, max_chars=max_chars)
        return FetchResult(
            url=fallback.url,
            title=fallback.title,
            markdown=fallback.markdown,
            metadata={
                **fallback.metadata,
                "crawl_status": "fallback",
                "crawl4ai_error": str(exc),
            },
        )


async def _crawl4ai_fetch(url: str, *, max_chars: int) -> FetchResult:
    from crawl4ai import AsyncWebCrawler  # type: ignore

    config = None
    try:
        from crawl4ai import CrawlerRunConfig  # type: ignore

        config = CrawlerRunConfig(word_count_threshold=1)
    except Exception:
        config = None
    async with AsyncWebCrawler() as crawler:
        if config is None:
            result = await crawler.arun(url=url)
        else:
            result = await crawler.arun(url=url, config=config)
    success = _result_attr(result, "success")
    if success is False:
        raise ValueError(str(_result_attr(result, "error_message") or "Crawl4AI crawl failed"))
    markdown = _markdown_from_crawl_result(result)
    title = _metadata_title(_result_attr(result, "metadata"))
    metadata = _object_or_empty(_result_attr(result, "metadata"))
    return FetchResult(
        url=str(_result_attr(result, "url") or url),
        title=title,
        markdown=_trim_text(markdown, max_chars),
        metadata={
            "crawl_status": "completed",
            "extractor": "crawl4ai",
            "fetched_at": datetime.now(UTC).isoformat(),
            "metadata": metadata,
        },
    )


async def _http_fallback_fetch(url: str, *, max_chars: int) -> FetchResult:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True, trust_env=False) as client:
        response = await client.get(url, headers={"User-Agent": "OpenTalonWebSearchMCP/0.1"})
        response.raise_for_status()
    parser = _ReadableHtmlParser()
    parser.feed(response.text)
    title = parser.title
    markdown = _trim_text(parser.markdown(), max_chars)
    return FetchResult(
        url=str(response.url),
        title=title,
        markdown=markdown,
        metadata={
            "crawl_status": "completed",
            "extractor": "httpx_html_parser",
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    )


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title or ''} {text}".strip()
        if not self._skip_depth and not self._in_title:
            self._parts.append(text)

    def markdown(self) -> str:
        text = " ".join(self._parts)
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def _search_result_from_searxng(item: dict[str, Any]) -> SearchResult:
    return SearchResult(
        title=str(item.get("title") or item.get("url") or "Untitled"),
        url=str(item.get("url") or ""),
        snippet=str(item.get("content") or item.get("snippet") or ""),
        engine=str(item.get("engine")) if item.get("engine") else None,
        score=float(item["score"]) if isinstance(item.get("score"), (int, float)) else None,
        published_date=str(item.get("publishedDate") or item.get("published_date") or "")
        or None,
        metadata={key: value for key, value in item.items() if key not in {"title", "url", "content", "snippet"}},
    )


def _search_result_payload(result: SearchResult, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "engine": result.engine,
        "score": result.score,
        "published_date": result.published_date,
        "metadata": result.metadata or {},
    }


def _citation(index: int, title: str, url: str) -> dict[str, Any]:
    return {"id": f"web-{index}", "title": title, "url": url}


def _asset_candidate(result: FetchResult) -> dict[str, Any]:
    title = result.title or urlparse(result.url).netloc or "web-page"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-").lower()[:80] or "web-page"
    return {
        "filename": f"{slug}.md",
        "content_type": "text/markdown",
        "content": result.markdown,
        "metadata": {
            "source": "web_search_plugin",
            "source_url": result.url,
            "title": result.title,
            "crawl_metadata": result.metadata,
        },
    }


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _required_url(arguments: dict[str, Any], key: str) -> str:
    value = _required_str(arguments, key)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{key} must be an HTTP or HTTPS URL")
    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[truncated]"


def _result_attr(result: Any, name: str) -> Any:
    if hasattr(result, name):
        return getattr(result, name)
    if isinstance(result, dict):
        return result.get(name)
    return None


def _markdown_from_crawl_result(result: Any) -> str:
    markdown = _result_attr(result, "markdown")
    if isinstance(markdown, str):
        return markdown
    for field in ("fit_markdown", "raw_markdown", "markdown_with_citations"):
        value = _result_attr(markdown, field)
        if isinstance(value, str) and value:
            return value
    for field in ("fit_markdown", "raw_markdown", "markdown_with_citations"):
        value = _result_attr(result, field)
        if isinstance(value, str) and value:
            return value
    return str(markdown or "")


def _metadata_title(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    title = metadata.get("title")
    return title if isinstance(title, str) and title else None


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def main() -> None:
    host = os.getenv("WEB_SEARCH_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_SEARCH_MCP_PORT", "8181"))
    uvicorn.run("web_search_mcp.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
