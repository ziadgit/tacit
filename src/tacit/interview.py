"""The interview call (SPEC §7): Vapi assistant, outbound/inbound calls, the webhook."""

import hmac
import json
import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import judge
from .auth import current_user, get_settings, get_store
from .config import Settings, require
from .context import context_text
from .domain import ACTIVE_CALL, Call, CallOut, Skill, User, cut, first_name
from .store import Store

log = logging.getLogger("tacit.interview")
VAPI = "https://api.vapi.ai"

SYSTEM_PROMPT = (
    "You are tacit's interviewer. You are talking with {{name}}. What they confirmed about "
    "themselves: {{context}}. Your job is to draw out one to three skills: things they know how "
    "to do that they never wrote down. Ask about a concrete recent situation, then what they "
    "did, what most people get wrong, and why they do it their way. Ask one short question at a "
    "time and let them talk. When you have heard a skill clearly, call note_skill with a short "
    "imperative title, the verdict (what to do), the reason (why), and their own exact words as "
    "the quote. Then say in one sentence what you saved, and ask if it's right. Never invent "
    "anything they didn't say. Never ask about their private life, health, money or other "
    "people's details. After three skills, or when they want to stop, thank them and say their "
    "skills are waiting for them in the app. Short sentences. No lists."
)

FIRST_MESSAGE = ("Hi {{name}}, it's tacit. I'd like to learn one or two things you know how to "
                 "do that you've never written down. Have you got a few minutes?")

NOTE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "note_skill",
        "description": "Save one skill the person just described, in their own words.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short imperative title, ≤ 80 chars"},
                "verdict": {"type": "string", "description": "What to do, ≤ 280 chars"},
                "reason": {"type": "string", "description": "Why, ≤ 280 chars"},
                "quote": {"type": "string",
                          "description": "Their own exact words, ≤ 200 chars"},
            },
            "required": ["title", "verdict", "reason"],
        },
    },
    "messages": [{"type": "request-start", "content": "Let me write that down."}],
}

STATUS_MAP = {"queued": "queued", "ringing": "ringing", "in-progress": "in-progress",
              "ended": "ended", "failed": "failed"}


def assistant_body(settings: Settings) -> dict[str, Any]:
    base = settings.public_base_url or ""
    secret = settings.vapi_server_secret.get_secret_value() if settings.vapi_server_secret else ""
    body: dict[str, Any] = {
        "name": "tacit interview",
        "firstMessage": FIRST_MESSAGE,
        "maxDurationSeconds": settings.interview_max_seconds,
        "transcriber": {"provider": "deepgram", "model": settings.deepgram_stt_model,
                        "language": "en", "endpointing": 300},
        "voice": {"provider": "deepgram", "voiceId": settings.vapi_voice_id},
        "model": {"provider": settings.vapi_llm_provider, "model": settings.vapi_llm_model,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
                  "tools": [NOTE_SKILL_TOOL]},
        "server": {"url": f"{base}/vapi/webhook", "headers": {"x-tacit-secret": secret}},
        # assistant-request is not an assistant server message: Vapi sends it to the phone
        # number's server URL (inbound), and rejects it here with a 400.
        "serverMessages": ["tool-calls", "status-update", "end-of-call-report"],
    }
    if settings.deepgram_api_key is not None:
        body["credentials"] = [{"provider": "deepgram",
                                "apiKey": settings.deepgram_api_key.get_secret_value()}]
    return body


def masked(body: dict[str, Any]) -> dict[str, Any]:
    """A copy of the assistant body with every secret replaced by "***" (for --dry-run)."""
    b = json.loads(json.dumps(body))
    if "server" in b:
        b["server"]["headers"] = {k: "***" for k in b["server"].get("headers", {})}
    for cred in b.get("credentials", []):
        cred["apiKey"] = "***"
    return b


class VapiError(Exception):
    """A Vapi REST error. The message holds only the status code, never the request body."""


