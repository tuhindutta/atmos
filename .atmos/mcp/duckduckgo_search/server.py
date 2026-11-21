"""MCP server for free web searches using DuckDuckGo's HTML results page."""

from __future__ import annotations

from html.parser import HTMLParser
import os
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from typing import Any

from fastmcp import FastMCP

SEARCH_URL = "https://lite.duckduckgo.com/lite/"
DEFAULT_TIMEOUT_SECONDS = 20

mcp = FastMCP(
    name="DuckDuckGo Search",
    instructions=(
        "Search the web using DuckDuckGo and return ordinary search results. "
        "No API key is required; this tool does not generate AI summaries."
    ),
)


class _ResultsParser(HTMLParser):
    """Extract result titles, target URLs, and snippets from DuckDuckGo HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._title_result: dict[str, str] | None = None
        self._title_parts: list[str] = []
        self._snippet_result: dict[str, str] | None = None
        self._snippet_parts: list[str] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        return set(dict(attrs).get("class", "").split())

    @staticmethod
    def _target_url(href: str) -> str:
        parsed = urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                href = target
        parsed = urlparse(href)
        return href if parsed.scheme in {"http", "https"} and parsed.netloc else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = self._classes(attrs)
        if tag == "a" and classes.intersection({"result__a", "result-link"}):
            href = self._target_url(attributes.get("href", ""))
            if href:
                self._title_result = {"title": "", "url": href, "snippet": ""}
                self._title_parts = []
        if classes.intersection({"result__snippet", "result-snippet"}):
            self._snippet_result = self.results[-1] if self.results else None
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_result is not None:
            self._title_parts.append(data)
        if self._snippet_result is not None:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._title_result is not None:
            self._title_result["title"] = " ".join("".join(self._title_parts).split())
            if self._title_result["title"]:
                self.results.append(self._title_result)
            self._title_result = None
            self._title_parts = []
        if self._snippet_result is not None and tag in {"a", "div", "td"}:
            snippet = " ".join("".join(self._snippet_parts).split())
            if snippet:
                self._snippet_result["snippet"] = snippet
            self._snippet_result = None
            self._snippet_parts = []


def _extract_results(document: str, limit: int) -> list[dict[str, str]]:
    parser = _ResultsParser()
    parser.feed(document)
    parser.close()
    return parser.results[:limit]


@mcp.tool

def duckduckgo_search(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search DuckDuckGo and return result titles, URLs, and snippets.

    Args:
        query: A question or topic to search for.
        num_results: Maximum number of results to return (1-10).
    """
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > 4000:
        raise ValueError("query must be 4000 characters or fewer")
    if not isinstance(num_results, int) or isinstance(num_results, bool) or not 1 <= num_results <= 10:
        raise ValueError("num_results must be an integer from 1 to 10")

    request = Request(
        f"{SEARCH_URL}?{urlencode({'q': query})}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (compatible; Atmos-DuckDuckGo-Search/1.0)",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            document = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"DuckDuckGo search failed (HTTP {exc.code}).") from None
    except (URLError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else "request timed out"
        raise RuntimeError(f"Could not reach DuckDuckGo: {reason}") from None

    return {
        "query": query,
        "results": _extract_results(document, num_results),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8083"))
    mcp.run(transport="http", host="127.0.0.1", port=port)
