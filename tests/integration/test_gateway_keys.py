"""The router's gateway key can do its job and nothing more (least privilege)."""

from collections.abc import Iterator

import httpx
import pytest

from settings import Settings

CHAT = {"messages": [{"role": "user", "content": "Say hi"}], "max_tokens": 5}


@pytest.fixture(scope="module")
def router_gateway(settings: Settings) -> Iterator[httpx.Client]:
    key = settings.litellm_router_key.get_secret_value()
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=settings.litellm_base_url, headers=headers, timeout=60) as c:
        yield c


def test_router_key_can_use_its_model(router_gateway: httpx.Client) -> None:
    resp = router_gateway.post("/v1/chat/completions", json={"model": "local-llm", **CHAT})
    assert resp.status_code == 200, resp.text


def test_router_key_cannot_use_other_models(router_gateway: httpx.Client) -> None:
    resp = router_gateway.post("/v1/chat/completions", json={"model": "some-other-model", **CHAT})
    assert resp.status_code == 403, resp.text


def test_router_key_cannot_create_keys(router_gateway: httpx.Client) -> None:
    resp = router_gateway.post("/key/generate", json={})
    assert resp.status_code == 401, resp.text