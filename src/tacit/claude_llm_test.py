import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from tacit.claude_llm import FALLBACK_BETA, ClaudeLLM
from tacit.llm import LLM, LLMError, make_llm
from tacit.testing import make_settings

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["idea"],
          "properties": {"idea": {"type": "string"}}}


class FakeMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.kwargs = reply, error, None

    async def create(self, **kw):
        self.kwargs = kw
        if self.error:
            raise self.error
        return self.reply


def reply(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[
        SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])


def claude(messages):
    return ClaudeLLM(make_settings(anthropic_api_key="sk-ant-x"),
                     client=SimpleNamespace(beta=SimpleNamespace(messages=messages)))


async def test_request_and_parse():
    m = FakeMessages(reply('{"idea": "backwards"}'))
    out = await claude(m).extract("S0: words", name="idea", schema=SCHEMA, instructions="Fill.")
    assert out == {"idea": "backwards"}
    kw = m.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["system"] == "Fill."
    assert kw["messages"] == [{"role": "user", "content": "S0: words"}]
    assert kw["output_config"] == {"effort": "medium",
                                   "format": {"type": "json_schema", "schema": SCHEMA}}
    assert kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert "thinking" not in kw and "temperature" not in kw


async def test_errors_never_echo():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError("S0: secret words", response=httpx.Response(429, request=req),
                                   body=None)
    with pytest.raises(LLMError) as e:
        await claude(FakeMessages(error=err)).extract("S0: secret words", name="idea",
                                                       schema=SCHEMA, instructions="")
    assert str(e.value) == "anthropic status 429"
    with pytest.raises(LLMError, match="declined"):
        await claude(FakeMessages(reply("", stop="refusal"))).extract(
            "t", name="idea", schema=SCHEMA, instructions="")
    with pytest.raises(LLMError, match="no JSON"):
        await claude(FakeMessages(reply("nope"))).extract("t", name="idea", schema=SCHEMA,
                                                          instructions="")


def test_make_llm_prefers_claude():
    assert make_llm(make_settings()) is None
    assert isinstance(make_llm(make_settings(openai_api_key="k")), LLM)
    both = make_llm(make_settings(openai_api_key="k", anthropic_api_key="sk-ant-x"))
    assert isinstance(both, ClaudeLLM)
    assert json.dumps(SCHEMA)
