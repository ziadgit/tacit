"""Motion detectors (SPEC §13.6): writing, drawing, whiteboard, typing, making, gesturing.

Pure functions over 100 Hz motion samples, no numpy. A sample is a dict (the kit's
`Message` is a dict) or any object with `ax ay az` in g and `gx gy gz` in degrees/second,
as the kit's `band.on("motion", fn)` gives them. A missing or None field counts as 0.

Windows are 4 s with a 2 s hop. `SessionTracker` turns window labels into sessions with
hysteresis; only `{kind, started_at, ended_at, confidence}` ever leaves the bridge.
"""

from __future__ import annotations

import math
import operator
from collections import deque
from dataclasses import dataclass

# ---------------------------------------------------------------------------------------
# Rules. These numbers are GUESSES, to tune on a real wrist (as the kit says of its own
# gesture limits). Pitch is the forearm (the band's x axis) against the horizon, from the
# low-passed gravity: positive = hand above the elbow ("up"), negative = pitched down.
# ---------------------------------------------------------------------------------------
RATE_HZ = 100
WINDOW_S = 4.0
HOP_S = 2.0

DOMINANT_RANGE_HZ = (0.5, 12.0)  # autocorrelation peak search range
DOMINANT_MIN_R = 0.3  # a peak weaker than this (normalised) means "no rhythm": dominant 0
STILL_GYRO_DPS = 8.0  # a sample turning slower than this is "still"
SPIKE_G = 0.08  # |a| above the window median by this much starts a spike
SPIKE_MAX_S = 0.06  # ...and it must end within this long to count as short
GRAVITY_TAU_S = 0.5  # low-pass time constant for gravity

WRITING_GYRO_MEAN = (15.0, 120.0)
WRITING_DOMINANT_HZ = (3.0, 8.0)
WRITING_ACCEL_STD_MAX = 0.15
WRITING_PITCH_MAX = -10.0  # wrist pitched down

DRAWING_GYRO_MEAN = (10.0, 150.0)
DRAWING_DOMINANT_HZ = (0.5, 3.0)
DRAWING_ACCEL_STD = (0.05, 0.4)
DRAWING_STILL_MIN = 0.1  # "with pauses"

WHITEBOARD_PITCH_MIN = 30.0  # drawing-like, forearm raised

TYPING_BURSTS_PER_S = (5.0, 12.0)
TYPING_GYRO_MEAN_MAX = 20.0
TYPING_PITCH_LEVEL = 15.0  # |pitch| below this = wrist level

MAKING_DOMINANT_HZ = (1.0, 3.0)
MAKING_ACCEL_STD_MIN = 0.3

GESTURING_GYRO_STD_MIN = 50.0  # large motions...
GESTURING_STILL_MIN = 0.2  # ...that come and go

# Sessions (hysteresis)
START_S = 60.0  # look-back to start a session
START_SHARE = 0.7  # share of matching windows in that look-back
END_S = 45.0  # a session ends this long after its last matching window
MIN_SESSION_S = 120.0  # only sessions this long are reported
MIN_SESSION_BY_KIND = {"making": 120.0}  # making needs >= 2 min by its own rule

KINDS = ("writing", "drawing", "whiteboard", "typing", "making", "gesturing")
FIELDS = ("ax", "ay", "az", "gx", "gy", "gz")


@dataclass(frozen=True)
class Features:
    accel_std: float  # std of |a|, g
    gyro_mean: float  # mean of |gyro|, deg/s
    gyro_std: float  # std of |gyro|, deg/s
    dominant_hz: float  # autocorrelation peak of the gyro, 0.0 = no rhythm
    pitch_deg: float  # forearm pitch from low-passed gravity, + = up
    still_fraction: float  # share of samples turning slower than STILL_GYRO_DPS
    burstiness: float  # short accel spikes per second


@dataclass(frozen=True)
class Session:
    kind: str
    started_at: float
    ended_at: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "confidence": self.confidence,
        }


def _value(sample, key: str) -> float:
    v = sample.get(key) if isinstance(sample, dict) else getattr(sample, key, None)
    return 0.0 if v is None else float(v)


def _row(sample) -> tuple[float, ...]:
    return tuple(_value(sample, k) for k in FIELDS)


def _mean_std(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / n)


def _in(x: float, lo_hi: tuple[float, float]) -> bool:
    return lo_hi[0] <= x <= lo_hi[1]


