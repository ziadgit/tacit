"""The bridge on the pretend band (SPEC §13.1, §13.2). Never a real band; band 74 / 16 only."""

import asyncio
import importlib.util
import math
from pathlib import Path

import pytest

from tacit import bridge as br
from tacit import gestures as g
from tacit.config import TEAM_BANDS
from tacit.testing import make_settings

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_gesture_templates", ROOT / "scripts" / "make_gesture_templates.py")
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)

BAND = TEAM_BANDS[1]


class FakeEars:
    def __init__(self, on_piece, keyterms):
        self.on_piece = on_piece
        self.keyterms = keyterms
        self.fed = 0
        self.started = False
        self.stopped = False

    def start(self, on_text=None):
        self.started = True
        return self

    def feed(self, packet, seq=None):
        self.fed += 1

    def stop(self, wait=0):
        self.stopped = True
        return ""


class FakeServer:
    def __init__(self):
        self.calls = []
        self.command = {"muted": False, "changed": False}
        self.fail = False

    async def _rec(self, name, arg=None):
        if self.fail:
            raise ConnectionError("offline")
        self.calls.append((name, arg))

    async def config(self):
        return {"keyterms": ["Maya", "Acme"], "kinds_off": []}

    async def commands(self):
        await self._rec("commands")
        return dict(self.command)

    async def state(self, s):
        await self._rec("state", s)

    async def segments(self, segs):
        await self._rec("segments", segs)

    async def moments(self, ms):
        await self._rec("moments", ms)

    async def rewind(self, seconds):
        await self._rec("rewind", seconds)

    def named(self, name):
        return [a for n, a in self.calls if n == name]


class Rig:
    """A Bridge on a pretend band whose clock is the band's own (no real waiting)."""

    def __init__(self, sim, band, bridge, server, ears, leds, slept, lines):
        self.sim, self.band, self.bridge, self.server = sim, band, bridge, server
        self.ears, self.leds, self.slept, self.lines = ears, leds, slept, lines

    @property
    def mic_on(self):
        return self.sim.led.get("source") == "mic"

    async def advance(self, ms, step=20):
        done = 0
        while done < ms:
            self.sim.step(step)
            done += step
            for _ in range(5):
                await asyncio.sleep(0)

    async def settle(self):
        for _ in range(20):
            await asyncio.sleep(0)
        for t in list(self.bridge.tasks):
            await t

    async def play(self, samples):
        self.sim.play_motion([{k: v for k, v in s.items() if k != "t"} for s in samples])

    async def close(self):
        await self.settle()
        await self.band.disconnect()


async def rig(tmp_path, *, state_path=None, server=None, templates=None):
    from tacit.band import use_kit

    use_kit()
    from vexo_open import Band, SimTransport

    leds = []
    sim = SimTransport(BAND, realtime=False, auto_tap=False, on_led=leds.append)
    band = await Band.connect(BAND, transport=sim)
    ears = []
    slept = []
    lines = []

    async def sleep(s):
        slept.append(s)

    def factory(on_piece, keyterms):
        e = FakeEars(on_piece, keyterms)
        ears.append(e)
        return e

    server = server if server is not None else FakeServer()
    settings = make_settings(tacit_band=BAND, tacit_data_dir=tmp_path / "data")
    bridge = br.Bridge(settings, band, server=server, ears_factory=factory,
                       templates=templates if templates is not None else g.load_templates(
                           Path("/nonexistent/gestures.json")),
                       state_path=state_path or tmp_path / "data" / "bridge-state.json",
                       clock=lambda: sim.now_ms / 1000, sleep=sleep, echo=lines.append)
    await bridge.start()
    return Rig(sim, band, bridge, server, ears, leds, slept, lines)


def gesture(name, seconds=1.4, size=0.4, rate=100):
    return mk.samples(name, seconds, size, rate_hz=rate)


def is_white_blink(led):
    return (led.get("r"), led.get("g"), led.get("b")) == (255, 255, 255) and led.get("pattern")


async def mute_by(r, name):
    samples = gesture(name)
    await r.play(samples)
    played_ms = len(samples) * 10
    t0 = r.sim.now_ms
    waited = 0
    while r.mic_on and waited < played_ms + 3000:
        await r.advance(20)
        waited += 20
    assert not r.mic_on, f"{name} did not mute"
    return (r.sim.now_ms - t0) - played_ms   # ms from the gesture's end to the mic off


async def test_starts_listening_with_the_notice(tmp_path):
    r = await rig(tmp_path)
    assert r.lines[0] == br.SOUND_NOTICE
    assert r.mic_on and r.bridge.listening and r.ears[0].started
    assert r.ears[0].keyterms == ["Maya", "Acme"]
    await r.close()


@pytest.mark.parametrize("name", ["x", "figure8"])
async def test_gesture_mutes_within_a_second_with_rewind_and_blink(tmp_path, name):
    r = await rig(tmp_path)
    late = await mute_by(r, name)
    assert late <= 1000
    await r.settle()
    assert r.bridge.muted and not r.bridge.listening
    assert r.ears[0].stopped
    assert r.server.named("rewind") == [15]
    whites = [i for i, led in enumerate(r.leds) if is_white_blink(led)]
    assert whites, r.leds
    after = r.leds[whites[-1] + 1:]
    assert after and after[-1].get("brightness") == 0   # then off
    assert 0.8 in r.slept
    assert br.load_state(r.bridge.state_path) == {"muted": True}
    await r.close()


