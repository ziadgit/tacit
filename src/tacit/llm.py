"""Structured extraction with the OpenAI Responses API over httpx (SPEC §13.4).

`POST https://api.openai.com/v1/responses` with `text.format` = a strict JSON schema, then the
output text is parsed as JSON. The default model is the kit's (`gpt-6-luna`). Errors never
echo the request (it holds what people said) or the key.
"""

import json
import logging
from typing import Any

import httpx

from .config import Settings, require

log = logging.getLogger("tacit.llm")
URL = "https://api.openai.com/v1/responses"
TIMEOUT_S = 30.0


class LLMError(Exception):
    """The model didn't answer usable JSON. The message holds only a status or a kind."""


def output_text(answer: Any) -> str:
    """The text of a Responses API answer: `output_text`, or the output_text parts."""
    if not isinstance(answer, dict):
        return ""
    if isinstance(answer.get("output_text"), str):
        return answer["output_text"]
    parts = []
    for item in answer.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for piece in item.get("content") or []:
            if isinstance(piece, dict) and piece.get("type") == "output_text":
                parts.append(str(piece.get("text") or ""))
    return "".join(parts).strip()


class LLM:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self._key = require(settings.openai_api_key, "OPENAI_API_KEY")
        self.model = settings.openai_model
        self._http = http

    async def extract(self, text: str, *, name: str, schema: dict[str, Any],
                      instructions: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "instructions": instructions,
            "input": text,
            "text": {"format": {"type": "json_schema", "name": name, "schema": schema,
                                "strict": True}},
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._http is not None:
                r = await self._http.post(URL, json=body, headers=headers, timeout=TIMEOUT_S)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                    r = await http.post(URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"openai unreachable ({type(e).__name__})") from None
        if not r.is_success:
            raise LLMError(f"openai status {r.status_code}")
        try:
            data = json.loads(output_text(r.json()))
        except ValueError:
            raise LLMError("openai sent no JSON") from None
        if not isinstance(data, dict):
            raise LLMError("openai sent no JSON object")
        return data


def make_llm(settings: Settings) -> Any:
    """Claude when ANTHROPIC_API_KEY is set, else OpenAI when OPENAI_API_KEY is set, else None."""
    if settings.anthropic_api_key is not None:
        from .claude_llm import ClaudeLLM

        return ClaudeLLM(settings)
    return LLM(settings) if settings.openai_api_key is not None else None
