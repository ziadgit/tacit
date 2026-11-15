import asyncio
from types import SimpleNamespace

from tacit.domain import Skill
from tacit.judge import QUESTIONS, check
from tacit.testing import make_settings


class FakeJev:
    def __init__(self, specific=0.8, own=0.3, exc=None, delay=0.0):
        self.calls = []
        self.p = {"specific": specific, "own": own}
        self.exc, self.delay = exc, delay

    async def system_one(self, *, state, questions):
        self.calls.append((state, questions))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return SimpleNamespace(nouls={k: SimpleNamespace(noul=v) for k, v in self.p.items()})


SKILL = Skill(owner_id="u", title="Open an update with the number", verdict="Lead with it",
              reason="People stop reading", quote="I always put the number first")


async def test_check_returns_scores_and_state():
    jev = FakeJev()
    assert await check(SKILL, jev, make_settings()) == (0.8, 0.3)
    (state, questions), = jev.calls
    assert questions is QUESTIONS and set(questions) == {"specific", "own"}
    assert state == {"skill": {"title": "Open an update with the number",
                               "verdict": "Lead with it", "reason": "People stop reading"},
                     "quote": "I always put the number first"}


async def test_no_quote_is_none_text():
    jev = FakeJev()
    await check({"title": "t", "verdict": "v", "reason": "r", "quote": None}, jev,
                make_settings())
    assert jev.calls[0][0]["quote"] == "none"


async def test_failures_give_none():
    s = make_settings(jev_timeout_s=0.0)
    assert await check(SKILL, None, s) == (None, None)
    assert await check(SKILL, FakeJev(exc=RuntimeError("x")), s) == (None, None)
    assert await check(SKILL, FakeJev(delay=2), s) == (None, None)
