"""Domain models (SPEC §2, §13.5). API responses use the separate `...Out` models."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, HttpUrl, StringConstraints

Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{7,14}$")]  # E.164 only

ContextKind = Literal["role", "expertise", "work", "writing", "other"]
CallStatus = Literal["queued", "ringing", "in-progress", "ended", "failed"]
ACTIVE_CALL = ("queued", "ringing", "in-progress")

MomentKind = Literal[
    "stop_request", "conversation", "advice_given", "advice_received", "explanation", "lesson",
    "question", "decision", "commitment", "recommendation", "idea", "presenting", "writing",
    "drawing", "whiteboard", "typing", "making", "walking_meeting", "demonstration", "kept",
    "handshake",
]
MOMENT_KINDS: tuple[str, ...] = MomentKind.__args__  # type: ignore[attr-defined]
CREATIVE_KINDS = ("writing", "drawing", "whiteboard", "making")
# Moments the wearer may share as a post. A shared "advice_received" shows what to do and why in
# tacit's words, never the giver's own words or name (they may not be on tacit); a matched
# giver (a pass) is credited by first name.
POSTABLE_KINDS = ("recommendation", "lesson", "idea", "advice_received")


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def first_name(name: str) -> str:
    return name.strip().split()[0] if name.strip() else ""


class User(BaseModel):
    id: str = Field(default_factory=new_id)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    phone: Phone
    headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)] | None = None
    links: Annotated[list[HttpUrl], Field(max_length=5)] = []
    consent_lookup: bool
    consent_call: bool
    portrait: list[str] | None = None
    portrait_source: Literal["words", "photo"] | None = None
    portrait_colors: dict[str, str] | None = None   # {hair, skin, clothes} as #rrggbb
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    expertise: list[str] = []          # up to 5 short chips, chosen by the person
    worth_knowing: list[str] = []      # up to 5 short chips, chosen by the person
    kinds_off: list[str] = []          # scenario kinds the wearer switched off (§13.3)
    share_creative: bool = False       # "share creative sessions" (§13.5), off by default
    created_at: datetime = Field(default_factory=now)


class ContextItem(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    kind: ContextKind
    text: Annotated[str, StringConstraints(max_length=200)]
    source_url: str
    status: Literal["pending", "kept", "removed"] = "pending"


class Skill(BaseModel):
    id: str = Field(default_factory=new_id)
    owner_id: str
    title: Annotated[str, StringConstraints(max_length=80)]
    verdict: Annotated[str, StringConstraints(max_length=280)]
    reason: Annotated[str, StringConstraints(max_length=280)]
    quote: Annotated[str, StringConstraints(max_length=200)] | None = None
    source: Literal["interview", "conversation"] = "interview"
    status: Literal["draft", "published", "removed"] = "draft"
    visibility: Literal["public", "followers"] = "public"
    jev_specific: float | None = None
    jev_own: float | None = None
    call_id: str | None = None
    moment_id: str | None = None
    created_at: datetime = Field(default_factory=now)


class Follow(BaseModel):
    follower_id: str
    expert_id: str
    paid: bool = False
    stripe_session_id: str | None = None
    created_at: datetime = Field(default_factory=now)


class Call(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    vapi_call_id: str | None = None
    direction: Literal["outbound", "inbound"]
    status: CallStatus = "queued"
    ended_reason: str | None = None
    created_at: datetime = Field(default_factory=now)


class BridgeDevice(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    band: int
    token_sha256: str
    muted: bool = False
    last_state: dict[str, Any] = {}
    last_seen: datetime | None = None


class Segment(BaseModel):
    id: str = Field(default_factory=new_id)
    device_id: str
    user_id: str
    started_at: datetime
    ended_at: datetime
    speaker: int | None = None
    text: str
    level: float | None = None    # median rms_db; LOWER is louder
    windowed: bool = False


class Moment(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    kind: MomentKind
    started_at: datetime
    ended_at: datetime
    title: str = ""
    body: dict[str, Any] = {}
    confidence: float = 0.0
    source: Literal["audio", "motion", "both"] = "audio"
    status: Literal["new", "kept", "dismissed", "shared"] = "new"
    skill_id: str | None = None
    segment_ids: list[str] = []


class Pass(BaseModel):
    id: str = Field(default_factory=new_id)
    giver_id: str
    receiver_id: str
    skill_id: str
    receiver_moment_id: str | None = None
    created_at: datetime = Field(default_factory=now)


# ---- API output models -------------------------------------------------------------------


class ContextItemOut(BaseModel):
    id: str
    kind: str
    text: str
    source_url: str
    status: str


class CallOut(BaseModel):
    id: str
    direction: str
    status: str
    ended_reason: str | None
    created_at: datetime


class SkillOut(BaseModel):
    id: str
    title: str
    verdict: str | None
    reason: str | None
    quote: str | None
    source: str
    status: str
    visibility: str
    jev_specific: float | None = None
    jev_own: float | None = None
    locked: bool = False
    created_at: datetime

    @classmethod
    def of(cls, s: Skill, *, locked: bool = False, owner: bool = False) -> "SkillOut":
        return cls(
            id=s.id, title=s.title, source=s.source, status=s.status, visibility=s.visibility,
            verdict=None if locked else s.verdict, reason=None if locked else s.reason,
            quote=None if locked else s.quote, locked=locked, created_at=s.created_at,
            jev_specific=s.jev_specific if owner else None,
            jev_own=s.jev_own if owner else None,
        )


class MeOut(BaseModel):
    id: str
    name: str
    phone: str
    headline: str | None
    links: list[str]
    consent_lookup: bool
    consent_call: bool
    portrait: list[str] | None
    portrait_source: str | None
    portrait_colors: dict[str, str] | None = None
    location: str | None = None
    company: str | None = None
    expertise: list[str] = []
    worth_knowing: list[str] = []
    kinds_off: list[str]
    share_creative: bool
    context: list[ContextItemOut]
    calls: list[CallOut]
    counts: dict[str, int]


class PersonOut(BaseModel):
    id: str
    first_name: str
    headline: str | None
    skill_count: int
    follower_count: int
    portrait: list[str] | None = None
    portrait_colors: dict[str, str] | None = None
    following: bool = False
    paid: bool = False
    handle: str = ""
    location: str | None = None
    company: str | None = None
    expertise: list[str] = []
    worth_knowing: list[str] = []
    post_count: int = 0
    recommendation_count: int = 0
    met_at: datetime | None = None       # when the viewer shook hands with them, if they did


class PersonDetailOut(PersonOut):
    skills: list[SkillOut]
    recommends: list[str] = []         # things they shared as worth it


class MomentOut(BaseModel):
    id: str
    kind: str
    started_at: datetime
    ended_at: datetime
    title: str
    body: dict[str, Any]
    confidence: float
    source: str
    status: str
    skill_id: str | None


class FeedItemOut(BaseModel):
    type: Literal["skill", "pass", "creative", "post", "picked_up", "connected", "heard"]
    id: str
    at: datetime
    person: dict[str, Any] | None = None       # {id, first_name}
    skill: SkillOut | None = None
    giver: dict[str, Any] | None = None
    receiver: dict[str, Any] | None = None
    lit: bool = False
    kind: str | None = None
    minutes: int | None = None
    title: str | None = None
    body: dict[str, Any] | None = None
    only_you: bool = False


def cut(text: object, limit: int) -> str | None:
    """Trim incoming text to a limit (collapsing whitespace) rather than rejecting it."""
    if text is None:
        return None
    s = " ".join(str(text).split())
    return s[:limit] if s else None