class VapiApi:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self._key = require(settings.vapi_api_key, "VAPI_API_KEY")
        self._http = http
        self.settings = settings

    async def _req(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._http is not None:
                r = await self._http.request(method, VAPI + path, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15) as http:
                    r = await http.request(method, VAPI + path, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise VapiError(f"vapi unreachable ({type(e).__name__})") from None
        if not r.is_success:
            raise VapiError(f"vapi status {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise VapiError("vapi sent a bad response") from None

    async def create_assistant(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._req("POST", "/assistant", body)

    async def update_assistant(self, assistant_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._req("PATCH", f"/assistant/{assistant_id}", body)

    async def create_call(self, *, phone: str, name: str, context: str, tacit_call_id: str
                          ) -> dict[str, Any]:
        s = self.settings
        return await self._req("POST", "/call", {
            "assistantId": s.vapi_assistant_id,
            "phoneNumberId": s.vapi_phone_number_id,
            "customer": {"number": phone, "name": name},
            "assistantOverrides": overrides(name, context, tacit_call_id),
        })


def overrides(name: str, context: str, tacit_call_id: str) -> dict[str, Any]:
    return {"variableValues": {"name": name, "context": context},
            "metadata": {"tacit_call_id": tacit_call_id}}


# ---- webhook ----------------------------------------------------------------------------


def _d(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def find_call(store: Store, message: dict[str, Any]) -> Call | None:
    call = _d(message.get("call"))
    for cid in (_d(_d(call.get("assistantOverrides")).get("metadata")).get("tacit_call_id"),
                _d(call.get("metadata")).get("tacit_call_id")):
        if isinstance(cid, str) and (found := store.get_call(cid)):
            return found
    vid = call.get("id")
    return store.call_by_vapi_id(vid) if isinstance(vid, str) else None


def _args(tc: dict[str, Any]) -> dict[str, Any]:
    fn = _d(tc.get("function"))
    raw = fn.get("arguments", tc.get("arguments"))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return _d(raw)


async def handle_tool_calls(message: dict[str, Any], store: Store, jev: Any,
                            settings: Settings) -> dict[str, Any]:
    call = find_call(store, message)
    results = []
    tool_calls = message.get("toolCallList")
    for tc in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(tc, dict):
            continue
        name = _d(tc.get("function")).get("name") or tc.get("name") or ""
        out: dict[str, Any] = {"name": name, "toolCallId": tc.get("id") or ""}
        log.info("vapi tool call: %s", name)
        if name != "note_skill":
            out["error"] = f"Unknown tool {name}."
        elif call is None:
            out["error"] = "I couldn't find this call, so I can't save that."
        else:
            a = _args(tc)
            title, verdict, reason = (cut(a.get("title"), 80), cut(a.get("verdict"), 280),
                                      cut(a.get("reason"), 280))
            if not (title and verdict and reason):
                out["error"] = "A skill needs a title, a verdict and a reason."
            else:
                skill = Skill(owner_id=call.user_id, title=title, verdict=verdict,
                              reason=reason, quote=cut(a.get("quote"), 200),
                              source="interview", call_id=call.id)
                skill.jev_specific, skill.jev_own = await judge.check(skill, jev, settings)
                store.add_skill(skill)
                out["result"] = f"Saved: {title}."
        results.append(out)
    return {"results": results}


def handle_assistant_request(message: dict[str, Any], store: Store,
                             settings: Settings) -> dict[str, Any]:
    call = _d(message.get("call"))
    number = _d(call.get("customer")).get("number")
    user = store.user_by_phone(number) if isinstance(number, str) else None
    if user is None or not user.consent_call or not settings.vapi_assistant_id:
        return {"error": "Please sign up in the tacit app first, then call again."}
    vid = call.get("id") if isinstance(call.get("id"), str) else None
    c = store.add_call(Call(user_id=user.id, direction="inbound", vapi_call_id=vid,
                            status="ringing"))
    log.info("vapi inbound call accepted")
    return {"assistantId": settings.vapi_assistant_id,
            "assistantOverrides": overrides(first_name(user.name),
                                            context_text(store, user.id), c.id)}


router = APIRouter()


@router.post("/vapi/webhook")
async def vapi_webhook(request: Request) -> Any:
    settings: Settings = request.app.state.settings
    store: Store = request.app.state.store
    secret = settings.vapi_server_secret
    given = request.headers.get("x-tacit-secret", "")
    if secret is None or not hmac.compare_digest(given.encode(),
                                                 secret.get_secret_value().encode()):
        return JSONResponse({"detail": "bad secret"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        return {}
    message = _d(_d(payload).get("message"))
    kind = message.get("type")
    if kind == "tool-calls":
        return await handle_tool_calls(message, store, request.app.state.jev, settings)
    if kind == "assistant-request":
        return handle_assistant_request(message, store, settings)
    call = find_call(store, message)
    if kind == "status-update" and call is not None:
        status = STATUS_MAP.get(str(message.get("status")))
        if status:
            store.update_call(call.id, status=status)
            log.info("vapi call status: %s", status)
    elif kind == "end-of-call-report" and call is not None:
        # Never store the transcript, recording URL or summary.
        reason = message.get("endedReason")
        store.update_call(call.id, status="ended",
                          ended_reason=cut(reason, 120) if isinstance(reason, str) else None)
        log.info("vapi call ended")
    return {}


@router.post("/api/call")
async def start_call(request: Request, user: Annotated[User, Depends(current_user)],
                     store: Annotated[Store, Depends(get_store)],
                     settings: Annotated[Settings, Depends(get_settings)]) -> CallOut:
    from datetime import timedelta

    from .domain import now

    if not user.consent_call:
        raise HTTPException(403, "turn on \"tacit may call me\" first")
    if store.count_events(user.id, "call", now() - timedelta(days=1)) >= \
            settings.calls_per_user_per_day:
        raise HTTPException(429, "that's enough calls for today")
    if store.active_call(user.id):
        raise HTTPException(409, "you already have a call going")
    if user.phone not in settings.call_allowlist:
        raise HTTPException(403, "calls are limited to the team's test numbers right now")
    vapi = request.app.state.vapi
    if vapi is None or not settings.vapi_assistant_id or not settings.vapi_phone_number_id:
        raise HTTPException(503, "calls aren't set up yet")
    store.add_event(user.id, "call")
    call = store.add_call(Call(user_id=user.id, direction="outbound"))
    try:
        resp = await vapi.create_call(phone=user.phone, name=first_name(user.name),
                                      context=context_text(store, user.id),
                                      tacit_call_id=call.id)
    except Exception as e:  # noqa: BLE001 - the error text never echoes the request
        log.warning("vapi create_call failed: %s", type(e).__name__)
        store.update_call(call.id, status="failed", ended_reason="couldn't start the call")
        raise HTTPException(502, "couldn't start the call") from None
    vid = resp.get("id") if isinstance(resp, dict) else None
    call = store.update_call(call.id, vapi_call_id=vid if isinstance(vid, str) else None)
    log.info("vapi call queued")
    return CallOut(**call.model_dump())


@router.get("/api/call/status")
def call_status(user: Annotated[User, Depends(current_user)],
                store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    call = store.latest_call(user.id)
    return {
        "call": CallOut(**call.model_dump()).model_dump(mode="json") if call else None,
        "skills": store.skills_from_call(call.id) if call else 0,
        "active": bool(call and call.status in ACTIVE_CALL),
    }
