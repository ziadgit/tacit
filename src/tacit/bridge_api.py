"""Pairing and the bridge API on the server (SPEC §13.1, §13.2).

The wearer pairs a band in the PWA (`/api/band/*`, session cookie). The bridge, the program
connected to that band, talks to `/api/bridge/*` with the Bearer token shown once at pairing;
only its SHA-256 is stored.

Mute commands: the PWA (or Jev's `stop_request`, §13.4) sets `muted` with `pending=True`. The
bridge polls `/api/bridge/commands` and gets `{"muted", "changed"}`; it always obeys a mute,
and obeys an unmute only when `changed` is true (so a stale "unmuted" can never undo a mute
the wearer just made with a gesture). Every state report makes the stored `muted` follow the
bridge's real state, unless a PWA command is still waiting to be picked up.
"""

import hashlib
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .auth import current_user, get_settings, get_store
from .config import TEAM_BANDS, Settings
from .domain import CREATIVE_KINDS, BridgeDevice, Moment, Segment, User, first_name, now
from .store import Store

log = logging.getLogger("tacit.bridge")
router = APIRouter()

BRIDGE_PER_MINUTE = 240         # polls every 2 s + state every 10 s + uploads, with room
MAX_REWIND_S = 3600
KEEP_WINDOW_S = 60              # double-tap "keep that" marks the last minute
MOTION_KINDS = (*CREATIVE_KINDS, "typing", "presenting", "walking_meeting", "demonstration")
BRIDGE_MOMENT_KINDS = (*MOTION_KINDS, "kept")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class _Rate:
    """A sliding one-minute window per device, in memory (the bridge polls a lot)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        t = time.monotonic()
        q = self.hits[key]
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(t)
        return True


def _rate(request: Request) -> _Rate:
    st = request.app.state
    if getattr(st, "bridge_rate", None) is None:
        st.bridge_rate = _Rate(BRIDGE_PER_MINUTE)
    return st.bridge_rate


def current_device(request: Request) -> BridgeDevice:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "bridge token needed")
    dev = get_store(request).device_by_token(token_hash(token.strip()))
    if dev is None:
        raise HTTPException(401, "unknown bridge token")
    if not _rate(request).allow(dev.id):
        raise HTTPException(429, "slow down")
    return dev


Device = Annotated[BridgeDevice, Depends(current_device)]
StoreDep = Annotated[Store, Depends(get_store)]
CurrentUser = Annotated[User, Depends(current_user)]


def set_mute_command(store: Store, dev: BridgeDevice, muted: bool) -> BridgeDevice:
    state = {**dev.last_state, "pending": True}
    return store.update_device(dev.id, muted=muted, last_state=state)


def band_out(dev: BridgeDevice | None, settings: Settings) -> dict[str, Any] | None:
    if dev is None:
        return None
    st = dev.last_state or {}
    fresh = dev.last_seen is not None and now() - utc(dev.last_seen) < timedelta(seconds=30)
    connected = bool(fresh and st.get("connected"))
    reported_muted = st.get("muted")
    return {
        "band": dev.band,
        "muted": dev.muted,
        "online": bool(fresh),
        "connected": connected,
        # listening only while the bridge itself says so, recently, and it isn't muted
        "listening": bool(connected and st.get("listening") and not reported_muted),
        "battery": st.get("battery"),
        "buffer_mb": st.get("buffer_mb"),
        "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        "pending": bool(st.get("pending")),
    }


# ---- the wearer's side (PWA) --------------------------------------------------------------


class PairIn(BaseModel):
    band: int


class MuteIn(BaseModel):
    muted: bool


@router.post("/api/band/pair", status_code=201)
def pair(body: PairIn, request: Request, user: CurrentUser, store: StoreDep,
         settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    if body.band not in TEAM_BANDS:
        raise HTTPException(422, f"tacit works only with the team's bands {list(TEAM_BANDS)}")
    other = store.device_by_band(body.band)
    if other is not None and other.user_id != user.id:
        raise HTTPException(409, "that band is linked to someone else")
    mine = store.device_for_user(user.id)
    was_muted = bool(mine and mine.muted)
    if mine is not None:
        store.delete_device(mine.id)   # a new pairing replaces the old token
    if other is not None and other.user_id == user.id and (mine is None or other.id != mine.id):
        store.delete_device(other.id)
    token = secrets.token_urlsafe(32)
    dev = store.add_device(BridgeDevice(user_id=user.id, band=body.band,
                                        token_sha256=token_hash(token), muted=was_muted))
    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    log.info("band paired")
    return {
        "band": dev.band,
        "token": token,     # shown once, never stored
        "env": [f"TACIT_BRIDGE_TOKEN={token}", f"TACIT_SERVER_URL={base}",
                f"TACIT_BAND={dev.band}"],
    }


@router.get("/api/band")
def my_band(user: CurrentUser, store: StoreDep,
            settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    return {"band": band_out(store.device_for_user(user.id), settings),
            "bands": list(TEAM_BANDS)}


@router.post("/api/band/mute")
def mute_command(body: MuteIn, user: CurrentUser, store: StoreDep,
                 settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    dev = store.device_for_user(user.id)
    if dev is None:
        raise HTTPException(404, "connect a band first")
    dev = set_mute_command(store, dev, body.muted)
    log.info("mute command: %s", "mute" if body.muted else "unmute")
    return {"band": band_out(dev, settings)}


@router.delete("/api/band", status_code=204)
def unpair(user: CurrentUser, store: StoreDep) -> Response:
    dev = store.device_for_user(user.id)
    if dev is not None:
        store.delete_device(dev.id)
    return Response(status_code=204)


# ---- the bridge's side -----------------------------------------------------------------------


class StateIn(BaseModel):
    connected: bool = False
    listening: bool = False
    muted: bool = False
    battery: float | None = None
    buffer_mb: float | None = None
    last_sync: datetime | None = None


class SegmentIn(BaseModel):
    started_at: datetime
    ended_at: datetime
    speaker: int | None = None
    text: str = Field(max_length=4000)
    level: float | None = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return utc(v)


class SegmentsIn(BaseModel):
    segments: list[SegmentIn] = Field(max_length=500)


class MomentIn(BaseModel):
    kind: str
    started_at: datetime
    ended_at: datetime
    confidence: float = Field(default=1.0, ge=0, le=1)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return utc(v)


class MomentsIn(BaseModel):
    moments: list[MomentIn] = Field(max_length=200)


class RewindIn(BaseModel):
    seconds: int = Field(ge=0)


KEYTERM = re.compile(r"\b[A-Z][\w+#.-]*(?:\s+[A-Z][\w+#.-]*)*")


def keyterms_for(store: Store, user: User | None) -> list[str]:
    """Up to 20 words Deepgram should listen for: names from the wearer's kept context."""
    if user is None:
        return []
    terms: list[str] = [first_name(user.name)]
    for item in store.kept_context(user.id):
        terms += [m.group(0).strip(" .-") for m in KEYTERM.finditer(item.text)]
    out: list[str] = []
    for t in terms:
        if t and len(t) <= 40 and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:20]


