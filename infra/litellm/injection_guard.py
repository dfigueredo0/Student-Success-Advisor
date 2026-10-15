"""Prompt-injection guardrail for the LiteLLM gateway.

Runs before every model call (mode: pre_call) and blocks requests whose messages
contain well-known prompt-injection phrases.
"""

import re
import unicodedata

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail

# Phrases attackers use to make the model drop its instructions (case-insensitive).
INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(ignore|disregard|forget)\b.{0,20}\b(previous|prior|above|earlier|all)\b"
        r".{0,20}\b(instructions|rules|guidelines|prompts?)\b",
        # "you are now a pirate" / "you are now in developer mode", but not
        # "since you are now my advisor".
        r"\byou are now (a|an|in|acting|playing|free)\b",
        # Asking for the hidden prompt, but not "show me your instructions for registering".
        r"\b(reveal|show|print|repeat)\b.{0,20}"
        r"\b(system prompt|(your|the) (hidden|secret|original|initial|system) "
        r"(instructions|prompt))\b",
        r"\b(developer mode|jailbreak)\b",
    ]
]


# Look-alike characters swapped in to slip past the patterns ("ign0re", "1nstructions").
LOOKALIKES = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)

# Three or more single letters separated by single spaces: "i g n o r e".
SPACED_LETTERS = re.compile(r"\b\w(?: \w\b){2,}")


def normalize(text: str) -> str:
    """A version of the text with common disguises undone, used only for matching."""
    # Split accented letters into letter + mark, then drop the marks and invisible
    # characters such as zero-width spaces.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        ch for ch in text if not unicodedata.combining(ch) and unicodedata.category(ch) != "Cf"
    )
    text = text.lower().translate(LOOKALIKES)
    # Words stay apart where there were several spaces: "i g n o r e   a l l" -> "ignore all".
    return SPACED_LETTERS.sub(lambda m: m.group().replace(" ", ""), text)


def message_texts(content: object) -> list[str]:
    """All the text in a message, whether it is a plain string or a list of parts."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        # OpenAI-style parts: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        return [
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
    return []


class PromptInjectionGuard(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        for message in data.get("messages", []):
            for text in message_texts(message.get("content")):
                variants = (text, normalize(text))
                if any(p.search(v) for p in INJECTION_PATTERNS for v in variants):
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "Blocked by the prompt-injection guardrail"},
                    )
        return data
