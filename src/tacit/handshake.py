"""Handshake: "I am shaking a hand", felt by one band on its own (pure functions, no band).

A port of the single-band half of the team's detector (handshake/handshake-detector.js on the
`handshake-detector` branch): over the last 1.2 s, the size of the acceleration must swing
strongly enough (energy) and a few times (4 to 16 swings: at least two full up-and-downs, and
not a buzz), after a calm second. Each bridge checks its own band; the server pairs two
people whose bands both felt a shake at the same moment (bridge_api.match_handshake).
No motion data leaves the bridge, only the time of the shake.

The numbers are the team's starting values, not yet measured on many real handshakes.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

WINDOW_MS = 1200      # how much of the recent past is looked at
STEP_MS = 20          # the trace is put on this time grid (50 per second)
MIN_ENERGY = 0.2      # g: how strong the shake must be (average swing size)
MIN_SWINGS = 4        # at least two full up-and-downs...
MAX_SWINGS = 16       # ...and not a buzz
COOLDOWN_MS = 3000    # after a shake, wait this long before the next one counts
CHECK_EVERY_MS = 100  # how often the window is looked at
# tacit's addition: a handshake is a burst. The second before it must be calm, so walking,
# running or carrying something (one long rhythm, which one band alone can't tell from a
# handshake) never counts.
CALM_MS = 1000
CALM_GAP_MS = 300     # the calm second may end this long before the window (checks every 0.1 s)
CALM_ENERGY = 0.12    # g
HALF_ENERGY = MIN_ENERGY  # g: each half of the window must be shaking as hard
# ...and a handshake ends: it counts only once the hand is calm again (half a second) within
# 3 s. Walking or carrying something goes on, so it never does.
SETTLE_MS = 500
SETTLE_WITHIN_MS = 3000
KEEP_MS = 4000


@dataclass(frozen=True)
class Shape:
    energy: float
    swings: int


def describe(values: list[float]) -> Shape:
    """The swings of a stretch of |a| around its average: how strong, how many."""
    mean = sum(values) / len(values)
    swing = [v - mean for v in values]
    energy = math.sqrt(sum(v * v for v in swing) / len(swing))
    band = max(0.08, energy * 0.5)   # ignore small wobbles around the middle
    swings, side = 0, 0
    for v in swing:
        if v > band and side != 1:
            if side == -1:
                swings += 1
            side = 1
        elif v < -band and side != -1:
            if side == 1:
                swings += 1
            side = -1
    return Shape(energy, swings)


def shaking(shape: Shape) -> bool:
    return shape.energy >= MIN_ENERGY and MIN_SWINGS <= shape.swings <= MAX_SWINGS


def _num(sample: Any, key: str) -> float | None:
    v = sample.get(key) if isinstance(sample, dict) else getattr(sample, key, None)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    return float(v)


class ShakeDetector:
    """Feed it every motion sample (band time `t` in ms); `feed` says True once per handshake,
    at the moment the hand settles after it."""

    def __init__(self) -> None:
        self.samples: deque[tuple[float, float]] = deque()
        self.last_shake = -math.inf
        self.last_check = -math.inf
        self.candidate: float | None = None   # band time a shake was seen, waiting to settle

    def reset(self) -> None:
        self.samples.clear()

    def feed(self, sample: Any) -> bool:
        t = _num(sample, "t")
        ax, ay, az = (_num(sample, k) for k in ("ax", "ay", "az"))
        if t is None or ax is None or ay is None or az is None:
            return False
        if self.samples and t <= self.samples[-1][0]:
            if t < self.samples[-1][0] - 1000:   # the band restarted: start over
                self.reset()
            else:
                t = self.samples[-1][0] + 1
        self.samples.append((t, math.sqrt(ax * ax + ay * ay + az * az)))
        while self.samples and self.samples[0][0] < t - KEEP_MS:
            self.samples.popleft()
        if t - self.last_check < CHECK_EVERY_MS or t - self.last_shake < COOLDOWN_MS:
            return False
        self.last_check = t
        if self.candidate is not None:
            settle = self._resample(t - SETTLE_MS, t)
            if settle is not None and describe(settle).energy <= CALM_ENERGY:
                self.candidate = None
                self.last_shake = t
                return True                    # shook, then let go: a handshake
            if t - self.candidate > SETTLE_WITHIN_MS:
                self.candidate = None          # it went on: walking, carrying, not a handshake
            return False
        values = self._resample(t - WINDOW_MS, t)
        if values is None or not shaking(describe(values)):
            return False
        # the whole window shakes (not just the start of some bigger motion)...
        half = len(values) // 2
        if min(describe(values[:half]).energy, describe(values[half:]).energy) < HALF_ENERGY:
            return False
        # ...and it came out of a calm second
        start = t - WINDOW_MS - CALM_GAP_MS
        before = self._resample(start - CALM_MS, start)
        if before is None or describe(before).energy > CALM_ENERGY:
            return False
        self.candidate = t
        return False

    def _resample(self, start: float, end: float) -> list[float] | None:
        s = self.samples
        if len(s) < 2 or s[0][0] > start + 150 or s[-1][0] < end - 150:
            return None
        out, i, t = [], 0, start
        while t <= end:
            while i < len(s) - 2 and s[i + 1][0] < t:
                i += 1
            (ta, va), (tb, vb) = s[i], s[i + 1]
            part = min(1.0, max(0.0, (t - ta) / (tb - ta))) if tb > ta else 0.0
            out.append(va + (vb - va) * part)
            t += STEP_MS
        return out