@router.get("/api/bridge/config")
def bridge_config(dev: Device, store: StoreDep) -> dict[str, Any]:
    user = store.get_user(dev.user_id)
    return {"band": dev.band, "keyterms": keyterms_for(store, user),
            "kinds_off": user.kinds_off if user else []}


@router.post("/api/bridge/state")
def bridge_state(body: StateIn, dev: Device, store: StoreDep) -> dict[str, Any]:
    pending = bool(dev.last_state.get("pending"))
    state = body.model_dump(mode="json")
    state["pending"] = pending
    fields: dict[str, Any] = {"last_state": state, "last_seen": now()}
    if not pending:
        fields["muted"] = body.muted   # the bridge's own mute (gesture, phrase) is the truth
    store.update_device(dev.id, **fields)
    return {"ok": True}


@router.get("/api/bridge/commands")
def bridge_commands(dev: Device, store: StoreDep) -> dict[str, Any]:
    changed = bool(dev.last_state.get("pending"))
    if changed:
        store.update_device(dev.id, last_state={**dev.last_state, "pending": False})
    return {"muted": dev.muted, "changed": changed}


def on_segments(request: Request, dev: BridgeDevice, segments: list[Segment]) -> None:
    """Hand new segments to the scenario pipeline (§13.4) when one is set up."""
    hook = getattr(request.app.state, "on_segments", None)
    if hook is not None:
        hook(dev, segments)


