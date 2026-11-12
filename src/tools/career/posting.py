"""compare_to_posting: one job posting, given as a link or as text, against a student's skills.

The posting is read the way a resume is: skills are matched against the O*NET vocabulary, so
the result holds vocabulary names only and none of the posting's own text. No model sees it.

fetch_posting requests an address the student typed, so it is written to be safe to aim at
anything: see the rules on it.
"""

import asyncio
import ipaddress
import json
import socket
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from domain.posting import URL, looks_like_posting
from domain.resume import scrub
from domain.skills import MAX_SCAN, canonical, extract_skills
from tools.career import onet
from tools.career.skill_courses import find_courses_for_skills

MAX_BYTES = 2_000_000  # of the page; the rest of a larger page is not read
MAX_REDIRECTS = 3
DEADLINE = 15.0  # seconds for the whole fetch, redirects included
_PORTS = {"http": 80, "https": 443}
_TEXT_TYPES = ("text/html", "text/plain")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; job-posting-reader)",
    "Accept": "text/html",
    "Accept-Encoding": "identity",
}


class FetchFailed(Exception):
    """The link was refused or could not be read; the reason is for logs, not the student."""


def _pin(url: str, resolve: Callable[..., list[Any]]) -> tuple[str, str]:
    """(`url` with its host replaced by an address checked to be public, the host name)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchFailed("not a URL") from exc
    host = parts.hostname
    if parts.scheme not in _PORTS or not host or parts.username or parts.password:
        raise FetchFailed("only plain http(s) links")
    if port not in (None, _PORTS[parts.scheme]):
        raise FetchFailed("only the standard port")
    try:
        # shortcut: IPv4 only, so a host with only IPv6 addresses cannot be read; add AF_INET6
        # with the same is_global check if students hit one.
        found = resolve(host, _PORTS[parts.scheme], family=socket.AF_INET, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchFailed("host does not resolve") from exc
    addresses = sorted({info[4][0] for info in found})
    # Every address must be public: loopback, private ranges, link-local (cloud metadata),
    # carrier NAT and multicast are all "not global". One internal address refuses the host.
    if not addresses or not all(_public(a) for a in addresses):
        raise FetchFailed("host is not a public address")
    pinned = urlunsplit((parts.scheme, addresses[0], parts.path or "/", parts.query, ""))
    return pinned, host


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


def fetch_posting(
    url: str,
    *,
    resolve: Callable[..., list[Any]] = socket.getaddrinfo,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """The readable text of the page at `url`, or FetchFailed.

    Rules, each because the address comes from a student:
    - http(s) on its standard port, no user:password, and every address the name resolves to
      must be public;
    - the request goes to that checked address (Host header and TLS still use the name), so
      the name cannot resolve to an internal address between the check and the connection;
    - redirects are followed by hand, at most MAX_REDIRECTS, each target checked the same way;
    - only uncompressed text/html and text/plain, at most MAX_BYTES; proxies from the
      environment are not used;
    - DEADLINE covers all of it: the name lookup, every redirect, and a server that sends one
      byte at a time (httpx's own timeouts are per read, so they do not).
    """
    try:
        return asyncio.run(asyncio.wait_for(_fetch(url, resolve, transport), DEADLINE))
    except TimeoutError as exc:
        raise FetchFailed("took too long") from exc
    except httpx.HTTPError as exc:
        raise FetchFailed(type(exc).__name__) from exc


async def _fetch(
    url: str, resolve: Callable[..., list[Any]], transport: httpx.AsyncBaseTransport | None
) -> str:
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=timeout) as client:
        for _ in range(MAX_REDIRECTS + 1):
            pinned, host = await asyncio.to_thread(_pin, url, resolve)  # the lookup blocks
            request = client.build_request(
                "GET", pinned, headers={**_HEADERS, "Host": host}, extensions={"sni_hostname": host}
            )
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                # Compressed bodies are refused, not inflated: a few kilobytes can expand past
                # any cap before the cap is checked.
                packed = response.headers.get("content-encoding", "identity").lower() != "identity"
                if response.status_code != 200 or kind not in _TEXT_TYPES or packed:
                    raise FetchFailed(f"status {response.status_code}, type {kind!r}")
                body = bytearray()
                async for chunk in response.aiter_bytes(65536):  # as sent: nothing to inflate
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                text = bytes(body[:MAX_BYTES]).decode(response.encoding or "utf-8", "replace")
                return html_text(text) if kind == "text/html" else text
            finally:
                await response.aclose()
    raise FetchFailed("too many redirects")


class _Text(HTMLParser):
    """Text a reader sees, plus the job data pages embed for search engines (JSON-LD), which
    is often the only copy of the posting in the HTML of a script-rendered page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden: str | None = None  # "skip" inside script/style, "ld" inside JSON-LD

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(" ")  # tags separate words: "<li>Python</li><li>SQL</li>"
        if tag in ("script", "style", "noscript", "template"):
            ld = (
                tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json"
            )
            self._hidden = "ld" if ld else "skip"

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(" ")
        if tag in ("script", "style", "noscript", "template"):
            self._hidden = None

    def handle_data(self, data: str) -> None:
        if self._hidden == "ld":
            try:
                embedded = " ".join(_strings(json.loads(data)))
            except ValueError:
                return
            self.parts.append(html_text(embedded))  # its description is HTML again
        elif self._hidden is None:
            self.parts.append(data)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def html_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def compare_to_posting(posting: str, current_skills: list[str]) -> dict[str, Any]:
    """Which of the posting's software and tool skills the student has, and which not.

    `posting` is the student's message: a link (fetched) or the posting's text. `reason` says
    why there is no comparison: "no_onet", "unreadable" (the link could not be fetched),
    "not_a_posting" (the page holds no posting: a login wall or a script-rendered page) or
    "no_skills_in_posting". `courses` is find_courses_for_skills' result for the missing ones.
    """
    result: dict[str, Any] = {
        "reason": None,
        "matched": [],
        "missing": [],
        "courses": None,
        "citations": [],
    }
    try:
        vocab = onet.vocabulary()
    except onet.OnetNotLoaded:
        return result | {"reason": "no_onet"}
    link = None if looks_like_posting(posting) else URL.search(posting)
    if link:
        try:
            text = fetch_posting(link.group(0))[:MAX_SCAN]  # a posting sits at the top of a page
        except FetchFailed:
            return result | {"reason": "unreadable"}
        if not looks_like_posting(text):
            return result | {"reason": "not_a_posting"}
    else:
        text = posting
    wanted = extract_skills(scrub(text), vocab)
    if not wanted:
        return result | {"reason": "no_skills_in_posting"}
    have = {vocab.short[name] for name in canonical(current_skills, vocab)[0]}
    result["matched"] = [s for s in wanted if s in have]
    result["missing"] = [s for s in wanted if s not in have]
    if result["missing"]:
        result["courses"] = find_courses_for_skills("this posting", [], result["missing"])
        result["citations"] = list(result["courses"]["citations"])
    if link:
        result["citations"].append({"source": "The job posting you shared", "url": link.group(0)})
    return result