def _dominant_hz(rows: list[tuple[float, ...]], rate: float) -> float:
    """Peak of the summed autocorrelation of the three gyro axes, in DOMINANT_RANGE_HZ."""
    # Halve the rate (average pairs) when it is high enough: 12 Hz still fits, and it is
    # four times less work in pure Python.
    halve = rate >= 4 * DOMINANT_RANGE_HZ[1]
    if halve:
        rate /= 2
    axes = []
    for k in (3, 4, 5):
        xs = [r[k] for r in rows]
        if halve:
            xs = [(a + b) / 2 for a, b in zip(xs[0::2], xs[1::2], strict=False)]
        m = sum(xs) / len(xs) if xs else 0.0
        axes.append([x - m for x in xs])
    n = len(axes[0])
    r0 = sum(sum(x * x for x in ax) for ax in axes)
    if r0 <= 1e-9:
        return 0.0
    lo = max(1, int(rate / DOMINANT_RANGE_HZ[1]))
    hi = min(n - 2, int(math.ceil(rate / DOMINANT_RANGE_HZ[0])))
    if hi <= lo:
        return 0.0
    r = {}
    for lag in range(lo - 1, hi + 2):
        r[lag] = sum(sum(map(operator.mul, ax, ax[lag:])) for ax in axes) / r0
    best_lag, best = 0, DOMINANT_MIN_R
    for lag in range(lo, hi + 1):
        if r[lag] > r[lag - 1] and r[lag] >= r[lag + 1] and r[lag] > best:
            best_lag, best = lag, r[lag]
    if not best_lag:
        return 0.0
    # Parabolic interpolation around the peak for a finer frequency.
    a, b, c = r[best_lag - 1], r[best_lag], r[best_lag + 1]
    denom = a - 2 * b + c
    shift = 0.5 * (a - c) / denom if denom else 0.0
    return rate / (best_lag + max(-0.5, min(0.5, shift)))


