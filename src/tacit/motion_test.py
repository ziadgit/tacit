"""Motion detector tests: synthetic signals (sine mixes plus noise) and the pretend band."""

import functools
import math
import random
from types import SimpleNamespace

import pytest

from tacit import motion
from tacit.motion import Session, SessionTracker, classify_window, features

RATE = 100
BAND = 16  # one of the team's own bands (tacit.config.TEAM_BANDS)


def _swing(t: float) -> dict:
    """The pretend band's own made-up swing (vexo_open/transports/sim.py), in g and deg/s."""
    a = 2 * math.pi * t / 2.0
    return dict(ax=0.12 * math.sin(a), ay=0.12 * math.cos(a), az=1 + 0.04 * math.sin(3 * a),
                gx=30 * math.cos(a), gy=-30 * math.sin(a), gz=10 * math.sin(2 * a))


def synthetic(kind: str | None, seconds: float, rate: int = RATE, seed: int = 0) -> list[dict]:
    """Synthetic motion for one kind: sine mixes plus noise. kind None = lying still."""
    return list(_synthetic(kind, seconds, rate, seed))


@functools.cache
def _synthetic(kind, seconds, rate, seed) -> tuple:
    rnd = random.Random(seed)
    out = []
    next_key = 0.0
    for i in range(int(seconds * rate)):
        t = i / rate
        n = rnd.gauss
        tau = 2 * math.pi * t
        if kind == "writing":  # small 5 Hz strokes, wrist pitched ~20 degrees down
            s = dict(ax=-0.34 + 0.03 * math.sin(tau * 5), ay=0.02 * math.cos(tau * 5), az=0.94,
                     gx=50 * math.sin(tau * 5), gy=25 * math.sin(tau * 5 + 1),
                     gz=10 * math.sin(tau * 0.3))
        elif kind in ("drawing", "whiteboard"):  # 1.5 Hz strokes, a 1 s pause every 4 s
            on = (t % 4.0) < 3.0
            g = (0.7, 0.71) if kind == "whiteboard" else (0.0, 1.0)  # forearm 45 degrees up
            s = dict(ax=g[0] + on * 0.15 * math.sin(tau * 1.5), ay=on * 0.1 * math.cos(tau * 1.5),
                     az=g[1] + on * 0.12 * math.sin(tau * 3), gx=on * 60 * math.sin(tau * 1.5),
                     gy=on * 40 * math.cos(tau * 1.5), gz=0.0)
        elif kind == "typing":  # keystrokes ~8 a second: 20 ms accel spikes, level wrist
            s = dict(ax=0.0, ay=0.0, az=1.0, gx=2 * math.sin(tau * 0.7), gy=0.0, gz=0.0)
            if t >= next_key:
                next_key = t + rnd.uniform(0.1, 0.15)
            if next_key - t > 0.1 - 1e-9 and next_key - t <= 0.12:
                s["az"] += 0.25
        elif kind == "making":  # sawing / kneading at 2 Hz, big along gravity
            s = dict(ax=0.1 * math.sin(tau * 2), ay=0.0, az=1 + 0.6 * math.sin(tau * 2),
                     gx=150 * math.sin(tau * 2), gy=30 * math.cos(tau * 2), gz=0.0)
        elif kind == "gesturing":  # a big 0.6 s gesture every 2 s, still between
            on = (t % 2.0) < 0.6
            s = dict(ax=on * 0.3 * math.sin(tau * 1.7), ay=0.0, az=1.0,
                     gx=on * 250 * math.sin(tau * 1.7), gy=on * 120 * math.cos(tau * 1.7), gz=0.0)
        elif kind == "swing":
            s = _swing(t)
        else:
            s = dict(ax=0.0, ay=0.0, az=1.0, gx=0.0, gy=0.0, gz=0.0)
        for k in ("ax", "ay", "az"):
            s[k] = float(s[k]) + n(0, 0.005)
        for k in ("gx", "gy", "gz"):
            s[k] = float(s[k]) + n(0, 1.5)
        out.append(s)
    return tuple(out)


def _windows(samples, rate=RATE):
    w, h = int(motion.WINDOW_S * rate), int(motion.HOP_S * rate)
    for i in range(0, len(samples) - w + 1, h):
        yield samples[i : i + w]


