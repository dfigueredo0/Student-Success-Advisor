"""Security checks for the LiteLLM gateway: only requests with a valid key get through."""

import httpx

from settings import Settings

# A tiny chat request, the same one as the curl "Say hi" test.
CHAT = {"model": "local-llm", "messages": [{"role": "user", "content": "Say hi"}]}


def test_gateway_accepts_the_master_key(litellm: httpx.Client) -> None:
    # Control: proves a 401 below is caused by the key, not by a broken request.
    resp = litellm.post("/v1/chat/completions", json=CHAT)
    assert resp.status_code == 200, resp.text


def test_gateway_rejects_a_wrong_key(settings: Settings) -> None:
    resp = httpx.post(
        f"{settings.litellm_base_url}/v1/chat/completions",
        json=CHAT,
        headers={"Authorization": "Bearer sk-not-the-real-key"},
        timeout=30,
    )
    assert resp.status_code == 401, resp.text


def test_gateway_rejects_a_missing_key(settings: Settings) -> None:
    resp = httpx.post(
        f"{settings.litellm_base_url}/v1/chat/completions",
        json=CHAT,
        timeout=30,
    )
    assert resp.status_code == 401, resp.text
