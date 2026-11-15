"""Jev check on a skill (SPEC §8). Scores are shown to the owner; code never acts on them."""

import asyncio
import logging
from typing import Any

from typesafe_sdk import Noul, NoulCriteria

from .config import Settings, require

log = logging.getLogger("tacit.judge")

QUESTIONS = {
    "specific": Noul(
        instructions="Is `skill` a specific, usable piece of know-how: a clear verdict about what "
                     "to do in a kind of situation, with a reason, rather than generic advice "
                     "anyone would give?",
        criteria=NoulCriteria(true="Specific: someone could act on it and it says why.",
                              false="Generic, vague, or missing what to do or why.")),
    "own": Noul(
        instructions="Does `quote` show that the speaker themselves practises `skill`, in their "
                     "own words, rather than repeating someone else's advice or the interviewer's "
                     "words?",
        criteria=NoulCriteria(true="Their own practice, in their words.",
                              false="Not clearly theirs, or there is no quote.")),
}


def make_jev(settings: Settings) -> Any:
    """The production Jev client (no retries, explicit timeout), or None without a key."""
    if settings.typesafe_api_key is None:
        return None
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

    return AsyncTypeSafeClient(
        api_key=require(settings.typesafe_api_key, "TYPESAFE_API_KEY"),
        model=settings.jev_model,
        retry=RetryPolicy(max_retries=0),
        timeout=settings.jev_timeout_s,
    )


def _state(skill: Any) -> dict[str, Any]:
    get = skill.get if isinstance(skill, dict) else lambda k: getattr(skill, k, None)
    return {
        "skill": {"title": get("title"), "verdict": get("verdict"), "reason": get("reason")},
        "quote": get("quote") or "none",
    }


async def check(skill: Any, jev: Any, settings: Settings) -> tuple[float | None, float | None]:
    """(specific, own) probabilities, or (None, None) when Jev is missing, fails or is slow."""
    if jev is None:
        return None, None
    try:
        async with asyncio.timeout(settings.jev_timeout_s + 1):
            resp = await jev.system_one(state=_state(skill), questions=QUESTIONS)
        return float(resp.nouls["specific"].noul), float(resp.nouls["own"].noul)
    except Exception as e:  # noqa: BLE001 - never invent a verdict; never echo the message
        log.warning("jev check failed: %s", type(e).__name__)
        return None, None
