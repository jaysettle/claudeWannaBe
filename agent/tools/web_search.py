from __future__ import annotations

import os
import re
import logging
from typing import List, Dict, Any

import httpx


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
logger = logging.getLogger(__name__)


def serpapi_search(query: str, num: int = 5, site: str | None = None) -> Dict[str, Any]:
    api_key = os.getenv("JAY_SERPAPI_KEY")
    if not api_key:
        return {"error": "Missing JAY_SERPAPI_KEY environment variable."}
    q = query
    if site:
        q = f"site:{site} {query}"
    params = {
        "engine": "google",
        "q": q,
        "num": max(1, min(num, 10)),
        "api_key": api_key,
    }
    try:
        logger.info("serpapi_search: q=%s num=%s site=%s", q, params["num"], site)
        resp = httpx.get(SERPAPI_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("serpapi_search failed: %s", exc)
        return {"error": f"SerpAPI request failed: {exc}"}

    results = []
    organic = data.get("organic_results", [])
    logger.info("serpapi_search: got %d organic results", len(organic))
    for item in organic[: params["num"]]:
        results.append(
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet") or item.get("rich_snippet") or "",
            }
        )
    return {"results": results}


def fetch_page(url: str, timeout: int = 8, max_bytes: int = 1_000_000) -> str:
    try:
        logger.info("fetch_page: %s", url)
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                logger.info("fetch_page skip %s: content-length %s > max_bytes %s", url, content_length, max_bytes)
                return ""
            ctype = resp.headers.get("Content-Type", "").lower()
            if "pdf" in ctype and content_length and int(content_length) > max_bytes:
                logger.info("fetch_page skip %s: pdf exceeds max_bytes %s", url, max_bytes)
                return ""
            chunks = []
            total = 0
            for chunk in resp.iter_bytes():
                if chunk:
                    total += len(chunk)
                    if total > max_bytes:
                        logger.info("fetch_page skip %s: exceeded max_bytes %s", url, max_bytes)
                        return ""
                    chunks.append(chunk)
            html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="ignore")
    except KeyboardInterrupt:
        return ""
    except Exception:
        logger.warning("fetch_page failed for %s", url)
        return ""
    return strip_html(html)[:5000]  # cap content length for summary


def strip_html(html: str) -> str:
    # Very simple tag stripper
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


def overlap_score(text: str, query: str) -> float:
    if not text:
        return 0.0
    words = set(w.lower() for w in re.findall(r"\\w+", query) if w)
    if not words:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for w in words if w in text_lower)
    return hits / len(words)


def summarize(text: str, max_len: int = 400) -> str:
    if not text:
        return ""
    return text[:max_len].strip()