@router.post("/api/bridge/segments")
def bridge_segments(body: SegmentsIn, request: Request, dev: Device,
                    store: StoreDep) -> dict[str, int]:
    saved = []
    for s in body.segments:
        text = " ".join(s.text.split())
        if not text:
            continue
        ended = max(s.ended_at, s.started_at)
        saved.append(store.add_segment(Segment(
            device_id=dev.id, user_id=dev.user_id, started_at=s.started_at, ended_at=ended,
            speaker=s.speaker, text=text, level=s.level)))
    log.info("bridge segments: %d", len(saved))
    on_segments(request, dev, saved)
    return {"stored": len(saved)}


def on_kept(request: Request, dev: BridgeDevice, moment: Moment) -> None:
    hook = getattr(request.app.state, "on_kept", None)
    if hook is not None:
        hook(dev, moment)


@router.post("/api/bridge/moments")
def bridge_moments(body: MomentsIn, request: Request, dev: Device,
                   store: StoreDep) -> dict[str, int]:
    user = store.get_user(dev.user_id)
    off = set(user.kinds_off) if user else set()
    stored = 0
    for m in body.moments:
        if m.kind not in BRIDGE_MOMENT_KINDS or m.kind in off:
            continue
        ended = max(m.ended_at, m.started_at)
        started = m.started_at
        if m.kind == "kept":
            started = ended - timedelta(seconds=KEEP_WINDOW_S)
        moment = store.add_moment(Moment(
            user_id=dev.user_id, kind=m.kind, started_at=started, ended_at=ended,
            confidence=m.confidence, source="motion", title=KIND_TITLES.get(m.kind, m.kind),
            body={"minutes": int((ended - started).total_seconds() // 60)}))
        stored += 1
        if m.kind == "kept":
            on_kept(request, dev, moment)
    log.info("bridge moments: %d", stored)
    return {"stored": stored}


KIND_TITLES = {
    "writing": "writing", "drawing": "drawing", "whiteboard": "at the whiteboard",
    "typing": "typing", "making": "making something", "presenting": "presenting",
    "walking_meeting": "a walking meeting", "demonstration": "a demonstration",
    "kept": "you kept this minute",
}


def rewind(store: Store, dev: BridgeDevice, seconds: int) -> dict[str, int]:
    """Delete this device's segments from the last N seconds and moments built only on them."""
    seconds = min(max(0, seconds), MAX_REWIND_S)
    since = now() - timedelta(seconds=seconds)
    gone = set(store.delete_segments_since(dev.id, since))
    removed = 0
    if gone:
        for m in store.moments_for(dev.user_id, since=since - timedelta(hours=1)):
            if m.segment_ids and set(m.segment_ids) <= gone:
                store.delete_moment(m.id)
                removed += 1
    log.info("rewind: %ds, %d segments, %d moments", seconds, len(gone), removed)
    return {"segments": len(gone), "moments": removed}


@router.post("/api/bridge/rewind")
def bridge_rewind(body: RewindIn, dev: Device, store: StoreDep) -> dict[str, int]:
    return rewind(store, dev, body.seconds)
