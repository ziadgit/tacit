"""Skills and the network API (SPEC §9) and the typed feed (§13.5)."""

import logging
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints

from .auth import current_user, get_store
from .domain import (
    CREATIVE_KINDS,
    POSTABLE_KINDS,
    FeedItemOut,
    PersonDetailOut,
    PersonOut,
    Skill,
    SkillOut,
    User,
    first_name,
    now,
)
from .store import Store

log = logging.getLogger("tacit.network")
FEED_MAX = 50
CREATIVE_MIN_S = 5 * 60
PASS_NEW = timedelta(hours=24)
# Fields of a shared moment's body that never go to the feed: words that might be a bystander's.
PRIVATE_BODY = ("quote", "giver", "who")

CurrentUser = Annotated[User, Depends(current_user)]
StoreDep = Annotated[Store, Depends(get_store)]
router = APIRouter()


class SkillPatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                            max_length=80)] | None = None
    verdict: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                              max_length=280)] | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                             max_length=280)] | None = None
    quote: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    status: Literal["published", "removed"] | None = None
    visibility: Literal["public", "followers"] | None = None


def who(user: User | None) -> dict[str, Any] | None:
    return {"id": user.id, "first_name": first_name(user.name)} if user else None


def can_see_locked(store: Store, viewer: User, owner_id: str) -> bool:
    if viewer.id == owner_id:
        return True
    f = store.get_follow(viewer.id, owner_id)
    return bool(f and f.paid)


def skill_view(store: Store, viewer: User, s: Skill) -> SkillOut:
    locked = s.visibility == "followers" and not can_see_locked(store, viewer, s.owner_id)
    return SkillOut.of(s, locked=locked, owner=viewer.id == s.owner_id)


def person_out(store: Store, viewer: User, u: User, skill_count: int | None = None) -> PersonOut:
    f = store.get_follow(viewer.id, u.id)
    return PersonOut(
        id=u.id, first_name=first_name(u.name), headline=u.headline,
        skill_count=store.count_published(u.id) if skill_count is None else skill_count,
        follower_count=store.follower_count(u.id), portrait=u.portrait,
        following=f is not None, paid=bool(f and f.paid),
    )


@router.get("/api/skills/mine")
def skills_mine(user: CurrentUser, store: StoreDep) -> list[SkillOut]:
    return [SkillOut.of(s, owner=True) for s in store.skills_mine(user.id)]


@router.patch("/api/skills/{skill_id}")
def patch_skill(skill_id: str, body: SkillPatch, user: CurrentUser, store: StoreDep) -> SkillOut:
    s = store.get_skill(skill_id)
    if s is None or s.owner_id != user.id or s.status == "removed":
        raise HTTPException(404, "no such skill")
    fields = body.model_dump(exclude_unset=True)
    for k in ("title", "verdict", "reason", "status", "visibility"):
        if k in fields and fields[k] is None:
            raise HTTPException(422, f"{k} can't be null")
    if "quote" in fields and not fields["quote"]:
        fields["quote"] = None
    updated = store.update_skill(skill_id, **fields) if fields else s
    if "status" in fields:
        log.info("skill status: %s", fields["status"])
    return SkillOut.of(updated, owner=True)


@router.get("/api/people")
def people(user: CurrentUser, store: StoreDep) -> list[PersonOut]:
    return [person_out(store, user, u, n) for u, n in store.people(limit=50)]


@router.get("/api/people/{person_id}")
def person(person_id: str, user: CurrentUser, store: StoreDep) -> PersonDetailOut:
    u = store.get_user(person_id)
    if u is None:
        raise HTTPException(404, "no such person")
    skills = store.published_skills(u.id)
    base = person_out(store, user, u, len(skills))
    return PersonDetailOut(**base.model_dump(),
                           skills=[skill_view(store, user, s) for s in skills])


@router.post("/api/follow/{person_id}")
def follow(person_id: str, user: CurrentUser, store: StoreDep) -> PersonOut:
    if person_id == user.id:
        raise HTTPException(400, "you can't follow yourself")
    u = store.get_user(person_id)
    if u is None:
        raise HTTPException(404, "no such person")
    store.follow(user.id, u.id)
    return person_out(store, user, u)


