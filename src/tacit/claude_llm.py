"""Structured extraction with Claude (Anthropic Messages API, official `anthropic` SDK).

The same contract as `llm.LLM`: `await extract(text, name=, schema=, instructions=) -> dict`,
raising `llm.LLMError` (with only a status or a kind, never the request text or the key).
The schema goes in `output_config.format` (`json_schema`), so the reply's text block is valid
JSON for it. Used instead of OpenAI when ANTHROPIC_API_KEY is set (see `llm.make_llm`).

Server-side refusal fallbacks are on (`fallbacks: "default"`): if a safety classifier declines
a request, the API re-runs it on a fallback model within the same call.
"""

import json
import logging
from typing import Any

import anthropic

from .config import Settings, require
from .llm import LLMError

log = logging.getLogger("tacit.claude")
MAX_TOKENS = 16000          # thinking is always on (adaptive) and counts toward this
TIMEOUT_S = 90.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeLLM:
    def __init__(self, settings: Settings, client: Any = None):
        self.model = settings.claude_model
        self.effort = settings.claude_effort
        self._client = client or anthropic.AsyncAnthropic(
            api_key=require(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
            max_retries=1, timeout=TIMEOUT_S)

    async def extract(self, text: str, *, name: str, schema: dict[str, Any],
                      instructions: str) -> dict[str, Any]:
        try:
            resp = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=instructions,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as e:
            raise LLMError(f"anthropic unreachable ({type(e).__name__})") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic status {e.status_code}") from None
        if resp.stop_reason == "refusal":
            raise LLMError("anthropic declined")
        if resp.stop_reason == "max_tokens":
            raise LLMError("anthropic ran out of tokens")
        out = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(out)
        except ValueError:
            raise LLMError("anthropic sent no JSON") from None
        if not isinstance(data, dict):
            raise LLMError("anthropic sent no JSON object")
        log.info("claude extract %s", name)
        return data
