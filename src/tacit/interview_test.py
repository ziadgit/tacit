import json

import httpx
import pytest
import respx

from tacit.domain import ContextItem
from tacit.interview import (
    NOTE_SKILL_TOOL,
    SYSTEM_PROMPT,
    VapiApi,
    VapiError,
    assistant_body,
    masked,
)
from tacit.judge_test import FakeJev
from tacit.store import Store
from tacit.testing import client, make_settings, onboard

PHONE = "+14155550100"
SECRET = "vapi-secret-123"


def settings(**kw):
    base = dict(vapi_api_key="vk", vapi_server_secret=SECRET, vapi_assistant_id="asst_1",
                vapi_phone_number_id="pn_1", call_allowlist=PHONE,
                public_base_url="https://tacit.example")
    return make_settings(**{**base, **kw})


class FakeVapi:
    def __init__(self, exc=None):
        self.calls, self.exc = [], exc

    async def create_call(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return {"id": "vapi_call_1"}


def test_assistant_body():
    b = assistant_body(settings(deepgram_api_key="dgk"))
    assert b["name"] == "tacit interview"
    assert b["firstMessage"].startswith("Hi {{name}}, it's tacit.")
    assert b["maxDurationSeconds"] == 600
    assert b["transcriber"] == {"provider": "deepgram", "model": "nova-3", "language": "en",
                                "endpointing": 300}
    assert b["voice"] == {"provider": "deepgram", "voiceId": "asteria"}
    assert b["model"]["messages"] == [{"role": "system", "content": SYSTEM_PROMPT}]
    assert b["model"]["tools"] == [NOTE_SKILL_TOOL]
    assert b["server"] == {"url": "https://tacit.example/vapi/webhook",
                           "headers": {"x-tacit-secret": SECRET}}
    assert b["serverMessages"] == ["tool-calls", "status-update", "end-of-call-report"]
    assert b["credentials"] == [{"provider": "deepgram", "apiKey": "dgk"}]
    assert "credentials" not in assistant_body(settings())
    m = json.dumps(masked(b))
    assert SECRET not in m and "dgk" not in m and m.count('"***"') == 2
    tool = NOTE_SKILL_TOOL["function"]
    assert tool["name"] == "note_skill"
    assert tool["parameters"]["required"] == ["title", "verdict", "reason"]
    assert NOTE_SKILL_TOOL["messages"][0]["content"] == "Let me write that down."


@respx.mock
async def test_vapi_api_create_call_and_errors():
    route = respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(201, json={"id": "c1"}))
    api = VapiApi(settings())
    resp = await api.create_call(phone=PHONE, name="Maya", context="nothing yet",
                                 tacit_call_id="t1")
    assert resp == {"id": "c1"}
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer vk"
    assert json.loads(req.content) == {
        "assistantId": "asst_1", "phoneNumberId": "pn_1",
        "customer": {"number": PHONE, "name": "Maya"},
        "assistantOverrides": {"variableValues": {"name": "Maya", "context": "nothing yet"},
                               "metadata": {"tacit_call_id": "t1"}}}
    respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(400, json={"message": f"bad number {PHONE}"}))
    with pytest.raises(VapiError) as e:
        await api.create_call(phone=PHONE, name="Maya", context="x", tacit_call_id="t1")
    assert str(e.value) == "vapi status 400" and PHONE not in str(e.value)
    respx.patch("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1"}))
    assert (await api.update_assistant("a1", {}))["id"] == "a1"


def test_call_flow(tmp_path):
    store = Store(tmp_path / "t.db")
    vapi = FakeVapi()
    c = client(tmp_path, settings(), store=store, vapi=vapi, jev=FakeJev())
    me = onboard(c)
    store.add_context_items([ContextItem(user_id=me["id"], kind="role", text="Head of product",
                                         source_url="https://a.com", status="kept"),
                             ContextItem(user_id=me["id"], kind="role", text="pending one",
                                         source_url="https://a.com")])
    r = c.post("/api/call")
    assert r.status_code == 200, r.text
    call = r.json()
    assert call["status"] == "queued"
    kw = vapi.calls[0]
    assert kw == {"phone": PHONE, "name": "Maya", "context": "Head of product",
                  "tacit_call_id": call["id"]}
    assert store.get_call(call["id"]).vapi_call_id == "vapi_call_1"
    assert c.post("/api/call").status_code == 409

    hdr = {"x-tacit-secret": SECRET}
    meta = {"call": {"id": "vapi_call_1",
                     "assistantOverrides": {"metadata": {"tacit_call_id": call["id"]}}}}
    r = c.post("/vapi/webhook", headers=hdr, json={"message": {
        **meta, "type": "status-update", "status": "in-progress"}})
    assert r.json() == {}
    assert c.get("/api/call/status").json()["call"]["status"] == "in-progress"

    args = {"title": "Open an update with the number", "verdict": "Lead with it " * 40,
            "reason": "People stop reading", "quote": "I put the number first"}
    r = c.post("/vapi/webhook", headers=hdr, json={"message": {
        **meta, "type": "tool-calls", "toolCallList": [
            {"id": "tc_1", "type": "function",
             "function": {"name": "note_skill", "arguments": json.dumps(args)}},
            {"id": "tc_2", "function": {"name": "note_skill", "arguments": {"title": "x"}}},
        ]}})
    res = r.json()["results"]
    assert res[0] == {"name": "note_skill", "toolCallId": "tc_1",
                      "result": "Saved: Open an update with the number."}
    assert res[1]["toolCallId"] == "tc_2" and "error" in res[1] and "result" not in res[1]
    skills = store.skills_mine(me["id"])
    (s,) = skills
    assert s.status == "draft" and s.source == "interview" and len(s.verdict) == 280
    assert (s.jev_specific, s.jev_own) == (0.8, 0.3)
    st = c.get("/api/call/status").json()
    assert st["skills"] == 1 and st["active"] is True

    r = c.post("/vapi/webhook", headers=hdr, json={"message": {
        "call": {"id": "vapi_call_1"}, "type": "end-of-call-report", "endedReason": "hangup",
        "transcript": "SECRET WORDS", "recordingUrl": "https://rec", "summary": "sum"}})
    assert r.status_code == 200
    got = store.get_call(call["id"])
    assert got.status == "ended" and got.ended_reason == "hangup"
    dump = "\n".join(store.db.iterdump())
    assert "SECRET WORDS" not in dump and "https://rec" not in dump


