"""Text detectors on the server (SPEC §13.4): segments → windows → Jev → extraction → moments.

- A window is up to 3 minutes of a device's transcript segments with 30 s of overlap. One runs
  after 90 s of new speech, after 20 s of silence, and at once on "keep that" (forced). At most
  `windows_per_hour` per wearer.
- The likely wearer is the speaker with the lowest median level (lower rms_db is louder) by at
  least 6 dB; otherwise the wearer is unknown and Jev decides.
- Step 1: one Jev `system_one` per window: a Noul per kind and a Choice `giver`. A probability
  ≥ `scenario_threshold` moves that kind on. No Jev → no detections (never guess).
- Step 2: extraction with `llm.py` (one strict JSON schema per kind). A quote is kept only if it
  is in the window's words. Same kind + title Jaccard ≥ 0.6 within 30 min → merged.
- `stop_request` → the device's mute command is set and the last 60 s are rewound.
- Segments are deleted after 24 h (and at once on rewind).
"""

import asyncio
import logging
import re
import statistics
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from typesafe_sdk import Choice, Noul, NoulCriteria

from .bridge_api import rewind, set_mute_command
from .config import Settings
from .domain import BridgeDevice, Moment, Segment, cut, first_name, now
from .store import Store

log = logging.getLogger("tacit.scenarios")

WINDOW_MAX = timedelta(minutes=3)
OVERLAP = timedelta(seconds=30)
NEW_SPEECH = timedelta(seconds=90)
SILENCE = timedelta(seconds=20)
WEARER_DB = 6.0
CONVERSATION_GAP = timedelta(minutes=2)
DEDUP_JACCARD = 0.6
DEDUP_WITHIN = timedelta(minutes=30)
RETENTION = timedelta(hours=24)
STOP_REWIND_S = 60

JEV_KINDS = {
    "advice": ("Does `window` contain advice: someone telling another person what to do in some "
               "kind of situation, from their own experience?",
               "Someone gives advice.", "Nobody gives advice."),
    "explanation": ("Does `window` contain an explanation of how to do something, with steps?",
                    "Someone explains how to do something.", "No how-to explanation."),
    "lesson": ("Does `window` contain a lesson learned from experience, like \"the mistake we "
               "made was...\"?", "Someone says what they learned.", "No lesson learned."),
    "question": ("Does the wearer (`wearer`) ask someone for advice or for how to do something?",
                 "The wearer asks for advice.", "The wearer asks for no advice."),
    "decision": ("Does `window` contain a decision being made, like \"let's go with X\"?",
                 "A decision is made.", "No decision."),
    "commitment": ("Does someone commit to doing something, like \"I'll send it tomorrow\"?",
                   "Someone commits to an action.", "No commitment."),
    "recommendation": ("Does someone recommend a book, tool, person or place as worth it?",
                       "Something is recommended.", "Nothing is recommended."),
    "idea": ("Does someone say a new idea out loud?", "A new idea is said.", "No new idea."),
    "stop_request": ("Does anyone in `window` ask for the recording to stop, or say they don't "
                     "want to be recorded?", "Someone asks to stop recording.",
                     "Nobody asks to stop recording."),
}


def jev_questions() -> dict[str, Any]:
    q: dict[str, Any] = {
        k: Noul(instructions=ins, criteria=NoulCriteria(true=t, false=f))
        for k, (ins, t, f) in JEV_KINDS.items()
    }
    q["giver"] = Choice(
        instructions="In `window`, who gives the advice or explanation? `wearer` names the "
                     "wearer's speaker label, or says it is unknown.",
        criteria={"wearer": "The wearer gives it.", "other": "Someone else gives it to the wearer.",
                  "both": "Both give some.", "none": "Nobody gives advice or an explanation."})
    return q


QUESTIONS = jev_questions()

_SKILL = {"type": "object", "additionalProperties": False,
          "required": ["title", "verdict", "reason", "quote", "giver", "steps"],
          "properties": {
              "title": {"type": "string"}, "verdict": {"type": "string"},
              "reason": {"type": "string"}, "quote": {"type": ["string", "null"]},
              "giver": {"type": "string", "enum": ["wearer", "other", "both", "none"]},
              "steps": {"type": "array", "items": {"type": "string"}}}}


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


