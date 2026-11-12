"""search_openings: one web search for current openings in a role.

O*NET says which roles fit a student; it holds no openings. This asks a search API (Tavily)
for pages from the past month. The results are other people's text: each is cut to a title,
a site and a short snippet, only http(s) links are kept, and every one comes back with its
source link. No model reads them. The query holds the role and the student's level only.

shortcut: no rate limit here, and the free plan is 1,000 searches a month; add a per-student
limit before the API is reachable from outside this machine.
"""

from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

from domain.posting import URL
from domain.web_results import clean, is_http_url
from settings import get_settings

SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 5
MAX_TITLE, MAX_SNIPPET, MAX_SITE, MAX_URL = 120, 200, 80, 500


def search_openings(
    role: str,
    graduation_year: int | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """`reason` says why `results` is empty: "not_configured" (no TAVILY_API_KEY),
    "search_failed" (the service refused or was unreachable, quota included) or "no_results"."""
    if graduation_year is None:
        level = "internship or entry level"
    else:
        level = "entry level" if graduation_year < date.today().year else "internship"
    query = f"{role} {level} job openings"
    result: dict[str, Any] = {
        "reason": None,
        "query": query,
        "searched_on": date.today().isoformat(),
        "results": [],
        "citations": [],
    }
    key = get_settings().tavily_api_key
    if key is None or not key.get_secret_value():
        return result | {"reason": "not_configured"}
    body = {
        "query": query,
        "max_results": MAX_RESULTS,
        "time_range": "month",
        "search_depth": "basic",
    }
    try:
        with httpx.Client(transport=transport, timeout=15.0) as client:
            response = client.post(
                SEARCH_URL,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json=body,
            )
            response.raise_for_status()
            found = response.json()["results"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return result | {"reason": "search_failed"}
    if not isinstance(found, list):
        return result | {"reason": "search_failed"}

    seen: set[str] = set()
    for item in found:
        if not isinstance(item, dict) or len(result["results"]) == MAX_RESULTS:
            continue
        url = item.get("url")
        # Addresses inside a title or snippet are dropped: the page turns addresses into
        # links, and the only link a result may carry is its own source.
        title = clean(URL.sub("", str(item.get("title") or "")), MAX_TITLE)
        if not (isinstance(url, str) and len(url) <= MAX_URL and is_http_url(url)):
            continue
        if not title or url in seen:
            continue
        seen.add(url)
        site = clean((urlsplit(url).hostname or "").removeprefix("www."), MAX_SITE)
        snippet = clean(URL.sub("", str(item.get("content") or "")), MAX_SNIPPET)
        result["results"].append({"title": title, "site": site, "snippet": snippet})
        result["citations"].append({"source": f"{title} ({site})", "url": url, "quote": snippet})
    return result if result["results"] else result | {"reason": "no_results"}
