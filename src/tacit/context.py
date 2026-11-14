"""Context lookup with Exa (SPEC §6): one search about the signed-in person, reviewed by them."""

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import current_user, get_settings, get_store
from .config import Settings
from .domain import ContextItem, ContextItemOut, User
from .store import Store

log = logging.getLogger("tacit.context")
MAX_ITEMS = 12
KINDS = ("role", "expertise", "work", "writing", "other")

PROFILE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {
        "kind": {"type": "string", "enum": ["role", "expertise", "work", "writing", "other"]},
        "text": {"type": "string"}, "source_url": {"type": "string"}},
    "required": ["kind", "text", "source_url"]}}}, "required": ["items"]}

SYSTEM_PROMPT = ("Only include facts about this one person that are clearly supported by a "
                 "source. Each item is one short fact in plain words with its source URL. Never "
                 "guess; return an empty list when unsure it is the same person.")


class LookupError_(Exception):
    """The lookup failed (timeout, error, bad output). Nothing is stored."""


def search_kwargs(user: User) -> tuple[str, dict[str, Any]]:
    """The one query and its exact kwargs. Never contains the phone number."""
    n, h = user.name, user.headline or ""
    links = " ".join(str(u) for u in user.links)
    query = f"{n} {h} {links}".strip()
    query = " ".join(query.split())
    return query, {
        "type": "auto",
        "objective": (
            f"Find public professional information about {n} ({h}): roles, areas of expertise, "
            "notable work and writing. Prefer the pages the person linked and pages they wrote "
            "themselves. Exclude other people with the same name, people-search and data-broker "
            "sites, and anything about their private life, family, address or health."),
        "system_prompt": SYSTEM_PROMPT,
        "output_schema": PROFILE_SCHEMA,
        "contents": {"highlights": True},
    }


def parse_items(content: Any, user_id: str) -> list[ContextItem]:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return []
    if not isinstance(content, dict):
        return []
    raw = content.get("items")
    if not isinstance(raw, list):
        return []
    out: list[ContextItem] = []
    for it in raw:
        if len(out) >= MAX_ITEMS:
            break
        if not isinstance(it, dict):
            continue
        kind, text, url = it.get("kind"), it.get("text"), it.get("source_url")
        if kind not in KINDS or not isinstance(text, str) or not isinstance(url, str):
            continue
        text = " ".join(text.split())[:200]
        if not text or not url.startswith(("http://", "https://")):
            continue
        out.append(ContextItem(user_id=user_id, kind=kind, text=text, source_url=url))
    return out


async def lookup(user: User, exa: Any, settings: Settings) -> list[ContextItem]:
    query, kwargs = search_kwargs(user)
    try:
        async with asyncio.timeout(settings.exa_timeout_s):
            resp = await exa.search(query, **kwargs)
    except Exception as e:  # noqa: BLE001 - never echo the message (may hold request details)
        log.warning("exa lookup failed: %s", type(e).__name__)
        raise LookupError_ from None
    output = getattr(resp, "output", None)
    if output is None and isinstance(resp, dict):
        output = resp.get("output")
    content = output.get("content") if isinstance(output, dict) else getattr(
        output, "content", None)
    return parse_items(content, user.id)


def context_text(store: Store, user_id: str, limit: int = 600) -> str:
    text = "; ".join(c.text for c in store.kept_context(user_id))
    return text[:limit] if text else "nothing yet"


router = APIRouter()


class StatusIn(BaseModel):
    status: Literal["kept", "removed"]


@router.post("/api/context/lookup")
async def api_lookup(request: Request, user: Annotated[User, Depends(current_user)],
                     store: Annotated[Store, Depends(get_store)],
                     settings: Annotated[Settings, Depends(get_settings)]
                     ) -> list[ContextItemOut]:
    if not user.consent_lookup:
        raise HTTPException(403, "turn on \"look me up\" first")
    exa = request.app.state.exa
    if exa is None:
        raise HTTPException(503, "web lookup isn't set up")
    if not store.allow(user.id, "lookup", settings.lookups_per_user_per_day):
        raise HTTPException(429, "that's enough lookups for today")
    try:
        items = await lookup(user, exa, settings)
    except LookupError_:
        raise HTTPException(502, "couldn't look you up right now") from None
    store.add_context_items(items)
    log.info("exa lookup: %d items", len(items))
    return [ContextItemOut(**i.model_dump()) for i in items]


@router.patch("/api/context/{item_id}")
def api_context_status(item_id: str, body: StatusIn,
                       user: Annotated[User, Depends(current_user)],
                       store: Annotated[Store, Depends(get_store)]) -> ContextItemOut:
    item = store.get("context_items", item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "not found")
    store.update("context_items", item_id, status=body.status)
    return ContextItemOut(**store.get("context_items", item_id).model_dump())
