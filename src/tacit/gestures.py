"""The mute gesture recogniser (SPEC §13.2): an X or a figure 8 drawn in the air.

Pure functions, no band. A Python port of the kit's
`vexo-open-kit/projects/gesture-trainer/recogniser.js` (template matching):

  1. Segmenter   cuts the stream of samples into gestures: from "the hand starts to move"
                 until "the hand has been quiet for a moment".
  2. to_shape    squeezes a gesture into a fixed list of numbers, so a slow and a fast
                 version of the same gesture look alike.
  3. match       finds the recorded example with the most similar shape.

Motion samples are what `band.on("motion", fn)` gives: a `vexo_open.Message` (a dict that
also allows attribute access) with `t` (band time, ms), `ax ay az` (g) and `gx gy gz`
(degrees/second). Any mapping or any object with those attributes works. Fast motion with
only one sensor on gives None for the other sensor's fields; they are read as 0 (the
recogniser needs both sensors to work well).
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

# The numbers to tune. They are guesses that work on the pretend band's motions: nobody
# has tried them on a real wrist yet. What is measured (one band lying on a desk)
# is how quiet a band at rest is: it turns at about 2.2 to 2.4 degrees/second
# and its acceleration changes by at most 0.005 g from one sample to the next. Both start
# numbers are far above that, so a band at rest never starts a gesture. Still to measure:
# a still hand (it trembles more than a desk) and real gestures.
START_GYRO = 40.0  # degrees/second: turning faster than this counts as moving (at rest: ~2.3)
START_ACCEL = 0.08  # g: so does a change in acceleration this big between samples (rest: 0.005)
QUIET_MS = 300  # a gesture ends when the hand was quiet for this long
MIN_MS = 200  # shorter than this is a bump, not a gesture
MAX_MS = 3000  # longer than this is just moving around
MAX_SAMPLES = 2000  # the most samples one gesture may have (50 a second for 3 seconds are 150)
POINTS = 24  # every gesture becomes this many points in time
GYRO_SCALE = 250.0  # degrees/second that count as much as...
ACCEL_SCALE = 1.0  # ...this many g. Without it the big gyro numbers would decide everything.
NOT_SURE = 0.5  # nearest example further away than this: "not sure"
AXES = ("ax", "ay", "az", "gx", "gy", "gz")

# Tacit's two thresholds (also untested guesses). Mute is easy to trigger and hard to undo:
# a near-miss still mutes, but unmuting needs a cleaner gesture (plus a double-tap).
MUTE_LIMIT = 0.6
UNMUTE_LIMIT = 0.35

GESTURES = ("x", "figure8")
BUILTIN_TEMPLATES = Path(__file__).with_name("gesture_templates.json")
USER_TEMPLATES = Path("data") / "gestures.json"  # the wearer's own examples (tacit gestures record)

Sample = dict[str, float]  # t, ax, ay, az, gx, gy, gz
Shape = list[float]  # POINTS x 6 numbers
Templates = dict[str, list[Shape]]


class Match(NamedTuple):
    label: str | None  # None: nothing near enough (or no examples)
    distance: float


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def read_sample(sample: Any) -> Sample | None:
    """A plain copy of one motion sample (mapping or attributes), or None without a usable `t`.
    Missing, None or non-finite sensor values become 0."""
    get = sample.get if isinstance(sample, Mapping) else lambda k: getattr(sample, k, None)
    t = _number(get("t"))
    if t is None:
        return None
    out: Sample = {"t": t}
    for axis in AXES:
        out[axis] = _number(get(axis)) or 0.0
    return out


def _moving(sample: Sample, before: Sample | None) -> bool:
    """Is the hand moving at this sample? `before` is the sample before it (or None)."""
    if math.hypot(sample["gx"], sample["gy"], sample["gz"]) > START_GYRO:
        return True
    return before is not None and math.hypot(
        sample["ax"] - before["ax"], sample["ay"] - before["ay"], sample["az"] - before["az"]
    ) > START_ACCEL


class Segmenter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Throw away a gesture in progress. Call it when the link drops."""
        self.samples: list[Sample] = []  # the gesture so far; empty while the hand is quiet
        self.before: Sample | None = None  # the sample before this one
        self.last_move = 0.0  # band time (ms) of the last sample that was moving
        self.began = 0.0  # the computer's time (ms) when this gesture began
        self.too_long = False  # once too many samples or too long: no gesture any more

    def feed(self, sample: Any, now: float | None = None) -> list[Sample] | None:
        """Feed one motion sample. Returns the samples of a finished gesture, or None.

        `t` is the band's time in ms: we measure with it, never by counting samples, because
        samples can arrive in packets or get lost. `now` is the computer's time in ms
        (default: a monotonic clock): the band's time alone cannot be trusted to stop the list
        from growing (a faulty band can send the same `t` again and again)."""
        s = read_sample(sample)
        if s is None:
            return None  # no time, no place in a gesture
        if now is None:
            now = time.monotonic() * 1000
        # A jump in time (samples lost, link was down): what we have is not one gesture.
        if self.before and (s["t"] < self.before["t"] or s["t"] - self.before["t"] > QUIET_MS):
            self.reset()
        is_moving = _moving(s, self.before)
        self.before = s
        if is_moving:
            self.last_move = s["t"]
        if not self.samples and not is_moving:
            return None  # still quiet
        # Keep the sample, unless the hand has been moving for too long already. "Too long" is
        # measured three ways: by the band's time, by the count, and by the computer's clock.
        if not self.samples:
            self.began = now
            self.too_long = False
            self.samples.append(s)
        elif len(self.samples) >= MAX_SAMPLES or now - self.began > 2 * (MAX_MS + QUIET_MS):
            self.too_long = True
        elif s["t"] - self.samples[0]["t"] <= MAX_MS + QUIET_MS:
            self.samples.append(s)
        if s["t"] - self.last_move < QUIET_MS:
            return None  # not over yet

        # Quiet for long enough: the gesture is everything up to the last moving sample.
        gesture = [one for one in self.samples if one["t"] <= self.last_move]
        too_long = self.too_long
        self.samples = []
        self.too_long = False
        if too_long or not gesture:
            return None
        ms = self.last_move - gesture[0]["t"]
        return gesture if MIN_MS <= ms <= MAX_MS else None


