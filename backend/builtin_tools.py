"""
Built-in tools — always available to every agent, no configuration required.

Currently provides:
  - web_search   : DuckDuckGo HTML search (no API key)
  - fetch_url    : HTTP GET/POST with response text extraction
"""

import asyncio
import json
import re
import urllib.parse
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

BUILTIN_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. Returns a list of results with "
                "titles, snippets, and URLs. Use this when you need up-to-date facts, "
                "news, documentation, or any information not in your training data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 8, max 20).",
                        "default": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch the content of any URL and return the page text. Useful for reading "
                "articles, documentation, GitHub files, or any public web page. "
                "Automatically strips HTML tags and extracts readable text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Truncate response to this many characters (default 8000).",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
        },
    },
]

BUILTIN_TOOL_NAMES = {s["function"]["name"] for s in BUILTIN_TOOL_SCHEMAS}


def is_builtin_tool(tool_name: str) -> bool:
    return tool_name in BUILTIN_TOOL_NAMES


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract visible text."""

    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = " ".join(parser.parts)
    # Collapse excessive whitespace
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# web_search — DuckDuckGo HTML (no API key)
# ---------------------------------------------------------------------------

def _parse_ddg_results(html: str, max_results: int) -> list[dict]:
    """Parse DuckDuckGo HTML search results page."""
    results = []

    # Each result block: <div class="result__body"> ... </div>
    # Title: <a class="result__a" href="...">...</a>
    # Snippet: <a class="result__snippet">...</a>
    title_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    titles = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title_html) in enumerate(titles[:max_results]):
        title = _strip_html(f"<span>{title_html}</span>") or "No title"
        snippet = _strip_html(f"<span>{snippets[i]}</span>") if i < len(snippets) else ""
        # DDG wraps URLs — decode them
        if url.startswith("//duckduckgo.com/l/?"):
            m = re.search(r"uddg=([^&]+)", url)
            if m:
                url = urllib.parse.unquote(m.group(1))
        results.append({"title": title, "snippet": snippet, "url": url})

    return results


async def _web_search(query: str, max_results: int = 8) -> str:
    max_results = min(max(1, max_results), 20)

    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    params = {"q": query, "kl": "us-en"}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15.0, headers=headers
        ) as client:
            resp = await client.get("https://html.duckduckgo.com/html/", params=params)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return json.dumps({"error": f"Search request failed: {e}"})

    results = _parse_ddg_results(html, max_results)

    if not results:
        # Fallback: try DuckDuckGo Instant Answer API
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                ia_resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers=headers,
                )
                data = ia_resp.json()
            ia_results = []
            if data.get("AbstractText"):
                ia_results.append({
                    "title": data.get("Heading", query),
                    "snippet": data["AbstractText"],
                    "url": data.get("AbstractURL", ""),
                })
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    ia_results.append({
                        "title": topic["Text"][:80],
                        "snippet": topic["Text"],
                        "url": topic.get("FirstURL", ""),
                    })
                    if len(ia_results) >= max_results:
                        break
            if data.get("Answer") and not ia_results:
                ia_results.append({"title": "Answer", "snippet": str(data["Answer"]), "url": ""})
            results = ia_results
        except Exception:
            pass

    if not results:
        return json.dumps({
            "query": query,
            "results": [],
            "note": "No results found. Try a different query.",
        })

    return json.dumps({"query": query, "results": results})


# ---------------------------------------------------------------------------
# fetch_url
# ---------------------------------------------------------------------------

async def _fetch_url(url: str, max_chars: int = 8000) -> str:
    max_chars = min(max(500, max_chars), 50000)

    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20.0, headers=headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            raw = resp.text
    except Exception as e:
        return json.dumps({"error": f"Fetch failed: {e}", "url": url})

    # Extract readable text from HTML; pass JSON/plain text through
    if "html" in content_type:
        text = _strip_html(raw)
    elif "json" in content_type:
        try:
            text = json.dumps(json.loads(raw), indent=2)
        except Exception:
            text = raw
    else:
        text = raw

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated — {len(text) - max_chars} more characters]"

    return json.dumps({"url": url, "content": text})


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def execute_builtin_tool(tool_name: str, arguments_str: str) -> str:
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "web_search":
        query = args.get("query", "").strip()
        if not query:
            return json.dumps({"error": "query is required"})
        max_results = int(args.get("max_results", 8))
        return await _web_search(query, max_results)

    if tool_name == "fetch_url":
        url = args.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required"})
        max_chars = int(args.get("max_chars", 8000))
        return await _fetch_url(url, max_chars)

    return json.dumps({"error": f"Unknown builtin tool: {tool_name}"})
