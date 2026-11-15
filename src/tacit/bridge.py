"""The band bridge (SPEC §13.1, §13.2): the program connected to one of the team's bands.

It connects to TACIT_BAND only, streams motion and (while listening) sound, sends the sound to
Deepgram with the kit's `speech` module, uploads final transcript segments and motion moments
to the tacit server, and owns **mute**:

- mute: an X or a figure 8 in the air, a stop phrase, or the PWA's command. The mic is off at
  once (before anything else), whatever was not uploaded from the last MUTE_REWIND_S is dropped
  and the server is asked to rewind the same, the LED blinks white twice and goes off, and the
  muted state is saved to data/bridge-state.json (a restart comes back muted). Mute is local:
  it works with no internet.
- unmute: the same gesture (matched with the stricter UNMUTE_LIMIT), then a double-tap within
  3 s; or "unmute" in the PWA. Mute never times out.
- double-tap while listening = "keep that": the last minute becomes a `kept` moment.

The kit is imported lazily (`use_kit()`), so the server never loads it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import re
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from . import gestures, motion
from .config import Settings, require, require_band
from .offline import AudioBuffer, Backoff, DeepgramPrerecorded, EventQueue, drain

log = logging.getLogger("tacit.bridge")

STOP_PHRASE = re.compile(
    r"\b(stop recording|turn (it|that) off|don'?t record|off the record|mute (it|that))\b",
    re.IGNORECASE)
# The kit's line (speech.py), printed before the microphone first starts.
SOUND_NOTICE = ("Note: while this runs, everything the band's microphone hears is sent over the "
                "internet to Deepgram (deepgram.com). Tell the people near the band.")
UNMUTE_WINDOW_S = 3.0
BLINK_S = 0.8
POLL_COMMANDS_S = 2.0
POST_STATE_S = 10.0
LEVEL_KEEP_S = 600
MIC_LEVEL_S = 0.1
MAX_KEYTERMS = 20


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


@dataclass
class Piece:
    """One final piece of text from the speech engine."""
    text: str
    started: float
    ended: float
    speaker: int | None = None


# ---- state file ----------------------------------------------------------------------------


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


# ---- the server ---------------------------------------------------------------------------


class ServerClient:
    """The tacit server's bridge API, with the bridge token. Errors raise httpx.HTTPError."""

    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx.AsyncClient(timeout=10)

    async def _call(self, method: str, path: str, body: Any = None) -> Any:
        r = await self._http.request(method, self.base + path, json=body, headers=self._headers)
        r.raise_for_status()
        return r.json() if r.content else None

    async def state(self, state: dict[str, Any]) -> None:
        await self._call("POST", "/api/bridge/state", state)

    async def commands(self) -> dict[str, Any]:
        return await self._call("GET", "/api/bridge/commands")

    async def config(self) -> dict[str, Any]:
        return await self._call("GET", "/api/bridge/config")

    async def segments(self, segments: list[dict[str, Any]]) -> None:
        await self._call("POST", "/api/bridge/segments", {"segments": segments})

    async def moments(self, moments: list[dict[str, Any]]) -> None:
        await self._call("POST", "/api/bridge/moments", {"moments": moments})

    async def rewind(self, seconds: int) -> None:
        await self._call("POST", "/api/bridge/rewind", {"seconds": seconds})

    async def aclose(self) -> None:
        await self._http.aclose()


# ---- speech engines -------------------------------------------------------------------------


def deepgram_ears(on_piece: Callable[[Piece], None], keyterms: list[str],
                  settings: Settings) -> Any:
    """The kit's Deepgram engine, with diarization: final pieces carry their speaker."""
    from .band import use_kit

    use_kit()
    import speech  # the kit's examples/python/speech.py

    class DiarizedDeepgram(speech.DeepgramSpeech):
        def __init__(self) -> None:
            super().__init__(model=settings.deepgram_stt_model, endpointing=300, diarize="true")
            # Repeated keyterm= parameters: urlencode() takes a list of pairs.
            self.query = [*self.query.items(), *(("keyterm", k) for k in keyterms)]
            self._speakers: list[int] = []
            self._began: float | None = None

        def _message(self, message: dict) -> None:
            if message.get("type") == "Results" and message.get("is_final"):
                alt = (message.get("channel", {}).get("alternatives") or [{}])[0]
                for w in alt.get("words") or []:
                    if isinstance(w.get("speaker"), int):
                        self._speakers.append(w["speaker"])
                if self._began is None and alt.get("transcript"):
                    dur = message.get("duration")
                    self._began = time.time() - (dur if isinstance(dur, int | float) else 0)
            super()._message(message)

        def _say(self, text, final) -> None:
            super()._say(text, final)
            text = (text or "").strip()
            if final and text:
                spk = statistics.mode(self._speakers) if self._speakers else None
                ended = time.time()
                on_piece(Piece(text, self._began or ended, ended, spk))
                self._speakers, self._began = [], None

    return DiarizedDeepgram()


