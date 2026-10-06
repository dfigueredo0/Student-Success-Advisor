"""The output guardrail removes student identifiers from answers and refuses streaming."""

import httpx
import pytest

STUDENT_ID = "A20123456"
STUDENT_EMAIL = "jdoe@hawk.illinoistech.edu"
STAFF_EMAIL = "advising@iit.edu"


def repeat(litellm: httpx.Client, text: str) -> dict[str, str]:
    # qwen3 thinks before answering, so it needs room (max_tokens) to reach the answer.
    resp = litellm.post(
        "/v1/chat/completions",
        json={
            "model": "local-llm",
            "messages": [{"role": "user", "content": f"Repeat exactly, nothing else: {text}"}],
            "max_tokens": 1500,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["choices"][0]["message"]


@pytest.mark.parametrize("secret", [STUDENT_ID, STUDENT_EMAIL])
def test_student_identifiers_are_removed(litellm: httpx.Client, secret: str) -> None:
    message = repeat(litellm, f"The record belongs to {secret}.")
    shown = (message.get("content") or "") + (message.get("reasoning_content") or "")
    assert secret not in shown
    assert "[removed]" in shown


def test_staff_email_is_kept(litellm: httpx.Client) -> None:
    message = repeat(litellm, f"Contact {STAFF_EMAIL} for help.")
    assert STAFF_EMAIL in (message.get("content") or "")


def test_streaming_is_refused(litellm: httpx.Client) -> None:
    resp = litellm.post(
        "/v1/chat/completions",
        json={
            "model": "local-llm",
            "messages": [{"role": "user", "content": "Say hi"}],
            "stream": True,
        },
    )
    assert resp.status_code == 400, resp.text
    assert "output check" in resp.text
