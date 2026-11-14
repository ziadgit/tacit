import json

import httpx
import pytest
import respx

from tacit.llm import LLM, URL, LLMError, make_llm, output_text
from tacit.testing import make_settings

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["idea"],
          "properties": {"idea": {"type": "string"}}}


def answer(text):
    return {"output": [{"type": "reasoning"}, {"type": "message", "content": [
        {"type": "output_text", "text": text}]}]}


@respx.mock
async def test_extract_request_and_parse():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=answer('{"idea": "x"}')))
    llm = LLM(make_settings(openai_api_key="sk-sekrit"))
    out = await llm.extract("S0: words", name="idea", schema=SCHEMA, instructions="Fill it.")
    assert out == {"idea": "x"}
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer sk-sekrit"
    body = json.loads(req.content)
    assert body["model"] == "gpt-6-luna" and body["input"] == "S0: words"
    assert body["text"] == {"format": {"type": "json_schema", "name": "idea", "schema": SCHEMA,
                                       "strict": True}}


@respx.mock
async def test_errors_never_echo():
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "sk-sekrit S0: words"}))
    llm = LLM(make_settings(openai_api_key="sk-sekrit"))
    with pytest.raises(LLMError) as e:
        await llm.extract("S0: words", name="idea", schema=SCHEMA, instructions="")
    assert str(e.value) == "openai status 401"
    respx.post(URL).mock(return_value=httpx.Response(200, json=answer("not json")))
    with pytest.raises(LLMError):
        await llm.extract("t", name="idea", schema=SCHEMA, instructions="")
    respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(LLMError, match="unreachable"):
        await llm.extract("t", name="idea", schema=SCHEMA, instructions="")


def test_output_text_and_make():
    assert output_text({"output_text": "a"}) == "a"
    assert output_text(answer("b")) == "b"
    assert output_text(None) == ""
    assert make_llm(make_settings()) is None
    assert make_llm(make_settings(openai_api_key="k")) is not None