class SimEars:
    """A pretend speech engine for `tacit bridge --sim` without a Deepgram key: every 8 s of
    sound it 'hears' the next line of a short script, as two speakers."""

    SCRIPT = (
        (0, "When I report results I open the update with the number, then the story."),
        (1, "Why the number first?"),
        (0, "Because people forget the story but they remember forty percent."),
        (1, "I'll try that in tomorrow's update."),
    )
    PACKETS_PER_LINE = 400  # 20 ms packets: 8 s

    def __init__(self, on_piece: Callable[[Piece], None]):
        self.on_piece = on_piece
        self.n = 0
        self.line = 0

    def start(self, on_text=None) -> SimEars:
        return self

    def feed(self, packet, seq=None) -> None:
        self.n += 1
        if self.n % self.PACKETS_PER_LINE == 0:
            speaker, text = self.SCRIPT[self.line % len(self.SCRIPT)]
            self.line += 1
            t = time.time()
            self.on_piece(Piece(text, t - 4, t, speaker))

    def stop(self, wait: float = 0) -> str:
        return ""


# ---- the bridge -----------------------------------------------------------------------------


class Bridge:
    def __init__(self, settings: Settings, band: Any, *, server: Any = None,
                 ears_factory: Callable[[Callable[[Piece], None], list[str]], Any] | None = None,
                 templates: gestures.Templates | None = None,
                 state_path: Path | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Any] = asyncio.sleep,
                 echo: Callable[[str], None] = print, transcriber: Any = None):
        self.settings = settings
        self.band_no = require_band(settings)
        self.band = band
        self.server = server
        self.ears_factory = ears_factory or (lambda on, kt: deepgram_ears(on, kt, settings))
        # The kit's Deepgram engine prints the sound notice itself when it starts.
        self.engine_prints_notice = ears_factory is None
        self.templates = templates if templates is not None else gestures.load_templates(
            settings.tacit_data_dir / "gestures.json")   # built-ins + `tacit gestures record`
        self.detector = gestures.GestureDetector(self.templates, gestures.MUTE_LIMIT)
        self.state_path = state_path or settings.tacit_data_dir / "bridge-state.json"
        self.clock = clock
        self.sleep = sleep
        self.echo = echo
        self.muted = bool(load_state(self.state_path).get("muted", False))
        self.listening = False
        self.connected = False
        self.battery: float | None = None
        self.ears: Any = None
        self.noticed = False
        self.unmute_until = 0.0
        self.keyterms: list[str] = []
        self.kinds_off: set[str] = set()
        self.levels: deque[tuple[float, float]] = deque()
        self.pieces: queue.SimpleQueue[Piece] = queue.SimpleQueue()
        self.pending_segments: list[dict[str, Any]] = []
        self.pending_moments: list[dict[str, Any]] = []
        self.pending_rewind = 0
        self.motion = motion.SessionTracker()                  # motion detectors (§13.6)
        self.gesturing: list[motion.Session] = []
        self.speech_windows: deque[float] = deque(maxlen=2000)  # when final speech arrived
        self.tasks: set[asyncio.Task] = set()
        self._last_poll = float("-inf")
        self._last_state = float("-inf")
        self.last_sync: float | None = None
        root = settings.tacit_data_dir / "bridge"
        self.buffer = AudioBuffer(root, settings.bridge_buffer_mb, clock)   # offline (§13.7)
        self.queue = EventQueue(root / "queue.jsonl")
        self.backoff = Backoff(clock)
        self.offline = False
        if transcriber is None and settings.deepgram_api_key is not None:
            transcriber = DeepgramPrerecorded(settings)
        self.transcriber = transcriber

    @property
    def buffer_mb(self) -> float:
        return self.buffer.size_mb

    # ---- set-up -----------------------------------------------------------------------------

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self) -> None:
        if self.band.number != self.band_no:
            raise RuntimeError("connected to the wrong band")
        self.band.on("motion", self.on_motion)
        self.band.on("double-tap", self.on_double_tap)
        self.band.on("audio", self.on_audio)
        self.band.on("mic-level", self.on_mic_level)
        self.band.on("battery", self.on_battery)
        self.band.on("reconnected", self.on_reconnected)
        self.band.on("disconnect", self.on_disconnect)
        self.connected = True
        await self.load_config()
        await self.setup()
        if not self.muted:
            await self.start_listening()
        else:
            self.echo("tacit bridge: muted (as before). Draw an X or a figure 8, then double-tap, "
                      "to unmute.")

    async def load_config(self) -> None:
        if self.server is None:
            return
        try:
            cfg = await self.server.config()
        except Exception:  # noqa: BLE001 - offline: keep going without keyterms
            return
        self.keyterms = [str(k) for k in (cfg or {}).get("keyterms", [])][:MAX_KEYTERMS]
        self.kinds_off = set((cfg or {}).get("kinds_off", []))

    async def setup(self) -> None:
        """Everything is off after a (re)connect: set it all up again."""
        await self.band.set_motion(accel_range=8, gyro_range=1000)
        # No `activity` (steps): nothing reads it, and with a still band the kit's stream watch
        # mistook its silence for "another program on USB took this stream".
        streams: dict[str, Any] = dict(events=True, motion=100, sensors="both", battery=60)
        if self.listening and not self.muted:
            streams.update(audio=True, mic_level=MIC_LEVEL_S)
        else:
            streams.update(audio=False, mic_level=False)
        await self.band.configure(**streams)

    async def start_listening(self) -> None:
        if not self.noticed and not self.engine_prints_notice:
            self.echo(SOUND_NOTICE)
            self.noticed = True
        self.start_ears()
        await self.band.configure(audio=True, mic_level=MIC_LEVEL_S)
        self.listening = True

    def start_ears(self) -> None:
        """Start the live speech engine; with no internet, sound goes to the buffer instead."""
        try:
            self.ears = self.ears_factory(self.pieces.put, self.keyterms)
            self.ears.start()
            self.offline = False
        except Exception as e:  # noqa: BLE001 - offline: buffer the sound, mute still works
            log.info("speech offline (%s): buffering", type(e).__name__)
            self.ears = None
            self.offline = True

    # ---- mute / unmute ------------------------------------------------------------------------

    async def mute(self, reason: str) -> None:
        if self.muted:
            return
        self.muted = True
        self.listening = False
        try:
            await self.band.configure(audio=False, mic_level=False)   # the mic goes off first
        finally:
            save_state(self.state_path, {"muted": True})
        log.info("muted (%s)", reason)
        self.echo(f"tacit bridge: muted ({reason})")
        ears, self.ears = self.ears, None
        if ears is not None:
            await asyncio.get_running_loop().run_in_executor(None, _stop_quietly, ears)
        self.drop_recent(self.settings.mute_rewind_s)
        self.pending_rewind = max(self.pending_rewind, self.settings.mute_rewind_s)
        await self.blink()
        await self.flush()
        await self.post_state()   # tell the app at once, not at the next 10 s report

    async def blink(self) -> None:
        try:
            await self.band.set_led("#ffffff", pattern="blink", period=200)
            await self.sleep(BLINK_S)
            if self.muted:
                await self.band.led_off()
        except Exception as e:  # noqa: BLE001 - the light is a courtesy; mute already happened
            log.warning("led: %s", type(e).__name__)

    async def unmute(self, reason: str) -> None:
        if not self.muted:
            return
        self.muted = False
        self.unmute_until = 0.0
        save_state(self.state_path, {"muted": False})
        log.info("unmuted (%s)", reason)
        self.echo(f"tacit bridge: listening again ({reason})")
        await self.start_listening()
        await self.post_state()

    def drop_recent(self, seconds: float) -> None:
        cut = self.clock() - seconds
        self.buffer.rewind(cut)
        self.pending_segments = [s for s in self.pending_segments if s["_ended"] < cut]
        while True:   # pieces still waiting in the queue are recent by definition
            try:
                self.pieces.get_nowait()
            except queue.Empty:
                break

    # ---- band handlers (short: the slow work is spawned) --------------------------------------

    def on_motion(self, m: Any) -> None:
        label = self.detector.feed(m, now=getattr(m, "t", None))   # the gesture check comes first
        if label is not None:
            self.on_gesture(label, self.detector.last.distance if self.detector.last else 1.0)
        t = getattr(m, "time", None)
        t = float(t) if isinstance(t, int | float) else self.clock()
        self.last_motion_t = t
        for session in self.motion.feed(m, t, speech_active=self.speech_active(t)):
            self.add_session(session)

    def speech_active(self, t: float) -> bool:
        return bool(self.speech_windows) and t - self.speech_windows[-1] <= 10.0

    def add_session(self, s: motion.Session) -> None:
        """Only {kind, started_at, ended_at, confidence} leaves the bridge; raw motion never."""
        kind = s.kind
        if kind == "gesturing":
            # gesturing feeds `presenting`: >= 3 min of it while speech kept coming
            spoke = [t for t in self.speech_windows if s.started_at <= t <= s.ended_at]
            minutes = (s.ended_at - s.started_at) / 60
            if minutes < 3 or len(spoke) < minutes * 3:
                return
            kind = "presenting"
        self.pending_moments.append({"kind": kind, "started_at": iso(s.started_at),
                                     "ended_at": iso(s.ended_at), "confidence": s.confidence})

    def on_gesture(self, label: str, distance: float) -> None:
        if not self.muted:
            self._spawn(self.mute(f"gesture {label}"))
        elif distance <= gestures.UNMUTE_LIMIT:
            self.unmute_until = self.clock() + UNMUTE_WINDOW_S
            self.echo("tacit bridge: double-tap within 3 s to unmute")

    def on_double_tap(self, e: Any) -> None:
        if self.muted:
            if self.clock() <= self.unmute_until:
                self._spawn(self.unmute("gesture and double-tap"))
            return
        t = self.clock()
        self.pending_moments.append({"kind": "kept", "started_at": iso(t - 60),
                                     "ended_at": iso(t), "confidence": 1.0})

    def on_audio(self, a: Any) -> None:
        if not self.listening or self.muted:
            return
        if self.ears is not None and not self.offline:
            try:
                self.ears.feed(a)
                return
            except Exception as e:  # noqa: BLE001 - the stream dropped: buffer from here on
                log.info("speech dropped (%s): buffering", type(e).__name__)
                self.ears, self.offline = None, True
        packet = getattr(a, "opus", a)
        if isinstance(packet, bytes | bytearray):
            self.buffer.add(bytes(packet), self.clock())

    def on_mic_level(self, e: Any) -> None:
        db = getattr(e, "rms_db", None)
        if isinstance(db, int | float):
            t = self.clock()
            self.levels.append((t, float(db)))
            while self.levels and self.levels[0][0] < t - LEVEL_KEEP_S:
                self.levels.popleft()

    def on_battery(self, e: Any) -> None:
        p = getattr(e, "percent", None)
        if isinstance(p, int | float):
            self.battery = float(p)

    def on_reconnected(self, e: Any) -> None:
        self.connected = True
        self._spawn(self.setup())

    def on_disconnect(self, e: Any) -> None:
        self.connected = False
        self.detector.reset()

    # ---- segments, commands, uploads ----------------------------------------------------------

    def level_for(self, started: float, ended: float) -> float | None:
        vals = [db for t, db in self.levels if started - 0.2 <= t <= ended + 0.2]
        return statistics.median(vals) if vals else None

    async def take_pieces(self) -> None:
        while True:
            try:
                p = self.pieces.get_nowait()
            except queue.Empty:
                return
            if self.muted:
                continue
            if STOP_PHRASE.search(p.text):
                await self.mute("someone asked to stop")
                return
            self.speech_windows.append(p.ended)
            self.pending_segments.append({
                "started_at": iso(p.started), "ended_at": iso(p.ended), "speaker": p.speaker,
                "text": p.text, "level": self.level_for(p.started, p.ended), "_ended": p.ended})

    async def poll_commands(self) -> None:
        if self.server is None:
            return
        try:
            cmd = await self.server.commands()
        except Exception:  # noqa: BLE001 - offline: mute still works by gesture
            return
        if not isinstance(cmd, dict):
            return
        if cmd.get("muted") is True and not self.muted:
            await self.mute("from the app")
        elif cmd.get("muted") is False and cmd.get("changed") and self.muted:
            await self.unmute("from the app")

    def state(self) -> dict[str, Any]:
        return {"connected": self.connected, "listening": self.listening and not self.muted,
                "muted": self.muted, "battery": self.battery, "buffer_mb": self.buffer_mb,
                "last_sync": iso(self.last_sync) if self.last_sync is not None else None}

    def write_health(self) -> None:
        """For `/healthz` on the same machine (a Pi hub): what the bridge is doing right now."""
        st = self.state()
        health = {"band_connected": st["connected"], "listening": st["listening"],
                  "muted": st["muted"], "buffer_mb": st["buffer_mb"], "last_sync": st["last_sync"],
                  "at": time.time()}
        try:
            save_state(self.settings.tacit_data_dir / "bridge-health.json", health)
        except OSError as e:
            log.info("health file: %s", type(e).__name__)

    async def post_state(self) -> None:
        self.write_health()
        if self.server is None:
            return
        try:
            await self.server.state(self.state())
        except Exception:  # noqa: BLE001
            return

    async def flush(self) -> None:
        """Upload what is waiting. On failure it stays (moments in queue.jsonl) and is tried
        again with exponential backoff, at most every 5 minutes."""
        if self.server is None:
            return
        if not self.backoff.ready():
            return
        try:
            if self.pending_rewind:
                await self.server.rewind(self.pending_rewind)
                self.pending_rewind = 0
            if self.pending_segments:
                batch = self.pending_segments[:200]
                await self.server.segments([{k: v for k, v in s.items() if k != "_ended"}
                                            for s in batch])
                self.pending_segments = self.pending_segments[len(batch):]
            moments = [m for m in self.queue.items() + self.pending_moments
                       if m.get("kind") not in self.kinds_off]
            if moments:
                await self.server.moments(moments)
            self.queue.clear()
            self.pending_moments = []
            if self.transcriber is not None and self.buffer.files():
                n = await drain(self.buffer, self.transcriber, self.server.segments)
                log.info("offline buffer: %d files transcribed and deleted", n)
            self.backoff.ok()
            self.last_sync = self.clock()
        except Exception as e:  # noqa: BLE001
            self.queue.add(self.pending_moments)
            self.pending_moments = []
            self.backoff.failed()
            log.info("upload later (%s), in %.0fs", type(e).__name__, self.backoff.delay)
            return
        if self.offline and self.listening and not self.muted:
            self.start_ears()   # back online: live speech again

    async def tick(self) -> None:
        await self.take_pieces()
        t = self.clock()
        if t - self._last_poll >= POLL_COMMANDS_S:
            self._last_poll = t
            await self.poll_commands()
        await self.flush()
        if t - self._last_state >= POST_STATE_S:
            self._last_state = t
            await self.post_state()

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.2)
            except TimeoutError:
                pass
        await self.close()

    async def close(self) -> None:
        for task in list(self.tasks):
            await task
        for session in self.motion.flush(getattr(self, "last_motion_t", self.clock())):
            self.add_session(session)
        if self.ears is not None:
            _stop_quietly(self.ears)
            self.ears = None
        await self.take_pieces()
        await self.flush()


