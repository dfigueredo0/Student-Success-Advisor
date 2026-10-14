from pathlib import Path

import pytest

from agents import prompts
from agents.prompts import load_prompt


def test_router_prompt_is_versioned_and_renders() -> None:
    p = load_prompt("router_intent")
    assert p.version == "router_intent@1"
    text = p.render(intents="- a: b", examples="Message: x\nIntent: a", message="hi")
    assert text.startswith("You route messages") and text.endswith("Message: hi\nIntent:")
    assert '{"intent": "<intent>"' in text  # literal JSON braces survive templating


def test_message_text_is_not_reinterpreted_as_template() -> None:
    p = load_prompt("router_intent")
    assert "$intents ${x}" in p.render(intents="", examples="", message="$intents ${x}")


def test_missing_placeholder_is_an_error() -> None:
    with pytest.raises(KeyError):
        load_prompt("router_intent").render(intents="", examples="")


@pytest.mark.parametrize(
    "content", ["no front matter\n", "---\nauthor: x\n---\nbody\n", "---\nprompt_version:\n---\nb"]
)
def test_prompt_without_version_is_rejected(
    content: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bad.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    load_prompt.cache_clear()
    try:
        with pytest.raises(ValueError):
            load_prompt("bad")
    finally:
        load_prompt.cache_clear()


def test_crlf_checkout_still_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "w.md").write_bytes(b"---\r\nprompt_version: 3\r\n---\r\nHi $name\r\n")
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    load_prompt.cache_clear()
    try:
        p = load_prompt("w")
        assert (p.version, p.render(name="A")) == ("w@3", "Hi A")
    finally:
        load_prompt.cache_clear()