def test_call_guards(tmp_path):
    c = client(tmp_path, settings(calls_per_user_per_day=1), vapi=FakeVapi())
    onboard(c, consent_call=False)
    assert c.post("/api/call").status_code == 403
    c.patch("/api/me", json={"consent_call": True})
    c.cookies.clear()
    onboard(c, phone="+14155550111", name="Ana")
    r = c.post("/api/call")
    assert r.status_code == 403
    assert r.json() == {"detail": "calls are limited to the team's test numbers right now"}


def test_empty_allowlist_means_no_calls(tmp_path):
    vapi = FakeVapi()
    c = client(tmp_path, settings(call_allowlist=""), vapi=vapi)
    onboard(c)
    assert c.post("/api/call").status_code == 403
    assert vapi.calls == []
    assert c.get("/api/config").json()["calls_enabled"] is False


def test_rate_limit_and_vapi_failure(tmp_path):
    store = Store(tmp_path / "t.db")
    c = client(tmp_path, settings(calls_per_user_per_day=1), store=store,
               vapi=FakeVapi(exc=VapiError("vapi status 500")))
    me = onboard(c)
    r = c.post("/api/call")
    assert r.status_code == 502 and "+1415" not in r.text
    assert store.latest_call(me["id"]).status == "failed"
    assert c.post("/api/call").status_code == 429


def test_webhook_secret(tmp_path):
    c = client(tmp_path, settings())
    assert c.post("/vapi/webhook", json={"message": {}}).status_code == 401
    assert c.post("/vapi/webhook", headers={"x-tacit-secret": "nope"},
                  json={}).status_code == 401
    c2 = client(tmp_path / "b", settings(vapi_server_secret=None))
    assert c2.post("/vapi/webhook", headers={"x-tacit-secret": ""}, json={}).status_code == 401
    r = c.post("/vapi/webhook", headers={"x-tacit-secret": SECRET}, json={"message": "x"})
    assert r.json() == {}
    r = c.post("/vapi/webhook", headers={"x-tacit-secret": SECRET}, content=b"not json")
    assert r.status_code == 200


def test_tool_call_without_known_call(tmp_path):
    c = client(tmp_path, settings())
    r = c.post("/vapi/webhook", headers={"x-tacit-secret": SECRET}, json={"message": {
        "type": "tool-calls", "toolCallList": [
            {"id": "t9", "function": {"name": "note_skill", "arguments": "{}"}}]}})
    (res,) = r.json()["results"]
    assert res["toolCallId"] == "t9" and "error" in res


def test_inbound_assistant_request(tmp_path):
    store = Store(tmp_path / "t.db")
    c = client(tmp_path, settings(), store=store)
    me = onboard(c)
    hdr = {"x-tacit-secret": SECRET}
    r = c.post("/vapi/webhook", headers=hdr, json={"message": {
        "type": "assistant-request", "call": {"id": "in_1", "customer": {"number": PHONE}}}})
    j = r.json()
    assert j["assistantId"] == "asst_1"
    cid = j["assistantOverrides"]["metadata"]["tacit_call_id"]
    assert j["assistantOverrides"]["variableValues"] == {"name": "Maya", "context": "nothing yet"}
    call = store.get_call(cid)
    assert call.direction == "inbound" and call.user_id == me["id"]
    r = c.post("/vapi/webhook", headers=hdr, json={"message": {
        "type": "assistant-request", "call": {"customer": {"number": "+19995550000"}}}})
    assert r.json() == {"error": "Please sign up in the tacit app first, then call again."}