_S, _N = {"type": "string"}, {"type": ["string", "null"]}
SCHEMAS: dict[str, dict[str, Any]] = {
    "advice": _SKILL, "explanation": _SKILL, "lesson": _SKILL, "demonstration": _SKILL,
    "commitment": _obj(what=_S, who=_N, when_text=_N),
    "decision": _obj(what=_S, why=_N),
    "recommendation": _obj(thing=_S, kind=_S, why=_N),
    "question": _obj(question=_S, topic=_S),
    "idea": _obj(idea=_S),
}
INSTRUCTIONS = (
    "You read a transcript window from a wristband. Lines start with a speaker label; one may be "
    "marked (likely wearer). Fill in the fields only from what was said. The title is a short "
    "imperative phrase. `quote` must be words copied exactly from one line, or null. Never "
    "invent anything; never include names of people who are not speaking.")


# ---- pure helpers -----------------------------------------------------------------------------


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


STOPWORDS = frozenset("a an the and or of to in on for with how do i you we it is my your what "
                      "when why who can should".split())


def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def wearer_speaker(segments: list[Segment]) -> int | None:
    """The speaker with the lowest median level (louder), by at least 6 dB over every other."""
    levels: dict[int, list[float]] = {}
    for s in segments:
        if s.speaker is not None and s.level is not None:
            levels.setdefault(s.speaker, []).append(s.level)
    if len(levels) < 2:
        return None
    med = sorted((statistics.median(v), k) for k, v in levels.items())
    return med[0][1] if med[1][0] - med[0][0] >= WEARER_DB else None


def window_lines(segments: list[Segment], wearer: int | None) -> str:
    out = []
    for s in segments:
        label = f"S{s.speaker}" if s.speaker is not None else "S?"
        if wearer is not None and s.speaker == wearer:
            label += " (likely wearer)"
        out.append(f"{label}: {s.text}")
    return "\n".join(out)