async def test_unmute_needs_gesture_and_double_tap(tmp_path):
    r = await rig(tmp_path)
    await mute_by(r, "x")
    await r.settle()
    # a double-tap alone does nothing
    r.sim.tap("double-tap")
    await r.advance(100)
    await r.settle()
    assert r.bridge.muted and not r.mic_on
    # the gesture alone does nothing
    await r.play(gesture("x"))
    await r.advance(2500)
    await r.settle()
    assert r.bridge.muted and not r.mic_on
    # gesture then a double-tap after the 3 s window: still muted
    await r.advance(3000)
    r.sim.tap("double-tap")
    await r.advance(100)
    await r.settle()
    assert r.bridge.muted
    # gesture, then a double-tap within 3 s: listening again
    await r.play(gesture("figure8"))
    await r.advance(2200)
    r.sim.tap("double-tap")
    await r.advance(100)
    await r.settle()
    assert not r.bridge.muted and r.mic_on and len(r.ears) == 2
    assert br.load_state(r.bridge.state_path) == {"muted": False}
    await r.close()


async def test_swing_shake_and_still_never_mute(tmp_path):
    r = await rig(tmp_path)
    await r.advance(10000, step=50)        # the pretend band's own swing
    assert not r.bridge.muted
    shake = [dict(ax=0.0, ay=0.0, az=1 + 1.5 * math.sin(40 * i / 100), gx=0.0, gy=0.0, gz=0.0)
             for i in range(50)]
    await r.play(shake)
    await r.advance(2000)
    still = [dict(ax=0.0, ay=0.0, az=1.0, gx=1.5, gy=-1.0, gz=0.5)] * 500
    await r.play(still)
    await r.advance(6000, step=50)
    await r.settle()
    assert not r.bridge.muted and r.mic_on
    await r.close()


async def test_muted_state_survives_a_restart(tmp_path):
    state = tmp_path / "state.json"
    r = await rig(tmp_path, state_path=state)
    await mute_by(r, "x")
    await r.close()
    r2 = await rig(tmp_path, state_path=state)
    assert r2.bridge.muted and not r2.mic_on and r2.ears == []
    assert any("muted" in line for line in r2.lines)
    await r2.close()


async def test_reconnect_comes_back_muted(tmp_path):
    r = await rig(tmp_path)
    await mute_by(r, "x")
    await r.settle()
    r.bridge.on_reconnected(None)
    await r.settle()
    assert not r.mic_on
    await r.close()


def test_stop_phrase_regex():
    for said in ("Please stop recording.", "can you turn it off", "Don't record this",
                 "this is off the record", "dont record", "mute that"):
        assert br.STOP_PHRASE.search(said), said
    for said in ("stop the recording studio", "record it", "muted colours", "turn off the oven"):
        assert not br.STOP_PHRASE.search(said), said


async def test_stop_phrase_mutes_with_rewind_and_is_not_uploaded(tmp_path):
    r = await rig(tmp_path)
    t = r.bridge.clock()
    r.bridge.on_mic_level(type("L", (), {"rms_db": 18})())
    r.ears[0].on_piece(br.Piece("Open the update with the number.", t - 2, t, 0))
    await r.bridge.tick()
    assert r.server.named("segments")[0][0]["text"] == "Open the update with the number."
    assert r.server.named("segments")[0][0]["level"] == 18
    r.ears[0].on_piece(br.Piece("Okay, off the record now", t, t + 1, 1))
    await r.bridge.tick()
    await r.settle()
    assert r.bridge.muted and not r.mic_on
    assert r.server.named("rewind") == [15]
    texts = [s["text"] for segs in r.server.named("segments") for s in segs]
    assert "Okay, off the record now" not in texts
    await r.close()


async def test_rewind_drops_unuploaded_segments(tmp_path):
    server = FakeServer()
    r = await rig(tmp_path, server=server)
    server.fail = True
    t = r.bridge.clock()
    r.ears[0].on_piece(br.Piece("old enough", t - 60, t - 50, 0))
    r.ears[0].on_piece(br.Piece("just now", t - 3, t - 1, 0))
    await r.bridge.tick()
    assert len(r.bridge.pending_segments) == 2
    await r.bridge.mute("test")
    assert [s["text"] for s in r.bridge.pending_segments] == ["old enough"]
    server.fail = False
    await r.bridge.flush()
    assert server.named("rewind") == []                   # backing off after the failure
    await r.advance(2100, step=100)
    await r.bridge.flush()
    assert server.named("rewind") == [15]
    assert [s["text"] for s in server.named("segments")[0]] == ["old enough"]
    await r.close()


