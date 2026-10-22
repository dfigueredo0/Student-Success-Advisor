"""Follow-ups: fill the fields an agent would ask for from the conversation.

The agents' extractors read only the latest message, so "and SQL?" after a list of Python
courses gives the Career agent no skill to look up, and "can I take the first one?" gives the
College Advisor no course. When a field is still missing, the model reads the conversation
(memory.context: recent messages plus earlier ones that match) and answers that field's
question for the student. The agent parses the answer with the field's own extractor, so the
value has its usual shape, and asks its question as before when nothing comes back.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from langfuse import get_client, observe

from agents.base import Field
from agents.prompts import load_prompt
from memory import EXAMPLES, context, words
from orchestrator.router import Completion, gateway_complete
from settings import get_settings

FOLLOWUP_PROMPT = load_prompt("followup_slots")

_JOINERS = frozenset({"and", "or"})
_EMPTY = re.compile(r"^\s*(none|nothing|no|n/?a|unknown)?\s*[.!]?\s*$", re.I)
_PARTS = re.compile(r"\s*(?:,|;|\band\b)\s*", re.I)

# (fields the agent would ask for, latest message, the conversation before it)
# -> field name -> answer text, only for the fields the conversation answers
Filler = Callable[[list[Field], str, list[dict[str, str]]], dict[str, str]]


@observe(name="followup")
def fill_slots(
    fields: list[Field],
    text: str,
    history: list[dict[str, str]],
    complete: Completion = gateway_complete,
) -> dict[str, str]:
    # TODO: security - the conversation is untrusted student input inside the prompt; every
    # answer is checked against it below and parsed by the field's extractor.
    seen = context(history, text)
    names = [f.name for f in fields]
    questions = "\n".join(f"- {f.name}: {EXAMPLES.sub('', f.question)}" for f in fields)
    payload: dict[str, Any] = {
        "model": get_settings().llm_default_model,
        "messages": [
            {
                "role": "user",
                "content": FOLLOWUP_PROMPT.render(fields=questions, history=seen, message=text),
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "details",
                "schema": {
                    "type": "object",
                    "properties": {n: {"type": "string"} for n in names},
                    "required": names,
                },
            },
        },
        "temperature": 0,
        "reasoning_effort": "none",  # as in ollama_classify: no hidden thinking on CPU
        "max_tokens": 128,
        "metadata": {"prompt_version": FOLLOWUP_PROMPT.version},
    }
    get_client().update_current_span(
        version=FOLLOWUP_PROMPT.version, metadata={"prompt_version": FOLLOWUP_PROMPT.version}
    )
    try:
        out = json.loads(complete(payload))
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return {}  # gateway/model unavailable or unparseable -> the agent asks
    if not isinstance(out, dict):
        return {}
    # Grounded answers only: every word must be in what the model was shown. Remembered fields
    # are facts about the student (their courses, skills, goal), so those must come from the
    # student's own messages, never from a course list the advisor sent.
    said = words(" ".join([text, *(m["content"] for m in history if m["role"] == "user")]))
    shown = words(f"{seen}\n{text}")
    filled = {}
    for f in fields:
        answer = out.get(f.name)
        # "none" is the student's to say. From the model it is a guess (often an earlier "none"
        # that answered another question), and the extractors would store it as an empty list.
        if not isinstance(answer, str) or _EMPTY.match(answer):
            continue
        if not words(answer) - _JOINERS <= (said if f.remember else shown):
            continue
        # The latest message replaces what it names: "and for SQL?" after Python is SQL alone,
        # even when the model merges the two (qwen3:1.7b did, 2026-10-22).
        named = [p for p in _PARTS.split(answer) if p and words(p) <= words(text)]
        filled[f.name] = ", ".join(named) if named else answer
    return filled
