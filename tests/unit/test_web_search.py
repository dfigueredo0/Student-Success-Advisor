"""search_openings: one web search for current openings; third-party results cleaned and cited."""

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tools.career import web_search

Handler = Callable[[httpx.Request], httpx.Response]


def result(n: int = 1, **changes: Any) -> dict[str, Any]:
    return {
        "title": f"Software Engineering Intern {n} - Acme",
        "url": f"https://boards.greenhouse.io/acme/jobs/{n}",
        "content": "Join our platform team for summer 2027.",
        "score": 0.9,
    } | changes


def found(*results: dict[str, Any]) -> Handler:
    return lambda request: httpx.Response(200, json={"results": list(results)})


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(tavily_api_key=SecretStr("tvly-test"))
    monkeypatch.setattr(web_search, "get_settings", lambda: settings)


def search(handler: Handler, role: str = "Software Developers", year: int | None = 2099) -> Any:
    return web_search.search_openings(role, year, transport=httpx.MockTransport(handler))


@pytest.mark.usefixtures("key")
def test_one_search_for_the_role_at_the_students_level_in_the_past_month() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return found(result())(request)

    r = search(handler)

    assert len(seen) == 1 and str(seen[0].url) == "https://api.tavily.com/search"
    assert seen[0].headers["authorization"] == "Bearer tvly-test"
    assert json.loads(seen[0].content) == {
        "query": "Software Developers internship job openings",
        "max_results": 5,
        "time_range": "month",
        "search_depth": "basic",
    }
    assert r["reason"] is None and r["query"] == "Software Developers internship job openings"
    assert r["results"] == [
        {
            "title": "Software Engineering Intern 1 - Acme",
            "site": "boards.greenhouse.io",
            "snippet": "Join our platform team for summer 2027.",
        }
    ]
    assert r["citations"] == [
        {
            "source": "Software Engineering Intern 1 - Acme (boards.greenhouse.io)",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "quote": "Join our platform team for summer 2027.",
        }
    ]


@pytest.mark.usefixtures("key")
@pytest.mark.parametrize(
    ("year", "level"), [(2000, "entry level"), (None, "internship or entry level")]
)
def test_level_follows_the_graduation_year(year: int | None, level: str) -> None:
    assert (
        search(found(result()), "data analyst", year)["query"]
        == f"data analyst {level} job openings"
    )


@pytest.mark.usefixtures("key")
def test_results_are_third_party_text_and_are_cleaned() -> None:
    r = search(
        found(
            result(1, url="javascript:alert(1)"),  # only http(s) links are kept
            result(2, url="ftp://files.example/job"),
            result(3, title=""),  # nothing to show
            result(4, url=None),
            result(5, title="T" * 300, content="line one\nline\ttwo \x00\x1b[31m " + "s " * 300),
            result(6),
            result(6),  # the same page twice
            "not a result",
        )
    )
    assert [x["title"][:3] for x in r["results"]] == ["TTT", "Sof"]
    long = r["results"][0]
    assert len(long["title"]) <= 123 and len(long["snippet"]) <= 203
    assert long["snippet"].startswith("line one line two [31m s s")  # one line, no control bytes
    assert [c["url"] for c in r["citations"]] == [
        "https://boards.greenhouse.io/acme/jobs/5",
        "https://boards.greenhouse.io/acme/jobs/6",
    ]


@pytest.mark.usefixtures("key")
def test_links_inside_a_result_are_removed_so_only_its_source_can_be_followed() -> None:
    """The page turns addresses in an answer into links; a result must not plant its own."""
    r = search(
        found(
            result(
                title="Apply at https://evil.example/login now",
                content="Send your details to http://phish.example/form today.",
            )
        )
    )
    shown = r["results"][0]
    assert (shown["title"], shown["snippet"]) == ("Apply at now", "Send your details to today.")
    assert "http" not in r["citations"][0]["source"] + r["citations"][0]["quote"]
    assert r["citations"][0]["url"] == "https://boards.greenhouse.io/acme/jobs/1"  # the source


@pytest.mark.usefixtures("key")
def test_at_most_five_results() -> None:
    assert len(search(found(*(result(n) for n in range(9))))["results"]) == 5


@pytest.mark.usefixtures("key")
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, json={"detail": "slow down"}),
        httpx.Response(432, json={"detail": "plan limit exceeded"}),
        httpx.Response(500),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"answer": "no results key"}),
        httpx.Response(200, json={"results": "not a list"}),
        httpx.ConnectTimeout("timed out"),
    ],
    ids=["rate-limit", "quota", "server-error", "not-json", "no-results-key", "bad-shape", "down"],
)
def test_a_failed_search_is_reported_not_raised(response: httpx.Response | Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    r = search(handler)
    assert (r["reason"], r["results"], r["citations"]) == ("search_failed", [], [])


@pytest.mark.usefixtures("key")
def test_nothing_found() -> None:
    assert search(found())["reason"] == "no_results"


@pytest.mark.parametrize("configured", [None, SecretStr("")])
def test_without_a_key_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch, configured: SecretStr | None
) -> None:
    settings = SimpleNamespace(tavily_api_key=configured)
    monkeypatch.setattr(web_search, "get_settings", lambda: settings)

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent without a key")

    assert search(never)["reason"] == "not_configured"