@pytest.mark.parametrize("kind", ["writing", "drawing", "whiteboard", "typing", "making"])
def test_each_kind_labelled_right(kind):
    labels = [classify_window(features(w)) for w in _windows(synthetic(kind, 20, seed=1))]
    assert labels and all(lab == kind for lab in labels), labels


def test_gesturing_needs_speech():
    wins = list(_windows(synthetic("gesturing", 20)))
    assert all(classify_window(features(w), speech_active=True) == "gesturing" for w in wins)
    assert all(classify_window(features(w)) != "gesturing" for w in wins)


@pytest.mark.parametrize("kind", ["swing", None])
def test_swing_and_stillness_are_nothing(kind):
    labels = [classify_window(features(w), speech_active=True)
              for w in _windows(synthetic(kind, 20))]
    assert labels == [None] * len(labels)


def test_features_accepts_objects_and_missing_fields():
    as_dicts = synthetic("writing", 4)
    as_objects = [SimpleNamespace(**s) for s in as_dicts]
    assert features(as_dicts) == features(as_objects)
    f = features([{"ax": 0.0, "ay": 0.0, "az": 1.0, "gx": None} for _ in range(400)])
    assert f.gyro_mean == 0.0 and f.still_fraction == 1.0 and abs(f.pitch_deg) < 1e-6


def test_writing_features_look_like_writing():
    f = features(synthetic("writing", 4))
    assert 4.5 < f.dominant_hz < 5.5
    assert f.pitch_deg < -15
    assert f.accel_std < 0.15


def _track(samples, tracker=None, t0=0.0):
    tracker = tracker or SessionTracker()
    out = []
    for i, s in enumerate(samples):
        out += tracker.feed(s, t0 + (i + 1) / RATE)
    return tracker, out


def test_three_minutes_of_writing_is_one_session():
    tracker, out = _track(synthetic("writing", 180) + synthetic(None, 48, seed=2))
    assert len(out) == 1  # ended by itself, 45 s after the writing stopped
    s = out[0]
    assert s.kind == "writing"
    assert s.confidence > 0.7
    assert s.ended_at - s.started_at >= 120
    assert s.to_dict() == {"kind": "writing", "started_at": s.started_at,
                           "ended_at": s.ended_at, "confidence": s.confidence}
    assert tracker.flush(228.0) == []


def test_flush_ends_an_open_session():
    tracker, out = _track(synthetic("making", 130))
    assert out == []
    (s,) = tracker.flush(130.0)
    assert s.kind == "making" and s.ended_at <= 130.0 and s.ended_at - s.started_at >= 120


def test_short_bursts_are_not_reported():
    # 80 s of writing starts a session, but it is shorter than 2 min.
    _, out = _track(synthetic("writing", 80) + synthetic(None, 48, seed=3))
    assert out == []
    # 40 s bursts never even start one.
    burst = synthetic("writing", 40) + synthetic(None, 20, seed=4)
    tracker, out = _track(burst * 2)
    assert out == [] and tracker.flush(120.0) == []


def test_session_dataclass_is_only_what_is_uploaded():
    assert [f for f in Session.__dataclass_fields__] == [
        "kind", "started_at", "ended_at", "confidence"]


# ---- end to end with the kit's pretend band (no hardware, its clock stepped by hand) ----

async def _run_sim(seconds: int, played=None):
    from tacit.band import use_kit

    use_kit()
    from vexo_open import Band, SimTransport

    sim = SimTransport(BAND, realtime=False, auto_tap=False)
    band = await Band.connect(BAND, transport=sim)
    tracker, out = SessionTracker(), []
    band.on("motion", lambda m: out.extend(tracker.feed(m, m.t / 1000)))
    await band.configure(motion=100)
    if played is not None:
        sim.play_motion(played)
    for _ in range(seconds):
        sim.step(1000)
    out += tracker.flush(seconds)
    await band.disconnect()
    return out


async def test_pretend_band_swing_is_no_session():
    assert await _run_sim(64) == []


async def test_pretend_band_played_writing_is_a_session():
    out = await _run_sim(126, played=synthetic("writing", 126))
    assert [s.kind for s in out] == ["writing"]
    assert out[0].confidence > 0.7