def features(samples, rate: float = RATE_HZ) -> Features:
    """Features of one window of motion samples (dicts or objects, see module doc)."""
    rows = [s if isinstance(s, tuple) else _row(s) for s in samples]
    if not rows:
        return Features(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    amag = [math.sqrt(r[0] ** 2 + r[1] ** 2 + r[2] ** 2) for r in rows]
    gmag = [math.sqrt(r[3] ** 2 + r[4] ** 2 + r[5] ** 2) for r in rows]
    _, accel_std = _mean_std(amag)
    gyro_mean, gyro_std = _mean_std(gmag)

    # Gravity: a one-pole low-pass of the accelerometer, averaged over the window.
    alpha = 1.0 / (1.0 + GRAVITY_TAU_S * rate)
    gx, gy, gz = rows[0][0], rows[0][1], rows[0][2]
    sx = sy = sz = 0.0
    for r in rows:
        gx += alpha * (r[0] - gx)
        gy += alpha * (r[1] - gy)
        gz += alpha * (r[2] - gz)
        sx, sy, sz = sx + gx, sy + gy, sz + gz
    pitch = math.degrees(math.atan2(sx, math.hypot(sy, sz))) if (sx or sy or sz) else 0.0

    still = sum(1 for g in gmag if g < STILL_GYRO_DPS) / len(rows)

    # Burstiness: short rises of |a| above the window's median.
    median = sorted(amag)[len(amag) // 2]
    max_len = max(1, round(SPIKE_MAX_S * rate))
    spikes, run = 0, 0
    for a in amag:
        if a - median > SPIKE_G:
            run += 1
        else:
            if 0 < run <= max_len:
                spikes += 1
            run = 0
    if 0 < run <= max_len:
        spikes += 1
    burstiness = spikes / (len(rows) / rate)

    return Features(
        accel_std=accel_std,
        gyro_mean=gyro_mean,
        gyro_std=gyro_std,
        dominant_hz=_dominant_hz(rows, rate),
        pitch_deg=pitch,
        still_fraction=still,
        burstiness=burstiness,
    )


def classify_window(f: Features, speech_active: bool = False) -> str | None:
    """The kind of one window, or None. Rules are the constants at the top of this file."""
    if (
        speech_active
        and f.gyro_std >= GESTURING_GYRO_STD_MIN
        and f.still_fraction >= GESTURING_STILL_MIN
    ):
        return "gesturing"
    drawing_like = (
        _in(f.gyro_mean, DRAWING_GYRO_MEAN)
        and _in(f.dominant_hz, DRAWING_DOMINANT_HZ)
        and _in(f.accel_std, DRAWING_ACCEL_STD)
        and f.still_fraction >= DRAWING_STILL_MIN
    )
    if drawing_like:
        return "whiteboard" if f.pitch_deg > WHITEBOARD_PITCH_MIN else "drawing"
    if (
        _in(f.gyro_mean, WRITING_GYRO_MEAN)
        and _in(f.dominant_hz, WRITING_DOMINANT_HZ)
        and f.accel_std < WRITING_ACCEL_STD_MAX
        and f.pitch_deg < WRITING_PITCH_MAX
    ):
        return "writing"
    if (
        _in(f.burstiness, TYPING_BURSTS_PER_S)
        and f.gyro_mean < TYPING_GYRO_MEAN_MAX
        and abs(f.pitch_deg) < TYPING_PITCH_LEVEL
    ):
        return "typing"
    if _in(f.dominant_hz, MAKING_DOMINANT_HZ) and f.accel_std > MAKING_ACCEL_STD_MIN:
        return "making"
    return None


class SessionTracker:
    """Feeds samples one at a time; returns sessions once they are complete.

    A session of kind K starts once the last START_S hold >= START_SHARE windows of K, and
    ends END_S after its last K window (it ends at that window). Only sessions at least
    MIN_SESSION_S long are reported. confidence = share of K windows within the session.
    `t` is in seconds (the kit's motion `t` is in milliseconds: pass m.t / 1000).
    """

    def __init__(self, rate: float = RATE_HZ) -> None:
        self.rate = rate
        self.window_n = round(WINDOW_S * rate)
        self.hop_n = round(HOP_S * rate)
        self.start_windows = int((START_S - WINDOW_S) / HOP_S) + 1
        self.speech_active = False
        self._rows: deque[tuple[float, ...]] = deque(maxlen=self.window_n)
        self._since_hop = 0
        self._last_t: float | None = None
        self._recent: deque[tuple[float, str | None]] = deque(maxlen=self.start_windows)
        self._kind: str | None = None
        self._started = self._last_match = 0.0
        self._matched = self._total = 0  # counted up to the last matching window
        self._pending = 0  # windows since the last match

    def feed(self, sample, t: float, speech_active: bool | None = None) -> list[Session]:
        if speech_active is not None:
            self.speech_active = speech_active
        if self._last_t is not None and t - self._last_t > 1.0:  # a gap: start the window over
            self._rows.clear()
            self._since_hop = 0
        self._last_t = t
        self._rows.append(_row(sample))
        self._since_hop += 1
        if len(self._rows) < self.window_n or self._since_hop < self.hop_n:
            return []
        self._since_hop = 0
        label = classify_window(features(list(self._rows), self.rate), self.speech_active)
        return self._window(t, label)

    def flush(self, t: float) -> list[Session]:
        """End whatever is open (at its last matching window, never after t)."""
        out = self._end(min(t, self._last_match)) if self._kind else []
        self._recent.clear()
        self._rows.clear()
        self._since_hop = 0
        self._last_t = None
        return out

    def _window(self, t: float, label: str | None) -> list[Session]:
        if self._kind is None:
            self._recent.append((t, label))
            if len(self._recent) < self.start_windows:
                return []
            for kind in KINDS:
                hits = [i for i, (_, lab) in enumerate(self._recent) if lab == kind]
                if len(hits) >= START_SHARE * len(self._recent):
                    first = hits[0]
                    self._kind = kind
                    self._started = self._recent[first][0] - WINDOW_S
                    self._last_match = self._recent[hits[-1]][0]
                    self._matched = len(hits)
                    self._total = hits[-1] - first + 1
                    self._pending = len(self._recent) - 1 - hits[-1]
                    self._recent.clear()
                    break
            return []
        if label == self._kind:
            self._matched += 1
            self._total += self._pending + 1
            self._pending = 0
            self._last_match = t
            return []
        self._pending += 1
        if t - self._last_match >= END_S:
            return self._end(self._last_match)
        return []

    def _end(self, ended_at: float) -> list[Session]:
        kind, started = self._kind, self._started
        confidence = self._matched / self._total if self._total else 0.0
        self._kind = None
        self._matched = self._total = self._pending = 0
        assert kind is not None
        if ended_at - started < MIN_SESSION_BY_KIND.get(kind, MIN_SESSION_S):
            return []
        return [Session(kind, started, ended_at, round(confidence, 3))]
