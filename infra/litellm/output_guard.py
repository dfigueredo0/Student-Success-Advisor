"""Output guardrail for the LiteLLM gateway.
Runs after every model call (post_call) and replaces student identifiers in the
answer with "[removed]" before it reaches the app. It also refuses streamed
requests (pre_call), because streamed answers are sent piece by piece and would
skip the check.
"""

import re

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail

REDACTED = "[removed]"

# Assumed formats; confirm against real IIT records.
SENSITIVE_PATTERNS = [
    re.compile(r"\bA\d{8}\b", re.IGNORECASE),  # IIT student ID, e.g. A20123456
    re.compile(r"\b[\w.+-]+@hawk\.(iit|illinoistech)\.edu\b", re.IGNORECASE),  # student email
]


def redact(text: str) -> str:
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class OutputGuard(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("stream"):
            raise HTTPException(
                status_code=400,
                detail={"error": "Streaming is not allowed: answers must pass the output check"},
            )
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        for choice in getattr(response, "choices", []):
            message = getattr(choice, "message", None)
            if message is None:
                continue
            # reasoning_content = the model's "thinking" text, which qwen3 also returns.
            for field in ("content", "reasoning_content"):
                value = getattr(message, field, None)
                if isinstance(value, str):
                    setattr(message, field, redact(value))
        return response
