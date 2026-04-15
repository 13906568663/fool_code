"""Web tools — WebFetch and WebSearch."""

from __future__ import annotations

import html
import os
import re
import time
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

import httpx

_TIMEOUT = 20
_USER_AGENT = "fool-code-tools/0.1"


def web_fetch(args: dict[str, Any]) -> str:
    url = args.get("url", "")
    prompt = args.get("prompt", "")
    if not url:
        raise ValueError("url is required")
    if not prompt:
        raise ValueError("prompt is required")

    started = time.monotonic()
    request_url = _normalize_fetch_url(url)

    client = httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        resp = client.get(request_url)
        code = resp.status_code
        content_type = resp.headers.get("content-type", "")
        body = resp.text
        final_url = str(resp.url)
    finally:
        client.close()

    normalized = _normalize_fetched_content(body, content_type)
    result = _summarize_web_fetch(final_url, prompt, normalized, body, content_type)
    duration_ms = int((time.monotonic() - started) * 1000)

    import json
    return json.dumps({
        "url": final_url,
        "code": code,
        "bytes": len(body),
        "duration_ms": duration_ms,
        "result": result,
    }, ensure_ascii=False, indent=2)


def web_search(args: dict[str, Any]) -> str:
    query = args.get("query", "")
    if not query or len(query) < 2:
        raise ValueError("query is required (min 2 characters)")

    allowed_domains = args.get("allowed_domains")
    blocked_domains = args.get("blocked_domains")

    started = time.monotonic()
    client = httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        hits = _do_search(client, query)
    finally:
        client.close()

    if allowed_domains:
        hits = [h for h in hits if _host_matches_list(h["url"], allowed_domains)]
    if blocked_domains:
        hits = [h for h in hits if not _host_matches_list(h["url"], blocked_domains)]

    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for h in hits:
        if h["url"] not in seen_urls:
            seen_urls.add(h["url"])
            deduped.append(h)
    hits = deduped[:8]

    if not hits:
        summary = f'No web search results matched the query "{query}".'
    else:
        rendered = "\n".join(f"- [{h['title']}]({h['url']})" for h in hits)
        summary = f'Search results for "{query}". Include a Sources section in the final answer.\n{rendered}'

    import json
    return json.dumps({
        "query": query,
        "results": [summary],
        "duration_seconds": round(time.monotonic() - started, 2),
    }, ensure_ascii=False, indent=2)


def _do_search(client: httpx.Client, query: str) -> list[dict]:
    base_url = os.environ.get("FOOL_CODE_WEB_SEARCH_BASE_URL")
    if base_url:
        url = f"{base_url}?q={query}"
    else:
        url = f"https://html.duckduckgo.com/html/?q={query}"

    try:
        resp = client.get(url)
        html_text = resp.text
    except Exception as primary_err:
        if base_url:
            raise
        try:
            resp = client.get(f"https://www.bing.com/search?q={query}")
            html_text = resp.text
        except Exception as fallback_err:
            raise RuntimeError(f"{primary_err}; fallback also failed: {fallback_err}")

    hits = _extract_ddg_hits(html_text)
    if not hits:
        hits = _extract_bing_hits(html_text)
    if not hits:
        hits = _extract_generic_links(html_text)
    return hits


def _extract_ddg_hits(text: str) -> list[dict]:
    hits: list[dict] = []
    pattern = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(text):
        raw_url = m.group(1)
        title = _html_to_text(m.group(2)).strip()
        decoded = _decode_ddg_redirect(raw_url)
        if decoded and title:
            hits.append({"title": title, "url": decoded})
    return hits


def _extract_bing_hits(text: str) -> list[dict]:
    hits: list[dict] = []
    pattern = re.compile(r'class="b_algo".*?<a\s+href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(text):
        raw_url = m.group(1)
        title = _html_to_text(m.group(2)).strip()
        if title and (raw_url.startswith("http://") or raw_url.startswith("https://")):
            hits.append({"title": title, "url": _decode_html_entities(raw_url)})
    return hits


def _extract_generic_links(text: str) -> list[dict]:
    hits: list[dict] = []
    pattern = re.compile(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(text):
        raw_url = m.group(1)
        title = _html_to_text(m.group(2)).strip()
        if not title:
            continue
        decoded = _decode_ddg_redirect(raw_url) or raw_url
        if decoded.startswith("http://") or decoded.startswith("https://"):
            hits.append({"title": title, "url": decoded})
    return hits


def _decode_ddg_redirect(url: str) -> str | None:
    if url.startswith("http://") or url.startswith("https://"):
        return _decode_html_entities(url)
    if url.startswith("//"):
        joined = f"https:{url}"
    elif url.startswith("/"):
        joined = f"https://duckduckgo.com{url}"
    else:
        return None
    parsed = urlparse(joined)
    if parsed.path in ("/l/", "/l"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg:
            return _decode_html_entities(unquote(uddg[0]))
    return joined


def _normalize_fetch_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "http":
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1"):
            return url.replace("http://", "https://", 1)
    return url


def _normalize_fetched_content(body: str, content_type: str) -> str:
    if "html" in content_type:
        return _html_to_text(body)
    return body.strip()


def _summarize_web_fetch(url: str, prompt: str, content: str, raw_body: str, content_type: str) -> str:
    compact = _collapse_whitespace(content)
    lower_prompt = prompt.lower()

    if "title" in lower_prompt:
        title = _extract_title(content, raw_body, content_type)
        detail = f"Title: {title}" if title else _preview_text(compact, 600)
    elif "summary" in lower_prompt or "summarize" in lower_prompt:
        detail = _preview_text(compact, 900)
    else:
        preview = _preview_text(compact, 900)
        detail = f"Prompt: {prompt}\nContent preview:\n{preview}"

    return f"Fetched {url}\n{detail}"


def _extract_title(content: str, raw_body: str, content_type: str) -> str | None:
    if "html" in content_type:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_body, re.IGNORECASE | re.DOTALL)
        if m:
            title = _collapse_whitespace(_decode_html_entities(m.group(1)))
            if title:
                return title
    for line in content.splitlines():
        t = line.strip()
        if t:
            return t
    return None


def _html_to_text(h: str) -> str:
    text = re.sub(r"<[^>]+>", " ", h)
    return _collapse_whitespace(_decode_html_entities(text))


def _decode_html_entities(s: str) -> str:
    return html.unescape(s)


def _collapse_whitespace(s: str) -> str:
    return " ".join(s.split())


def _preview_text(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\u2026"


def _host_matches_list(url: str, domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for d in domains:
        normalized = _normalize_domain(d)
        if normalized and (host == normalized or host.endswith(f".{normalized}")):
            return True
    return False


def _normalize_domain(domain: str) -> str:
    trimmed = domain.strip()
    try:
        parsed = urlparse(trimmed)
        if parsed.hostname:
            return parsed.hostname.lower().strip(".").rstrip("/")
    except Exception:
        pass
    return trimmed.strip(".").rstrip("/").lower()