async def test_app_commands(tmp_path):
    r = await rig(tmp_path)
    r.server.command = {"muted": True, "changed": True}
    await r.bridge.poll_commands()
    await r.settle()
    assert r.bridge.muted and not r.mic_on
    r.server.command = {"muted": False, "changed": False}   # stale: never unmutes
    await r.bridge.poll_commands()
    assert r.bridge.muted
    r.server.command = {"muted": False, "changed": True}
    await r.bridge.poll_commands()
    await r.settle()
    assert not r.bridge.muted and r.mic_on
    await r.close()


async def test_double_tap_keeps_the_last_minute(tmp_path):
    r = await rig(tmp_path)
    await r.advance(100)
    r.sim.tap("double-tap")
    await r.advance(100)
    await r.bridge.tick()
    kept = r.server.named("moments")[0]
    assert kept[0]["kind"] == "kept"
    await r.close()


async def test_state_report(tmp_path):
    r = await rig(tmp_path)
    await r.bridge.tick()
    s = r.server.named("state")[0]
    assert s["connected"] and s["listening"] and not s["muted"]
    assert r.server.named("commands")
    await r.close()


async def test_audio_goes_to_the_ears_only_while_listening(tmp_path):
    r = await rig(tmp_path)
    await r.advance(400)
    assert r.ears[0].fed > 0
    await r.bridge.mute("test")
    fed = r.ears[0].fed
    await r.advance(400)
    assert r.ears[0].fed == fed
    await r.close()


async def test_wrong_band_number_refused(tmp_path):
    from tacit.band import use_kit

    use_kit()
    from vexo_open import Band, SimTransport

    other = TEAM_BANDS[0]
    band = await Band.connect(other, transport=SimTransport(other, realtime=False))
    b = br.Bridge(make_settings(tacit_band=BAND), band, ears_factory=FakeEars,
                  state_path=tmp_path / "s.json", echo=lambda s: None)
    with pytest.raises(RuntimeError, match="wrong band"):
        await b.start()
    await band.disconnect()


def test_deepgram_ears_query_has_diarize_keyterms_and_opt_out():
    ears = br.deepgram_ears(lambda p: None, ["Maya", "Acme Corp"],
                            make_settings(deepgram_stt_model="nova-3"))
    q = ears.query
    assert ("diarize", "true") in q and ("mip_opt_out", "true") in q
    assert ("model", "nova-3") in q and ("endpointing", 300) in q
    assert [v for k, v in q if k == "keyterm"] == ["Maya", "Acme Corp"]
    from urllib.parse import urlencode

    assert urlencode(q).count("keyterm=") == 2


def test_sim_ears_plays_its_script():
    got = []
    e = br.SimEars(got.append)
    for _ in range(br.SimEars.PACKETS_PER_LINE * 2):
        e.feed(b"x")
    assert [p.speaker for p in got] == [0, 1] and got[0].text.startswith("When I report")


async def test_run_bridge_sim_end_to_end(tmp_path):
    lines = []
    stop = asyncio.Event()
    settings = make_settings(tacit_band=BAND, tacit_data_dir=tmp_path / "data")
    task = asyncio.create_task(br.run_bridge(settings, sim=True, echo=lines.append, stop=stop))
    await asyncio.sleep(1.5)
    stop.set()
    await asyncio.wait_for(task, 20)
    assert any("pretend speech engine" in line for line in lines)
    assert br.SOUND_NOTICE in lines


def test_cli_bridge_needs_band(monkeypatch):
    from typer.testing import CliRunner

    from tacit import cli

    r = CliRunner().invoke(cli.app, ["bridge", "--sim"])
    assert r.exit_code == 1 and "TACIT_BAND" in r.output


async def test_motion_sessions_are_uploaded_as_summaries(tmp_path):
    from tacit.motion_test import synthetic

    r = await rig(tmp_path)
    r.sim.play_motion(list(synthetic("drawing", 150)))
    for _ in range(150):
        await r.advance(1000, step=1000)
    await r.bridge.close()
    moments = [m for batch in r.server.named("moments") for m in batch]
    assert [m["kind"] for m in moments] == ["drawing"]
    assert set(moments[0]) == {"kind", "started_at", "ended_at", "confidence"}
    assert not r.bridge.muted            # drawing never looks like the mute gesture
    await r.band.disconnect()


def test_gesturing_becomes_presenting_only_with_speech(tmp_path):
    from tacit.motion import Session

    b = br.Bridge.__new__(br.Bridge)
    b.pending_moments = []
    b.speech_windows = __import__("collections").deque()
    b.add_session(Session("gesturing", 1000.0, 1300.0, 0.8))
    assert b.pending_moments == []
    b.speech_windows.extend(1000.0 + 10 * i for i in range(30))
    b.add_session(Session("gesturing", 1000.0, 1300.0, 0.8))
    assert b.pending_moments[0]["kind"] == "presenting"
    b.add_session(Session("gesturing", 1000.0, 1100.0, 0.8))   # under 3 minutes
    assert len(b.pending_moments) == 1


async def test_bridge_writes_health_file(tmp_path):
    import json

    r = await rig(tmp_path)
    await r.bridge.post_state()
    h = json.loads((tmp_path / "data" / "bridge-health.json").read_text())
    assert h["band_connected"] and h["listening"] and not h["muted"]
    await r.close()