def quote_ok(quote: Any, segments: list[Segment]) -> str | None:
    """Keep a quote only if it appears in the window's words (case and spaces normalised)."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    q = norm(quote).strip(" \"'“”.")
    words = norm(" ".join(s.text for s in segments))
    return cut(quote.strip().strip("\"“”"), 200) if q and q in words else None


def speakers_within(segments: list[Segment], gap: timedelta = CONVERSATION_GAP) -> bool:
    """≥ 2 diarized speakers within 2 minutes of each other."""
    seen: list[tuple[datetime, int]] = [(s.ended_at, s.speaker) for s in segments
                                        if s.speaker is not None]
    for i, (t, spk) in enumerate(seen):
        for t2, spk2 in seen[i + 1:]:
            if spk2 != spk and abs(t2 - t) <= gap:
                return True
    return False


# ---- the pipeline -----------------------------------------------------------------------------

MomentHook = Callable[[BridgeDevice, Moment, dict[str, Any]], Awaitable[None]]


class Scenarios:
    def __init__(self, store: Store, settings: Settings, jev: Any = None, llm: Any = None,
                 clock: Callable[[], datetime] = now):
        self.store = store
        self.settings = settings
        self.jev = jev
        self.llm = llm
        self.clock = clock
        self.hooks: list[MomentHook] = []   # moments → skills and passes (§13.5)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, dev: BridgeDevice) -> asyncio.Lock:
        return self._locks.setdefault(dev.id, asyncio.Lock())

    # entry points (run as background tasks after the bridge's request)

    async def on_segments(self, dev: BridgeDevice) -> None:
        await self.maybe_run(dev)

    async def tick(self, dev: BridgeDevice) -> None:
        self.store.delete_segments_before(self.clock() - RETENTION)
        await self.maybe_run(dev)

    async def on_kept(self, dev: BridgeDevice, kept: Moment) -> None:
        async with self._lock(dev):
            segs = [s for s in self.store.segments(dev.id, since=kept.started_at)
                    if s.started_at <= kept.ended_at]
            found = await self.run_window(dev, segs, forced=True) if segs else []
            self.store.update_moment(kept.id, segment_ids=[s.id for s in segs],
                                     body={**kept.body, "found": [m.kind for m in found]})

    async def maybe_run(self, dev: BridgeDevice) -> list[Moment]:
        async with self._lock(dev):
            segs = self.due(dev)
            return await self.run_window(dev, segs) if segs else []

    def due(self, dev: BridgeDevice) -> list[Segment] | None:
        """The window to run now, or None: 90 s of new speech, or 20 s of silence after some."""
        all_segs = self.store.segments(dev.id)
        new = [s for s in all_segs if not s.windowed]
        if not new:
            return None
        first = new[0].started_at
        span = new[-1].ended_at - first
        if span < NEW_SPEECH and self.clock() - new[-1].ended_at < SILENCE:
            return None
        window = [s for s in new if s.ended_at - first <= WINDOW_MAX] or new[:1]
        overlap = [s for s in all_segs if s.windowed and first - OVERLAP <= s.ended_at <= first]
        return overlap + window

    async def classify(self, lines: str, wearer: int | None) -> dict[str, Any] | None:
        if self.jev is None:
            return None
        state = {"window": lines, "wearer": f"S{wearer}" if wearer is not None else "unknown"}
        try:
            async with asyncio.timeout(self.settings.jev_timeout_s + 1):
                resp = await self.jev.system_one(state=state, questions=QUESTIONS)
            probs = {k: float(resp.nouls[k].noul) for k in JEV_KINDS}
            giver = str(resp.choices["giver"].choice)
        except Exception as e:  # noqa: BLE001 - Jev unavailable → no detections, never a guess
            log.warning("jev classify failed: %s", type(e).__name__)
            return None
        return {"probs": probs, "giver": giver}

    async def extract(self, kind: str, lines: str) -> dict[str, Any] | None:
        if self.llm is None:
            return None
        try:
            return await self.llm.extract(lines, name=kind, schema=SCHEMAS[kind],
                                          instructions=INSTRUCTIONS)
        except Exception as e:  # noqa: BLE001
            log.warning("extract %s failed: %s", kind, type(e).__name__)
            return None

    async def run_window(self, dev: BridgeDevice, segs: list[Segment],
                         forced: bool = False) -> list[Moment]:
        user = self.store.get_user(dev.user_id)
        if user is None:
            return []
        for s in segs:
            if not s.windowed:
                self.store.update("segments", s.id, windowed=True)
        if not forced and not self.store.allow(user.id, "window", self.settings.windows_per_hour,
                                               per=timedelta(hours=1)):
            log.info("window cap reached")
            return []
        off = set(user.kinds_off)
        out: list[Moment] = []
        start, end = segs[0].started_at, max(s.ended_at for s in segs)
        ids = [s.id for s in segs]
        if "conversation" not in off and speakers_within(segs):
            out.append(self._conversation(user.id, start, end, ids))

        wearer = wearer_speaker(segs)
        lines = window_lines(segs, wearer)
        verdict = await self.classify(lines, wearer)
        if verdict is None:
            log.info("window: no Jev, no detections")
            return out
        probs, giver = verdict["probs"], verdict["giver"]
        thr = self.settings.scenario_threshold
        if probs.get("stop_request", 0) >= thr and "stop_request" not in off:
            set_mute_command(self.store, dev, True)
            rewind(self.store, dev, STOP_REWIND_S)
            log.info("window: stop request → mute")
            return []
        creative = self._creative_overlap(user.id, start, end)
        for kind in JEV_KINDS:
            if kind == "stop_request" or probs.get(kind, 0) < thr:
                continue
            for moment_kind, extracted in await self._moments_for(kind, lines, giver, creative):
                if moment_kind in off:
                    continue
                m = self._build(user.id, moment_kind, extracted, probs[kind], start, end, ids, segs)
                m = self._dedup_or_add(m)
                out.append(m)
                for hook in self.hooks:
                    await hook(dev, m, extracted or {})
        log.info("window: %d moments", len(out))
        return out

    async def _moments_for(self, kind: str, lines: str, giver: str, creative: bool
                           ) -> list[tuple[str, dict[str, Any] | None]]:
        if kind in ("advice", "explanation", "lesson"):
            ex_kind = "demonstration" if kind == "explanation" and creative else kind
            extracted = await self.extract(ex_kind, lines)
            who = (extracted or {}).get("giver") if giver == "none" else giver
            if kind == "advice":
                kinds = {"wearer": ["advice_given"], "other": ["advice_received"],
                         "both": ["advice_given", "advice_received"]}.get(who or "", [])
                return [(k, extracted) for k in kinds]
            return [(ex_kind, {**(extracted or {}), "giver": who})]
        return [(kind, await self.extract(kind, lines))]

    def _creative_overlap(self, user_id: str, start: datetime, end: datetime) -> bool:
        return any(m.kind in ("drawing", "whiteboard", "making") and m.started_at <= end
                   and m.ended_at >= start
                   for m in self.store.moments_for(user_id, since=start - timedelta(hours=1)))

    def _conversation(self, user_id: str, start: datetime, end: datetime,
                      ids: list[str]) -> Moment:
        for m in self.store.moments_for(user_id, since=start - CONVERSATION_GAP,
                                        kind="conversation"):
            if m.ended_at >= start - CONVERSATION_GAP:
                return self.store.update_moment(
                    m.id, started_at=min(m.started_at, start), ended_at=max(m.ended_at, end),
                    segment_ids=sorted(set(m.segment_ids) | set(ids)))
        return self.store.add_moment(Moment(user_id=user_id, kind="conversation", started_at=start,
                                            ended_at=end, title="a conversation",
                                            confidence=1.0, segment_ids=ids))

    def _build(self, user_id: str, kind: str, ex: dict[str, Any] | None, p: float,
               start: datetime, end: datetime, ids: list[str], segs: list[Segment]) -> Moment:
        ex = ex or {}
        body: dict[str, Any] = {}
        if kind in ("advice_given", "advice_received", "explanation", "lesson", "demonstration"):
            body = {"title": cut(ex.get("title"), 80), "verdict": cut(ex.get("verdict"), 280),
                    "reason": cut(ex.get("reason"), 280),
                    "steps": [cut(s, 200) for s in ex.get("steps") or [] if cut(s, 200)][:10],
                    "giver": ex.get("giver")}
            # a bystander's exact words are never kept (§13.5, §15)
            body["quote"] = None if kind == "advice_received" else quote_ok(ex.get("quote"), segs)
            if kind == "demonstration":
                body["ranked_first"] = True
            title = body["title"] or kind.replace("_", " ")
        elif kind == "commitment":
            body = {"what": cut(ex.get("what"), 280), "who": cut(ex.get("who"), 80),
                    "when_text": cut(ex.get("when_text"), 80)}
            title = body["what"] or "a commitment"
        elif kind == "decision":
            body = {"what": cut(ex.get("what"), 280), "why": cut(ex.get("why"), 280)}
            title = body["what"] or "a decision"
        elif kind == "recommendation":
            body = {"thing": cut(ex.get("thing"), 120), "kind": cut(ex.get("kind"), 40),
                    "why": cut(ex.get("why"), 280)}
            title = body["thing"] or "a recommendation"
        elif kind == "question":
            body = {"question": cut(ex.get("question"), 280), "topic": cut(ex.get("topic"), 80)}
            body["matches"] = self._matches(user_id, body["topic"] or body["question"] or "")
            title = body["question"] or "a question"
        elif kind == "idea":
            body = {"idea": cut(ex.get("idea"), 280)}
            title = body["idea"] or "an idea"
        else:
            title = kind.replace("_", " ")
        return Moment(user_id=user_id, kind=kind, started_at=start, ended_at=end,
                      title=cut(title, 120) or kind, body=body, confidence=round(p, 3),
                      source="audio", segment_ids=ids)

    def _matches(self, user_id: str, topic: str) -> list[dict[str, Any]]:
        """People the wearer follows with a published skill on this topic (first names only)."""
        want = tokens(topic) - STOPWORDS
        out: list[dict[str, Any]] = []
        if not want:
            return out
        for f in self.store.following(user_id):
            expert = self.store.get_user(f.expert_id)
            if expert is None:
                continue
            for s in self.store.published_skills(expert.id):
                have = tokens(f"{s.title} {s.verdict}")
                if len(want & have) / len(want) >= 0.5:
                    out.append({"person_id": expert.id, "first_name": first_name(expert.name),
                                "skill_id": s.id, "title": s.title})
                    break
        return out[:5]

    def _dedup_or_add(self, m: Moment) -> Moment:
        for old in self.store.moments_for(m.user_id, since=m.started_at - DEDUP_WITHIN,
                                          kind=m.kind):
            if (old.id != m.id and m.started_at - old.ended_at <= DEDUP_WITHIN
                    and jaccard(old.title, m.title) >= DEDUP_JACCARD):
                body = {**m.body, **{k: v for k, v in old.body.items() if v}}
                return self.store.update_moment(
                    old.id, ended_at=max(old.ended_at, m.ended_at),
                    confidence=max(old.confidence, m.confidence), body=body,
                    segment_ids=sorted(set(old.segment_ids) | set(m.segment_ids)))
        return self.store.add_moment(m)

