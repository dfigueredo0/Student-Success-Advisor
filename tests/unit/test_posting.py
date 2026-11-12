"""Job postings: spotting one, fetching a link safely, and comparing it with a student's skills."""

import asyncio
import gzip
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from domain.posting import is_posting, looks_like_posting
from domain.skills import build_vocab
from tools.career import onet, posting

POSTING = (Path(__file__).parents[1] / "fixtures" / "posting" / "synthetic.txt").read_text()
PUBLIC = "93.184.216.34"
HTML = {"content-type": "text/html; charset=utf-8"}
VOCAB = build_vocab(["Python", "Structured query language SQL", "Docker", "Kubernetes"])


def resolver(*addresses: str) -> Callable[..., list[Any]]:
    """Stands in for DNS: every host resolves to `addresses`."""
    return lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses
    ]


def fetch(url: str, handler: Callable[[httpx.Request], httpx.Response], *addresses: str) -> str:
    return posting.fetch_posting(
        url, resolve=resolver(*addresses or (PUBLIC,)), transport=httpx.MockTransport(handler)
    )


def never(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request may be sent, got {request.url}")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (POSTING, True),
        ("What are the qualifications and responsibilities of a data scientist?", False),  # short
        ("I have a question about my degree requirements. " * 12, False),  # long, no posting cues
    ],
)
def test_looks_like_posting(text: str, expected: bool) -> None:
    assert looks_like_posting(text) is expected


def test_a_link_counts_as_a_posting_to_read() -> None:
    assert is_posting("Am I a fit for this? https://jobs.lever.co/acme/123")
    assert is_posting(POSTING) and not is_posting("Can I take CS 450?")


def test_fetch_requests_the_validated_address_and_still_names_the_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers=HTML, text="<h1>Intern</h1><p>Python</p>")

    text = fetch("https://jobs.example.com/p/1?x=2", handler)

    assert "Intern" in text and "Python" in text
    request = seen[0]
    # The connection goes to the address that was checked, so the name cannot resolve to an
    # internal one in between; TLS and the Host header still use the name.
    assert str(request.url) == f"https://{PUBLIC}/p/1?x=2"
    assert request.headers["host"] == "jobs.example.com"
    assert request.extensions["sni_hostname"] == "jobs.example.com"


@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("http://localhost/", ["127.0.0.1"]),
        ("http://intranet.example/", ["10.0.0.5"]),
        ("http://metadata.example/latest/meta-data", ["169.254.169.254"]),
        ("http://cgnat.example/", ["100.64.0.1"]),
        ("http://multicast.example/", ["224.0.0.1"]),
        ("http://mixed.example/", [PUBLIC, "192.168.1.10"]),  # one bad address is enough
        ("http://nowhere.example/", []),
        ("ftp://files.example/posting.txt", [PUBLIC]),
        ("https://user:secret@jobs.example.com/", [PUBLIC]),
        ("https://jobs.example.com:8443/", [PUBLIC]),
        ("http://jobs.example.com:443/", [PUBLIC]),
        ("https:///no-host", [PUBLIC]),
    ],
)
def test_addresses_the_server_must_not_reach_are_refused(url: str, addresses: list[str]) -> None:
    with pytest.raises(posting.FetchFailed):
        posting.fetch_posting(
            url, resolve=resolver(*addresses), transport=httpx.MockTransport(never)
        )


def test_redirect_to_an_internal_address_is_not_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    def resolve(host: str, port: int, **kw: Any) -> list[Any]:
        address = host if host[0].isdigit() else PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    with pytest.raises(posting.FetchFailed):
        posting.fetch_posting(
            "https://jobs.example.com/a", resolve=resolve, transport=httpx.MockTransport(handler)
        )
    assert calls == [f"https://{PUBLIC}/a"]


@pytest.mark.parametrize(("redirects", "ok"), [(3, True), (4, False)])
def test_redirects_are_followed_three_times_at_most(redirects: int, ok: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        if n < redirects:
            return httpx.Response(301, headers={"location": f"/{n + 1}"})  # relative: same host
        return httpx.Response(200, headers=HTML, text="done")

    if ok:
        assert fetch("https://jobs.example.com/0", handler).strip() == "done"
    else:
        with pytest.raises(posting.FetchFailed):
            fetch("https://jobs.example.com/0", handler)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-"),
        httpx.Response(403, headers=HTML, text="Forbidden"),
        httpx.ConnectError("refused"),
    ],
    ids=["not-a-page", "blocked", "unreachable"],
)
def test_pages_that_cannot_be_read_fail_the_fetch(response: httpx.Response | Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    with pytest.raises(posting.FetchFailed):
        fetch("https://jobs.example.com/", handler)


def test_a_huge_page_is_cut_not_read_whole() -> None:
    big = httpx.Response(200, headers={"content-type": "text/plain"}, content=b"a" * 3_000_000)
    assert len(fetch("https://jobs.example.com/", lambda request: big)) <= posting.MAX_BYTES


def test_compressed_pages_are_refused_not_inflated() -> None:
    """A few kilobytes can inflate to gigabytes: the fetch asks for none and takes none."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers["accept-encoding"])
        packed = gzip.compress(b"a" * 5_000_000)
        return httpx.Response(200, headers={**HTML, "content-encoding": "gzip"}, content=packed)

    with pytest.raises(posting.FetchFailed):
        fetch("https://jobs.example.com/", handler)
    assert asked == ["identity"]


def test_a_server_that_stalls_is_cut_off_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deadline covers the whole fetch, the wait for a first byte included."""
    monkeypatch.setattr(posting, "DEADLINE", 0.2)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, headers=HTML, text="too late")

    start = time.monotonic()
    with pytest.raises(posting.FetchFailed):
        fetch("https://jobs.example.com/", handler)  # type: ignore[arg-type]
    assert time.monotonic() - start < 2


