import importlib.util
import json
import math
import random
from pathlib import Path

import pytest

from tacit import gestures as g
from tacit.config import TEAM_BANDS

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_gesture_templates", ROOT / "scripts" / "make_gesture_templates.py"
)
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)


@pytest.fixture(scope="module")
def templates():
    return g.load_templates(Path("/nonexistent/gestures.json"))


def noisy(samples, seed, gyro=4.0, accel=0.008):
    rng = random.Random(seed)
    out = []
    for s in samples:
        n = dict(s)
        for k in ("ax", "ay", "az"):
            n[k] += rng.gauss(0, accel)
        for k in ("gx", "gy", "gz"):
            n[k] += rng.gauss(0, gyro)
        out.append(n)
    return out


def motion(fn, seconds, rest=0.6, rate=100, t0=5000.0):
    """Samples of fn(s) (deltas from rest) for `seconds`, then a still band for `rest`."""
    out = []
    for i in range(int((seconds + rest) * rate)):
        s = i / rate
        d = dict(t=t0 + i * 1000 / rate, ax=0.0, ay=0.0, az=1.0, gx=0.0, gy=0.0, gz=0.0)
        if s < seconds:
            d.update(fn(s))
        out.append(d)
    return out


def detect(samples, templates, limit=g.MUTE_LIMIT):
    det = g.GestureDetector(templates, limit)
    found = [r for s in samples if (r := det.feed(s, now=g.read_sample(s)["t"])) is not None]
    return found, det


def test_builtin_templates_exist_and_have_the_right_size(templates):
    assert set(templates) == {"x", "figure8"}
    for shapes in templates.values():
        assert shapes
        assert all(len(s) == g.POINTS * len(g.AXES) for s in shapes)


def test_limits():
    assert 0 < g.UNMUTE_LIMIT < g.MUTE_LIMIT


@pytest.mark.parametrize("name", ["x", "figure8"])
@pytest.mark.parametrize(
    "seconds,size,gain,seed",
    [(1.05, 0.35, (1.0, 0.9), 1), (1.45, 0.42, (0.9, 1.1), 2), (2.05, 0.45, (1.1, 1.0), 3)],
)
def test_drawn_gestures_match_under_mute_limit(templates, name, seconds, size, gain, seed):
    raw = mk.samples(name, seconds, size, t0_ms=12345.0, axis_gain=gain)
    found, det = detect(noisy(raw, seed), templates)
    assert found == [name], det.last


def test_figure8_at_50hz_with_attribute_samples(templates):
    class Obj:
        def __init__(self, d):
            self.__dict__.update(d)

    raw = noisy(mk.samples("figure8", 1.6, 0.4, rate_hz=50), seed=7)
    found, _ = detect([Obj(s) for s in raw], templates)
    assert found == ["figure8"]


def test_a_shake_never_matches(templates):
    shake = motion(lambda s: dict(az=1 + 1.5 * math.sin(40 * s)), 0.5)
    wrist = motion(lambda s: dict(gx=400 * math.sin(2 * math.pi * 6 * s),
                                  ax=0.8 * math.sin(2 * math.pi * 6 * s)), 0.8)
    for samples in (shake, wrist):
        found, det = detect(noisy(samples, 4), templates)
        assert found == []
        assert det.last is not None  # it was cut out as a gesture, and rejected


def test_an_ordinary_arm_swing_never_matches(templates):
    swing = motion(lambda s: dict(gy=150 * math.sin(2 * math.pi * s / 1.2),
                                  ax=0.3 * math.cos(2 * math.pi * s / 1.2)), 1.2)
    walk = motion(lambda s: dict(gy=200 * math.sin(2 * math.pi * s),
                                 az=1 + 0.4 * math.cos(2 * math.pi * s)), 2.0)
    wave = motion(lambda s: dict(gz=250 * math.sin(3 * math.pi * s)), 2.0)
    endless = motion(lambda s: dict(gy=200 * math.sin(2 * math.pi * s)), 8.0)
    for samples in (swing, walk, wave, endless):
        found, _ = detect(noisy(samples, 5), templates)
        assert found == []


def test_a_still_hand_never_matches(templates):
    tremor = motion(lambda s: dict(gx=8 * math.sin(2 * math.pi * 9 * s),
                                   gy=6 * math.cos(2 * math.pi * 11 * s)), 10.0)
    found, det = detect(noisy(tremor, 6), templates)
    assert found == [] and det.last is None


def test_unmute_limit_is_stricter(templates):
    raw = noisy(mk.samples("x", 1.3, 0.4), seed=8)
    found, det = detect(raw, templates)
    assert found == ["x"]
    shape_distance = det.last.distance
    # a sloppier X: a near-miss mutes but does not unmute
    sloppy = noisy(mk.samples("x", 1.3, 0.4, axis_gain=(0.55, 1.0)), seed=9)
    loose, det_loose = detect(sloppy, templates, g.MUTE_LIMIT)
    strict, _ = detect(sloppy, templates, g.UNMUTE_LIMIT)
    assert loose == ["x"] and strict == []
    assert shape_distance < det_loose.last.distance


def test_missing_time_and_none_fields():
    seg = g.Segmenter()
    assert seg.feed({"ax": 1.0}) is None
    assert g.read_sample({"t": 1, "ax": None, "gx": float("nan")})["gx"] == 0.0


def test_load_templates_merges_user_examples(tmp_path):
    builtin = g.load_templates(tmp_path / "missing.json")
    extra = [0.0] * (g.POINTS * len(g.AXES))
    data = Path("data")  # tests run in tmp_path (root conftest)
    data.mkdir()
    (data / "gestures.json").write_text(json.dumps({"x": [extra, [1, 2]], "other": [extra]}))
    merged = g.load_templates()
    assert len(merged["x"]) == len(builtin["x"]) + 1  # the bad [1, 2] is skipped
    assert merged["x"][-1] == extra
    assert merged["figure8"] == builtin["figure8"]
    assert g.classify(extra, merged, g.UNMUTE_LIMIT) == "x"
    (data / "gestures.json").write_text("not json")
    assert g.load_templates() == builtin


async def run_sim(play=None, ms=10000):
    from tacit.band import use_kit

    use_kit()
    from vexo_open import Band, SimTransport

    number = TEAM_BANDS[0]  # one of our own bands, never any other
    sim = SimTransport(number, realtime=False)
    band = await Band.connect(number, transport=sim)
    det = g.GestureDetector(g.load_templates(), g.MUTE_LIMIT)
    found = []
    band.on("motion", lambda m: found.append(r) if (r := det.feed(m, now=m.t)) else None)
    await band.set_motion(accel_range=8)
    await band.configure(motion=50)
    if play is not None:
        sim.play_motion(play)
    sim.step(ms)
    await band.disconnect()
    return found


async def test_pretend_band_idle_swing_never_matches():
    assert await run_sim() == []


async def test_pretend_band_played_x_matches():
    raw = mk.samples("x", 1.4, 0.4, rate_hz=50)
    played = [{k: v for k, v in s.items() if k != "t"} for s in raw]
    assert await run_sim(play=played, ms=4000) == ["x"]
