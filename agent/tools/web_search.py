from __future__ import annotations

import os
import re
from typing import List, Dict, Any

import httpx


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


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
        resp = httpx.get(SERPAPI_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"error": f"SerpAPI request failed: {exc}"}

    results = []
    for item in data.get("organic_results", [])[: params["num"]]:
        results.append(
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet") or item.get("rich_snippet") or "",
            }
        )
    return {"results": results}


def fetch_page(url: str, timeout: int = 8) -> str:
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return ""
    return strip_html(html)[:5000]  # cap content length


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