def test_only_the_start_of_a_huge_page_is_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    courses = Courses(monkeypatch)
    top = "About the role: write Python. Responsibilities: ship features. Qualifications: any. " * 4
    page = top + "filler " * 60_000 + "Docker and Kubernetes"  # the cap falls inside the filler
    monkeypatch.setattr(posting, "fetch_posting", lambda url: page)
    r = posting.compare_to_posting("https://jobs.example.com/1", ["Python"])
    assert (r["matched"], r["missing"], courses.calls) == (["Python"], [], [])


def test_html_text_keeps_what_a_reader_sees_and_the_embedded_job_data() -> None:
    html = (
        "<html><head><style>p{color:red}</style>"
        '<script type="application/ld+json">{"@type": "JobPosting", "title": "Data Intern", '
        '"description": "\\u003cp\\u003eUse \\u003cb\\u003eTableau\\u003c/b\\u003e daily"}</script>'
        "</head><body><ul><li>Python</li><li>SQL</li></ul><script>track('x')</script></body></html>"
    )
    text = " ".join(posting.html_text(html).split())
    assert "Data Intern" in text and "Use Tableau daily" in text
    assert "Python SQL" in text  # list items do not run together
    assert "track" not in text and "color" not in text and "<" not in text


class Courses:
    """Stands in for find_courses_for_skills; records what it was asked to find."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.result = {"gap": ["Docker"], "matches": [], "citations": [{"source": "IIT Banner"}]}
        monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)
        monkeypatch.setattr(posting, "find_courses_for_skills", self)

    def __call__(self, *args: Any) -> dict[str, Any]:
        self.calls.append(args)
        return self.result


def test_pasted_posting_is_split_into_skills_held_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    courses = Courses(monkeypatch)
    r = posting.compare_to_posting(POSTING, ["python", "SQL", "juggling"])
    assert (r["reason"], r["matched"], r["missing"]) == (
        None,
        ["Python", "SQL"],
        ["Docker", "Kubernetes"],
    )
    assert courses.calls == [("this posting", [], ["Docker", "Kubernetes"])]
    assert r["courses"] == courses.result and r["citations"] == courses.result["citations"]


def test_link_is_fetched_and_cited(monkeypatch: pytest.MonkeyPatch) -> None:
    courses = Courses(monkeypatch)
    monkeypatch.setattr(posting, "fetch_posting", lambda url: POSTING)
    url = "https://jobs.lever.co/acme/123"
    r = posting.compare_to_posting(f"Am I a fit? {url}", ["Python", "SQL", "Docker", "Kubernetes"])
    assert (r["matched"], r["missing"]) == (["Python", "SQL", "Docker", "Kubernetes"], [])
    assert r["courses"] is None and courses.calls == []  # nothing to learn, nothing to look up
    assert r["citations"] == [{"source": "The job posting you shared", "url": url}]


@pytest.mark.parametrize(
    ("page", "reason"),
    [
        ("Sign in to continue. Forgot your password?", "not_a_posting"),  # login wall, JS shell
        (posting.FetchFailed("blocked"), "unreadable"),
    ],
)
def test_link_that_gives_no_posting_says_why(
    monkeypatch: pytest.MonkeyPatch, page: str | Exception, reason: str
) -> None:
    courses = Courses(monkeypatch)

    def fetch_posting(url: str) -> str:
        if isinstance(page, Exception):
            raise page
        return page

    monkeypatch.setattr(posting, "fetch_posting", fetch_posting)
    r = posting.compare_to_posting("https://www.linkedin.com/jobs/view/1", ["Python"])
    assert r["reason"] == reason and courses.calls == []


def test_posting_without_known_skills_and_missing_job_data(monkeypatch: pytest.MonkeyPatch) -> None:
    Courses(monkeypatch)
    plain = "Responsibilities: greet visitors. Qualifications: a friendly manner. " * 5
    assert posting.compare_to_posting(plain, ["Python"])["reason"] == "no_skills_in_posting"

    def not_loaded() -> None:
        raise onet.OnetNotLoaded

    monkeypatch.setattr(onet, "vocabulary", not_loaded)
    assert posting.compare_to_posting(POSTING, ["Python"])["reason"] == "no_onet"