def _stop_quietly(ears: Any) -> None:
    try:
        ears.stop()
    except Exception as e:  # noqa: BLE001
        log.info("speech stop: %s", type(e).__name__)


# ---- `tacit bridge` -------------------------------------------------------------------------


async def run_bridge(settings: Settings, *, sim: bool, echo: Callable[[str], None] = print,
                     stop: asyncio.Event | None = None) -> None:
    from .band import use_kit

    number = require_band(settings)
    use_kit()
    from vexo_open import Band

    if sim:
        from vexo_open import audio

        from .band import KIT

        voice = audio.ogg_packets(KIT / "dashboard" / "speech" / "sample-speech.opus")
        band = await Band.connect(number, transport="sim", audio_packets=voice)
    else:
        band = await Band.connect(number, auto_reconnect=True)
    if band.number != number:
        await band.disconnect()
        raise RuntimeError("connected to the wrong band")
    server = None
    base = settings.tacit_server_url or settings.public_base_url
    if settings.tacit_bridge_token is not None and base:
        server = ServerClient(base, require(settings.tacit_bridge_token, "TACIT_BRIDGE_TOKEN"))
    else:
        echo("tacit bridge: no TACIT_BRIDGE_TOKEN / TACIT_SERVER_URL: nothing is uploaded "
             "(pair a band in the app first)")
    factory = None
    if sim and settings.deepgram_api_key is None:
        factory = lambda on, kt: SimEars(on)  # noqa: E731
        echo("tacit bridge: no DEEPGRAM_API_KEY, so a pretend speech engine plays a script")
    bridge = Bridge(settings, band, server=server, ears_factory=factory, echo=echo)
    stop = stop or asyncio.Event()
    try:
        await bridge.run(stop)
    finally:
        await band.disconnect()
        if server is not None:
            await server.aclose()
