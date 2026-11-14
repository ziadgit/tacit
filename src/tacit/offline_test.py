import json

import httpx
import respx

from tacit import offline as off
from tacit.bridge_test import BAND, FakeServer, rig
from tacit.testing import make_settings


class Clock:
    def __init__(self, t=1_794_700_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_buffer_layout_and_records(tmp_path):
    clock = Clock()
    buf = off.AudioBuffer(tmp_path / "bridge", 500, clock)
    buf.add(b"\xb8abc")
    clock.t += 3600
    buf.add(b"\xb8defg")
    files = buf.files()
    assert len(files) == 2 and all(p.name.endswith(".opus-packets") for p in files)
    assert files[0].parent.name.count("-") == 2               # data/bridge/<date>/<hh>...
    assert off.read_records(files[0]) == [(1_794_700_000.0, b"\xb8abc")]
    files[1].write_bytes(files[1].read_bytes() + b"\x00\x01")  # a cut-off record is skipped
    assert len(off.read_records(files[1])) == 1


def test_size_cap_drops_oldest_first(tmp_path):
    clock = Clock()
    buf = off.AudioBuffer(tmp_path / "bridge", cap_mb=0.01, clock=clock)   # ~10 kB
    paths = []
    for _ in range(4):                                  # 4 hours of ~5 kB each
        paths.append(buf._path(clock.t))
        for _ in range(off.ENFORCE_EVERY):
            buf.add(b"\xb8" + b"x" * 40)
        clock.t += 3600
    assert buf.size_bytes() <= buf.cap_bytes
    kept = buf.files()
    assert kept and kept[-1] == paths[-1]               # the newest hour stays
    assert paths[0] not in kept                         # the oldest went first


def test_older_than_24h_is_dropped(tmp_path):
    clock = Clock()
    buf = off.AudioBuffer(tmp_path / "bridge", 500, clock)
    buf.add(b"\xb8old")
    clock.t += 25 * 3600
    buf.add(b"\xb8new")
    buf.enforce()
    recs = [r for p in buf.files() for r in off.read_records(p)]
    assert [pk for _, pk in recs] == [b"\xb8new"]


def test_rewind_deletes_buffered_audio(tmp_path):
    clock = Clock()
    buf = off.AudioBuffer(tmp_path / "bridge", 500, clock)
    for i in range(30):
        buf.add(b"\xb8" + bytes([i]), clock.t + i)
    assert buf.rewind(clock.t + 15) == 15
    recs = [r for p in buf.files() for r in off.read_records(p)]
    assert len(recs) == 15 and max(t for t, _ in recs) < clock.t + 15
    buf.rewind(0)
    assert buf.files() == []


def test_event_queue(tmp_path):
    q = off.EventQueue(tmp_path / "queue.jsonl")
    q.add([{"kind": "drawing"}])
    q.add([{"kind": "kept"}])
    with q.path.open("a") as f:
        f.write("not json\n")
    assert [i["kind"] for i in q.items()] == ["drawing", "kept"]
    q.clear()
    assert q.items() == []


def test_backoff():
    clock = Clock(0)
    b = off.Backoff(clock)
    assert b.ready()
    delays = []
    for _ in range(12):
        b.failed()
        delays.append(b.delay)
    assert delays[:4] == [1, 2, 4, 8] and max(delays) == 300
    assert not b.ready()
    clock.t += 300
    assert b.ready()
    b.ok()
    assert b.delay == 0 and b.ready()


def test_to_ogg_is_an_ogg_file():
    data = off.to_ogg([b"\xb8" + b"\x00" * 10] * 60)
    assert data.startswith(b"OggS") and b"OpusHead" in data


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    async def transcribe(self, packets):
        self.calls.append(len(packets))
        return [{"start": 0.0, "end": 0.1, "speaker": 0, "text": "said offline"}]


async def test_drain_uploads_then_deletes(tmp_path):
    clock = Clock()
    buf = off.AudioBuffer(tmp_path / "bridge", 500, clock)
    for i in range(10):
        buf.add(b"\xb8" + bytes([i]), clock.t + i * 0.02)
    uploaded = []

    async def failing(segs):
        raise ConnectionError

    import pytest

    with pytest.raises(ConnectionError):
        await off.drain(buf, FakeTranscriber(), failing)
    assert buf.files()                                          # kept: nothing was uploaded

    async def upload(segs):
        uploaded.extend(segs)

    assert await off.drain(buf, FakeTranscriber(), upload) == 1
    assert buf.files() == []
    assert uploaded[0]["text"] == "said offline" and uploaded[0]["speaker"] == 0
    assert uploaded[0]["started_at"].startswith("2026-")


@respx.mock
async def test_deepgram_prerecorded_request():
    route = respx.post(off.DEEPGRAM_URL).mock(return_value=httpx.Response(200, json={
        "results": {"utterances": [{"start": 0.5, "end": 1.2, "speaker": 1,
                                    "transcript": "hello there"}]}}))
    t = off.DeepgramPrerecorded(make_settings(deepgram_api_key="dg-sekrit"))
    out = await t.transcribe([b"\xb8\x00"] * 10)
    assert out == [{"start": 0.5, "end": 1.2, "speaker": 1, "text": "hello there"}]
    req = route.calls.last.request
    assert req.headers["authorization"] == "Token dg-sekrit"
    assert req.headers["content-type"] == "audio/ogg"
    q = req.url.params
    assert q["diarize"] == "true" and q["mip_opt_out"] == "true" and q["model"] == "nova-3"
    assert req.content.startswith(b"OggS")


class FailingEars:
    def __init__(self, on_piece, keyterms):
        pass

    def start(self, on_text=None):
        raise OSError("no internet")


async def test_bridge_buffers_offline_and_drains_back_online(tmp_path):
    server = FakeServer()
    server.fail = True
    r = await rig(tmp_path, server=server)
    # Deepgram can't be reached: the sound goes to the buffer
    r.bridge.ears_factory = FailingEars
    await r.bridge.mute("test")
    r.bridge.unmute_until = r.bridge.clock() + 5
    await r.bridge.unmute("test")
    assert r.bridge.offline and r.mic_on
    await r.advance(2000)
    assert r.bridge.buffer.files() and r.bridge.buffer_mb >= 0
    r.sim.tap("double-tap")
    await r.advance(100)
    await r.bridge.tick()                                       # fails: queued to disk
    assert [i["kind"] for i in r.bridge.queue.items()] == ["kept"]
    # mute works offline, and its rewind deletes the last 15 s of buffered audio
    await r.bridge.mute("offline gesture")
    assert not r.mic_on and r.bridge.buffer.files() == []
    # back online
    server.fail = False
    r.bridge.transcriber = FakeTranscriber()
    r.bridge.backoff.ok()
    await r.bridge.flush()
    assert [m["kind"] for batch in server.named("moments") for m in batch] == ["kept"]
    assert r.bridge.queue.items() == []
    assert 15 in server.named("rewind")
    await r.close()


async def test_bridge_drains_buffer_after_upload(tmp_path):
    server = FakeServer()
    r = await rig(tmp_path, server=server)
    r.bridge.transcriber = FakeTranscriber()
    t = r.bridge.clock()
    for i in range(50):
        r.bridge.buffer.add(b"\xb8" + bytes([i]), t - 100 + i * 0.02)
    await r.bridge.flush()
    texts = [s["text"] for segs in server.named("segments") for s in segs]
    assert texts == ["said offline"] and r.bridge.buffer.files() == []
    state = r.bridge.state()
    assert state["buffer_mb"] == 0 and state["last_sync"]
    await r.close()


def test_band_is_a_team_band():
    from tacit.config import TEAM_BANDS

    assert BAND in TEAM_BANDS
    assert json.dumps(TEAM_BANDS)