def to_shape(gesture: list[Sample]) -> Shape:
    """Turn a gesture into POINTS x 6 numbers. The points are spread evenly over the time of
    the gesture, and each value is read off between the two samples next to that time."""
    start = gesture[0]["t"]
    length = gesture[-1]["t"] - start
    shape: Shape = []
    i = 0
    for p in range(POINTS):
        t = start + length * p / (POINTS - 1)
        while i < len(gesture) - 2 and gesture[i + 1]["t"] < t:
            i += 1
        a = gesture[i]
        b = gesture[i + 1] if i + 1 < len(gesture) else a
        part = min(1.0, max(0.0, (t - a["t"]) / (b["t"] - a["t"]))) if b["t"] > a["t"] else 0.0
        for axis in AXES:
            value = a[axis] + (b[axis] - a[axis]) * part
            shape.append(value / (GYRO_SCALE if axis[0] == "g" else ACCEL_SCALE))
    return shape


def distance(one: Shape, other: Shape) -> float:
    """How different two shapes are: the mean distance between their points. 0 = the same."""
    n = len(AXES)
    total = 0.0
    for p in range(0, len(one), n):
        total += math.sqrt(sum((one[k] - other[k]) ** 2 for k in range(p, p + n)))
    return total / (len(one) / n)


def match(shape: Shape, examples: Iterable[tuple[str, Shape]], limit: float = NOT_SURE) -> Match:
    """Find the nearest example. `examples` are (label, shape) pairs. The label is None when
    nothing is near enough (or there are no examples); the distance is always the nearest."""
    best = Match(None, math.inf)
    for label, example in examples:
        d = distance(shape, example)
        if d < best.distance:
            best = Match(label, d)
    return best if best.distance <= limit else Match(None, best.distance)


def classify(shape: Shape, templates: Templates, limit: float) -> str | None:
    """"x", "figure8" or None: the nearest template's gesture, if within `limit`."""
    pairs = ((name, one) for name, shapes in templates.items() for one in shapes)
    return match(shape, pairs, limit).label


def _valid_shape(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == POINTS * len(AXES)
        and all(_number(v) is not None for v in value)
    )


def _read_templates(path: Path) -> Templates:
    """Read one templates file. Untrusted when it is the user's: bad entries are skipped."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("gesture templates unreadable, ignored: %s", path)
        return {}
    if not isinstance(raw, dict):
        log.warning("gesture templates not an object, ignored: %s", path)
        return {}
    out: Templates = {}
    for name in GESTURES:
        shapes = raw.get(name)
        if isinstance(shapes, list):
            good = [[float(v) for v in s] for s in shapes if _valid_shape(s)]
            if len(good) < len(shapes):
                bad = len(shapes) - len(good)
                log.warning("%d bad %s template(s) skipped: %s", bad, name, path)
            if good:
                out[name] = good
    return out


def load_templates(extra_path: Path | None = None) -> Templates:
    """The built-in templates plus the wearer's own examples (default `data/gestures.json`,
    same format: {"x": [shape, ...], "figure8": [shape, ...]}), merged."""
    templates: Templates = {name: [] for name in GESTURES}
    for path in (BUILTIN_TEMPLATES, extra_path if extra_path is not None else USER_TEMPLATES):
        for name, shapes in _read_templates(path).items():
            templates[name].extend(shapes)
    return templates


class GestureDetector:
    """Feed it every motion sample; it says "x" / "figure8" when a matching gesture ends."""

    def __init__(self, templates: Templates, limit: float = MUTE_LIMIT) -> None:
        self.templates = templates
        self.limit = limit
        self.segmenter = Segmenter()
        self.last: Match | None = None  # the last finished gesture's nearest match

    def reset(self) -> None:
        """Forget a gesture in progress (link dropped, stream restarted)."""
        self.segmenter.reset()

    def feed(self, sample: Any, now: float | None = None) -> str | None:
        gesture = self.segmenter.feed(sample, now)
        if gesture is None:
            return None
        pairs = ((name, one) for name, shapes in self.templates.items() for one in shapes)
        self.last = match(to_shape(gesture), pairs, self.limit)
        return self.last.label