@router.delete("/api/follow/{person_id}", status_code=204)
def unfollow(person_id: str, user: CurrentUser, store: StoreDep) -> Response:
    store.unfollow(user.id, person_id)
    return Response(status_code=204)


# ---- feed -------------------------------------------------------------------------------


def feed_items(store: Store, viewer: User) -> list[FeedItemOut]:
    followed = {f.expert_id: f for f in store.following(viewer.id)}
    users: dict[str, User | None] = {viewer.id: viewer}

    def user(uid: str) -> User | None:
        if uid not in users:
            users[uid] = store.get_user(uid)
        return users[uid]

    items: list[FeedItemOut] = []
    t = now()
    for eid, f in followed.items():
        expert = user(eid)
        if expert is None:
            continue
        for s in store.published_skills(eid):
            if s.visibility == "followers" and not f.paid:
                continue
            items.append(FeedItemOut(type="skill", id=f"skill:{s.id}", at=s.created_at,
                                     person=who(expert), skill=skill_view(store, viewer, s)))
        for m in store.moments_for(eid):
            if (m.kind in CREATIVE_KINDS and expert.share_creative and m.status != "dismissed"
                    and (m.ended_at - m.started_at).total_seconds() >= CREATIVE_MIN_S):
                minutes = int((m.ended_at - m.started_at).total_seconds() // 60)
                items.append(FeedItemOut(type="creative", id=f"creative:{m.id}", at=m.ended_at,
                                         person=who(expert), kind=m.kind, minutes=minutes))
            elif m.kind in POSTABLE_KINDS and m.status == "shared":
                body = {k: v for k, v in m.body.items() if k not in PRIVATE_BODY}
                items.append(FeedItemOut(type="post", id=f"post:{m.id}", at=m.ended_at,
                                         person=who(expert), kind=m.kind, title=m.title,
                                         body=body))

    seen_passes: set[str] = set()
    pass_sources = [p for uid in [viewer.id, *followed] for p in store.passes_for(uid)]
    for p in pass_sources:
        if p.id in seen_passes:
            continue
        seen_passes.add(p.id)
        s = store.get_skill(p.skill_id)
        giver, receiver = user(p.giver_id), user(p.receiver_id)
        if s is None or s.status != "published" or giver is None or receiver is None:
            continue
        items.append(FeedItemOut(type="pass", id=f"pass:{p.id}", at=p.created_at,
                                 giver=who(giver), receiver=who(receiver),
                                 skill=skill_view(store, viewer, s),
                                 lit=t - p.created_at < PASS_NEW))

    items.extend(picked_up(store, viewer))
    for m in store.moments_for(viewer.id, kind="handshake"):
        pid = m.body.get("person_id")
        other = user(pid) if pid and m.status != "dismissed" else None
        if other is not None:
            items.append(FeedItemOut(type="connected", id=f"connected:{m.id}", at=m.ended_at,
                                     person=who(other), only_you=True))
    items.sort(key=lambda i: i.at, reverse=True)
    return items[:FEED_MAX]


def picked_up(store: Store, viewer: User) -> list[FeedItemOut]:
    """The viewer's own advice_received moments. Credited by name only through a pass."""
    by_moment = {p.receiver_moment_id: p for p in store.passes_for(viewer.id)
                 if p.receiver_id == viewer.id and p.receiver_moment_id}
    out = []
    for m in store.moments_for(viewer.id, kind="advice_received"):
        if m.status == "dismissed":
            continue
        body = {k: m.body.get(k) for k in ("title", "verdict", "reason")}
        giver: dict[str, Any] | None = {"id": None, "first_name": "someone you talked with"}
        p = by_moment.get(m.id)
        s = store.get_skill(p.skill_id) if p else None
        if p and s and s.status == "published":
            g = store.get_user(p.giver_id)
            if g:
                giver = who(g)
                body["quote"] = s.quote   # the giver's own words, from their own skill
        out.append(FeedItemOut(type="picked_up", id=f"picked_up:{m.id}", at=m.ended_at,
                               title=m.title or body.get("title"), body=body, giver=giver,
                               only_you=True))
    return out


@router.get("/api/feed")
def feed(user: CurrentUser, store: StoreDep) -> list[FeedItemOut]:
    return feed_items(store, user)
