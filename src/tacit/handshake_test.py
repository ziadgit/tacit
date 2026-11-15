import importlib.util
import math
import random
from pathlib import Path

from tacit import handshake as hs

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_gesture_templates", ROOT / "scripts" / "make_gesture_templates.py")
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)


def signal(parts, rate=100, seed=1):
    """parts: [(seconds, fn(s) -> dict of deltas)], played one after another, with noise."""
    rnd = random.Random(seed)
    out, t = [], 0.0
    for seconds, fn in parts:
        for i in range(int(seconds * rate)):
            d = dict(ax=0.0, ay=0.0, az=1.0)
            d.update(fn(i / rate))
            for k in ("ax", "ay", "az"):
                d[k] += rnd.gauss(0, 0.01)
            d["t"] = t * 1000
            out.append(d)
            t += 1 / rate
    return out


def still(_s):
    return {}


def shake(s):   # a handshake: ~4 up-and-downs a second, about half a g, for 1.5 s
    return dict(az=1 + 0.6 * math.sin(2 * math.pi * 4 * s))


def count(samples):
    d = hs.ShakeDetector()
    return sum(d.feed(x) for x in samples)


def test_a_handshake_counts_once():
    assert count(signal([(2, still), (1.5, shake), (2, still)])) == 1


def test_two_handshakes_need_the_cooldown():
    assert count(signal([(2, still), (1.5, shake), (0.5, still), (1.5, shake), (2, still)])) == 1
    assert count(signal([(2, still), (1.5, shake), (3, still), (1.5, shake), (2, still)])) == 2


def test_still_hand_swing_and_buzz_are_not_handshakes():
    assert count(signal([(10, still)])) == 0
    swing = lambda s: dict(ax=0.12 * math.sin(math.pi * s), ay=0.12 * math.cos(math.pi * s))  # noqa: E731
    assert count(signal([(10, swing)])) == 0                     # the pretend band's own swing
    buzz = lambda s: dict(az=1 + 0.6 * math.sin(2 * math.pi * 12 * s))  # noqa: E731  (below the 25 Hz grid limit)
    assert count(signal([(2, still), (1.5, buzz), (2, still)])) == 0
    weak = lambda s: dict(az=1 + 0.1 * math.sin(2 * math.pi * 4 * s))  # noqa: E731
    assert count(signal([(2, still), (1.5, weak), (2, still)])) == 0


def test_walking_never_counts():
    walk = lambda s: dict(az=1 + 0.45 * math.sin(2 * math.pi * 2 * s),  # noqa: E731
                          ax=0.2 * math.sin(2 * math.pi * s))
    assert count(signal([(2, still), (30, walk), (2, still)])) == 0


def test_a_drawn_x_can_look_like_a_shake_to_one_band():
    # On one band alone a mute gesture is a short burst that settles, like a handshake.
    # The bridge gives the mute gesture priority (bridge_test: a gesture is never a handshake).
    samples = mk.samples("x", 1.4, 0.4, rate_hz=100)
    lead = [dict(t=i * 10.0, ax=0.0, ay=0.0, az=1.0) for i in range(200)]
    assert count(lead + [{**x, "t": x["t"] + 2000} for x in samples]) <= 1


def test_bad_samples_are_skipped():
    d = hs.ShakeDetector()
    assert d.feed({"t": None, "ax": 0, "ay": 0, "az": 1}) is False
    assert d.feed({"t": 1.0, "ax": float("nan"), "ay": 0, "az": 1}) is False
