"""Output guardrail for the LiteLLM gateway.
Runs after every model call (post_call) and replaces personal data in the answer, the
model's thinking text and any tool-call arguments with "[removed]" before it reaches the app.
It also refuses streamed requests (pre_call), because streamed answers are sent piece by
piece and would skip the check.

What counts as personal data lives in src/domain/redaction.py, which the app's merge node
uses too; docker-compose.yml mounts it into the container and puts it on PYTHONPATH.
"""

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail
from redaction import redact


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
            # A tool call's arguments are model-written text too, and the app acts on them.
            for call in getattr(message, "tool_calls", None) or []:
                function = getattr(call, "function", None)
                arguments = getattr(function, "arguments", None)
                if isinstance(arguments, str):
                    function.arguments = redact(arguments)
        return response
