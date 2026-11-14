"""Moments, skills from conversations, and passes (SPEC §13.5).

- `advice_given`, `explanation`, `lesson`, `demonstration` with the wearer as the giver → a
  draft Skill (`source="conversation"`), checked by Jev as in §8, linked to the moment. It
  reaches followers only after the owner publishes it.
- Passes: two linked devices whose `conversation` moments overlap by ≥ 60 s were in the same
  conversation. An `advice_given` on one and an `advice_received` on the other within ±2 min
  (or title Jaccard ≥ 0.4) make a Pass. This happens only here, on the server.
- `GET /api/moments`, `PATCH /api/moments/{id}` for the wearer's private timeline.
"""

import logging
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import judge
from .auth import current_user, get_store
from .config import Settings
from .domain import POSTABLE_KINDS, BridgeDevice, Moment, MomentOut, Pass, Skill, User, cut
from .scenarios import jaccard
from .store import Store

log = logging.getLogger("tacit.moments")
router = APIRouter()

SKILL_KINDS = ("advice_given", "explanation", "lesson", "demonstration")
OVERLAP_MIN = timedelta(seconds=60)
PASS_WITHIN = timedelta(minutes=2)
PASS_JACCARD = 0.4
MOMENTS_MAX = 300


def _overlap(a: Moment, b: Moment) -> timedelta:
    return min(a.ended_at, b.ended_at) - max(a.started_at, b.started_at)


def same_conversation(store: Store, user_a: str, user_b: str, at: Moment) -> bool:
    """Do both wearers have conversation moments that overlap by ≥ 60 s around `at`?"""
    since = at.started_at - timedelta(hours=1)
    mine = [m for m in store.moments_for(user_a, since=since, kind="conversation")
            if m.started_at - PASS_WITHIN <= at.ended_at
            and m.ended_at + PASS_WITHIN >= at.started_at]
    theirs = store.moments_for(user_b, since=since, kind="conversation")
    return any(_overlap(a, b) >= OVERLAP_MIN for a in mine for b in theirs)


def _close(a: Moment, b: Moment) -> bool:
    near = abs(a.started_at - b.started_at) <= PASS_WITHIN or \
        abs(a.ended_at - b.ended_at) <= PASS_WITHIN
    return near or jaccard(a.title, b.title) >= PASS_JACCARD


def find_passes(store: Store, m: Moment) -> list[Pass]:
    """Make the passes this new advice moment completes, with the other linked devices."""
    if m.kind not in ("advice_given", "advice_received"):
        return []
    made: list[Pass] = []
    others = {d.user_id for d in store.all_devices() if d.user_id != m.user_id}
    for other in others:
        if not same_conversation(store, m.user_id, other, m):
            continue
        want = "advice_received" if m.kind == "advice_given" else "advice_given"
        since = m.started_at - timedelta(hours=1)
        for o in store.moments_for(other, since=since, kind=want):
            if not _close(m, o):
                continue
            giver_m, recv_m = (m, o) if m.kind == "advice_given" else (o, m)
            if not giver_m.skill_id:
                continue
            done = store.passes_for_skill(giver_m.skill_id)
            if any(p.receiver_id == recv_m.user_id for p in done):
                continue
            p = store.add_pass(Pass(giver_id=giver_m.user_id, receiver_id=recv_m.user_id,
                                    skill_id=giver_m.skill_id, receiver_moment_id=recv_m.id))
            made.append(p)
            log.info("pass made")
    return made


def skill_from(m: Moment) -> Skill | None:
    b = m.body or {}
    if b.get("giver") not in ("wearer", "both", None) or not b.get("title"):
        return None
    verdict = b.get("verdict") or ""
    steps = [s for s in b.get("steps") or [] if s]
    if m.kind in ("explanation", "demonstration") and steps:
        # the verdict holds the steps
        verdict = "; ".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    if not verdict or not b.get("reason"):
        return None
    return Skill(owner_id=m.user_id, title=cut(b["title"], 80) or "",
                 verdict=cut(verdict, 280) or "",
                 reason=cut(b["reason"], 280) or "", quote=cut(b.get("quote"), 200),
                 source="conversation", moment_id=m.id)


class MomentHooks:
    """Registered on the scenario pipeline: skills from the wearer's advice, then passes."""

    def __init__(self, store: Store, settings: Settings, jev: Any = None):
        self.store, self.settings, self.jev = store, settings, jev

    async def __call__(self, dev: BridgeDevice, m: Moment, extracted: dict[str, Any]) -> None:
        if m.kind in SKILL_KINDS and not m.skill_id:
            skill = skill_from(m)
            if skill is not None:
                specific, own = await judge.check(skill, self.jev, self.settings)
                skill.jev_specific, skill.jev_own = specific, own
                skill = self.store.add_skill(skill)
                m = self.store.update_moment(m.id, skill_id=skill.id)
                log.info("draft skill from a conversation")
        find_passes(self.store, m)


# ---- API --------------------------------------------------------------------------------------


class MomentPatch(BaseModel):
    status: Literal["kept", "dismissed", "shared"]


def moment_out(m: Moment) -> MomentOut:
    return MomentOut(**m.model_dump(include=set(MomentOut.model_fields)))


@router.get("/api/moments")
def list_moments(user: Annotated[User, Depends(current_user)],
                 store: Annotated[Store, Depends(get_store)]) -> list[MomentOut]:
    ms = store.moments_for(user.id)[:MOMENTS_MAX]
    # newest first; within the same hour a demonstration is ranked first
    ms.sort(key=lambda m: (m.started_at.replace(minute=0, second=0, microsecond=0),
                           m.kind == "demonstration", m.started_at), reverse=True)
    return [moment_out(m) for m in ms]


@router.patch("/api/moments/{moment_id}")
def patch_moment(moment_id: str, body: MomentPatch, user: Annotated[User, Depends(current_user)],
                 store: Annotated[Store, Depends(get_store)]) -> MomentOut:
    m = store.get_moment(moment_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "no such moment")
    if body.status == "shared" and m.kind not in POSTABLE_KINDS:
        raise HTTPException(422, "only a recommendation, lesson or idea can be shared")
    log.info("moment status: %s", body.status)
    return moment_out(store.update_moment(m.id, status=body.status))
