"""Make the built-in mute gesture templates: src/tacit/gesture_templates.json (SPEC §13.2).

Stdlib only. A gesture is a path the hand draws in the air, in a vertical plane in front of
the wearer (metres; x to the right, y up):

  - x        two crossing diagonal strokes: top-left to bottom-right, up to top-right,
             then top-right to bottom-left.
  - figure8  an upright lemniscate (of Gerono), once round.

The forearm swings from the elbow, so the wrist turns at (hand speed / forearm length):
moving sideways turns it about the vertical axis (gz), moving up and down about the
sideways axis (gy). The band feels the hand's acceleration plus gravity: ax sideways,
az up (1 g at rest). Samples go at 100 Hz through tacit.gestures.Segmenter (cut just as
live motion is) and to_shape. Each gesture is drawn at a few speeds, because to_shape keeps
the size of the numbers (a fast gesture turns faster).

    .venv/bin/python scripts/make_gesture_templates.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tacit.gestures import BUILTIN_TEMPLATES, Segmenter, to_shape  # noqa: E402

G = 9.81  # m/s² per g
FOREARM_M = 0.35  # elbow to wrist
RATE_HZ = 100
REST_S = (0.3, 0.6)  # still before and after the gesture, so the Segmenter cuts it
SIZE_M = 0.4  # how big the gesture is drawn
SPEEDS = {"x": (0.9, 1.2, 1.6, 2.2), "figure8": (1.0, 1.4, 1.9, 2.5)}  # seconds per gesture


def ease(u: float) -> float:
    """Minimum-jerk progress 0..1: a hand starts and stops smoothly."""
    u = min(1.0, max(0.0, u))
    return u**3 * (10 - 15 * u + 6 * u * u)


def x_path(size: float):
    """Position (x, y) at progress u in 0..1 of an X: three straight strokes, each eased."""
    h = size / 2
    points = [(-h, h), (h, -h), (h, h), (-h, -h)]
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:], strict=False)]
    total = sum(lengths)

    def at(u: float) -> tuple[float, float]:
        d = min(1.0, max(0.0, u)) * total
        for (a, b), length in zip(zip(points, points[1:], strict=False), lengths, strict=True):
            if d <= length:
                k = ease(d / length)
                return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
            d -= length
        return points[-1]

    return at, False  # each stroke is eased itself


def figure8_path(size: float):
    """Position at progress u of an upright figure 8: x = w sin θ cos θ, y = h sin θ."""
    h = size / 2

    def at(u: float) -> tuple[float, float]:
        theta = 2 * math.pi * u
        return h * math.sin(theta) * math.cos(theta) * 1.2, h * math.sin(theta)

    return at, True  # ease the whole loop


PATHS = {"x": x_path, "figure8": figure8_path}


def samples(name: str, seconds: float, size: float = SIZE_M, rate_hz: int = RATE_HZ,
            t0_ms: float = 0.0, axis_gain: tuple[float, float] = (1.0, 1.0)) -> list[dict]:
    """Motion samples (t ms, ax ay az g, gx gy gz deg/s) of drawing `name` in `seconds`,
    with still hand before and after. axis_gain scales (sideways, up/down) for variety."""
    at, eased = PATHS[name](size)
    dt = 1 / rate_hz
    before, after = REST_S
    n = round((before + seconds + after) * rate_hz) + 1

    def pos(i: int) -> tuple[float, float]:
        u = (i * dt - before) / seconds
        u = min(1.0, max(0.0, u))
        x, y = at(ease(u) if eased else u)
        return x * axis_gain[0], y * axis_gain[1]

    out = []
    for i in range(n):
        (x0, y0), (x1, y1), (x2, y2) = pos(i - 1), pos(i), pos(i + 1)
        vx, vy = (x2 - x0) / (2 * dt), (y2 - y0) / (2 * dt)
        acx, acy = (x2 - 2 * x1 + x0) / dt**2, (y2 - 2 * y1 + y0) / dt**2
        out.append({
            "t": t0_ms + i * dt * 1000,
            "ax": acx / G, "ay": 0.0, "az": 1 + acy / G,
            "gx": 0.0,
            "gy": -math.degrees(vy / FOREARM_M),
            "gz": math.degrees(vx / FOREARM_M),
        })
    return out


def cut(motion: list[dict]) -> list[dict]:
    """The one gesture the Segmenter finds in `motion` (fed with a matching computer clock)."""
    seg = Segmenter()
    found = [g for s in motion if (g := seg.feed(s, now=s["t"])) is not None]
    if len(found) != 1:
        raise ValueError(f"expected one gesture, the Segmenter found {len(found)}")
    return found[0]


def templates() -> dict[str, list[list[float]]]:
    return {
        name: [[round(v, 4) for v in to_shape(cut(samples(name, s)))] for s in speeds]
        for name, speeds in SPEEDS.items()
    }


def main() -> None:
    data = templates()
    BUILTIN_TEMPLATES.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    counts = ", ".join(f"{k}: {len(v)}" for k, v in data.items())
    print(f"wrote {BUILTIN_TEMPLATES.relative_to(ROOT)} ({counts})")


if __name__ == "__main__":
    main()
