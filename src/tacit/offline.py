"""Offline buffering on the bridge (SPEC §13.7).

With no internet the band's Opus packets go to `data/bridge/<date>/<hh>.opus-packets`
(length-prefixed records: an 8-byte time and a 2-byte length, then the packet), capped at
BRIDGE_BUFFER_MB and 24 h, oldest dropped first. Motion sessions and gesture events queue in
`data/bridge/queue.jsonl`. Mute still works offline (it is local) and a rewind also deletes
buffered audio. Back online the buffer is transcribed with Deepgram's prerecorded API
(`diarize=true`), the segments are uploaded, **then** the audio is deleted. Retries back off
exponentially up to 5 minutes.
"""

from __future__ import annotations

import json
import logging
import struct
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import Settings, require

log = logging.getLogger("tacit.offline")

RECORD = struct.Struct(">dH")   # time (s since 1970), packet length
MAX_AGE_S = 24 * 3600
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 300.0
PACKET_S = 0.02                  # one Opus packet is 20 ms of sound
SUFFIX = ".opus-packets"
ENFORCE_EVERY = 100


class AudioBuffer:
    def __init__(self, root: Path, cap_mb: float = 500, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.cap_bytes = int(cap_mb * 1024 * 1024)
        self.clock = clock
        self._added = 0

    def _path(self, t: float) -> Path:
        d = datetime.fromtimestamp(t, UTC)
        return self.root / d.strftime("%Y-%m-%d") / f"{d:%H}{SUFFIX}"

    def files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(self.root.glob(f"*/*{SUFFIX}"))

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.files())

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes() / (1024 * 1024), 2)

    def add(self, packet: bytes, t: float | None = None) -> None:
        if not packet or len(packet) > 0xFFFF:
            return
        t = self.clock() if t is None else t
        path = self._path(t)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as f:
            f.write(RECORD.pack(t, len(packet)) + bytes(packet))
        self._added += 1
        if self._added % ENFORCE_EVERY == 0:   # about every 2 s of sound
            self.enforce()

    def enforce(self) -> None:
        """Drop files older than 24 h, then the oldest until under the cap."""
        cut = self.clock() - MAX_AGE_S
        for p in self.files():
            recs = read_records(p)
            if not recs or recs[-1][0] < cut:   # its newest packet is over 24 h old
                p.unlink(missing_ok=True)
        files = self.files()
        total = sum(p.stat().st_size for p in files)
        while files and total > self.cap_bytes:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            log.info("buffer full: dropped the oldest hour")
        self._tidy()

    def rewind(self, since: float) -> int:
        """Delete buffered audio from `since` on (a mute's rewind). Returns packets dropped."""
        dropped = 0
        for p in self.files():
            recs = read_records(p)
            keep = [(t, pk) for t, pk in recs if t < since]
            if len(keep) == len(recs):
                continue
            dropped += len(recs) - len(keep)
            if keep:
                write_records(p, keep)
            else:
                p.unlink(missing_ok=True)
        self._tidy()
        return dropped

    def _tidy(self) -> None:
        if not self.root.is_dir():
            return
        for d in self.root.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()


def read_records(path: Path) -> list[tuple[float, bytes]]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    out, at = [], 0
    while at + RECORD.size <= len(data):
        t, n = RECORD.unpack_from(data, at)
        at += RECORD.size
        if at + n > len(data):
            break   # a cut-off last record (power lost mid-write)
        out.append((t, data[at:at + n]))
        at += n
    return out


def write_records(path: Path, recs: list[tuple[float, bytes]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(b"".join(RECORD.pack(t, len(pk)) + pk for t, pk in recs))
    tmp.replace(path)


class EventQueue:
    """Motion sessions and gesture events waiting for the internet: one JSON object a line."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def add(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def items(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text().splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class Backoff:
    """Exponential backoff: 1 s, 2 s, 4 s ... at most 5 minutes; reset on success."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.delay = 0.0
        self.next_at = 0.0

    def ready(self) -> bool:
        return self.clock() >= self.next_at

    def failed(self) -> None:
        self.delay = min(BACKOFF_MAX_S, max(BACKOFF_START_S, self.delay * 2))
        self.next_at = self.clock() + self.delay

    def ok(self) -> None:
        self.delay = 0.0
        self.next_at = 0.0


# ---- Deepgram prerecorded ---------------------------------------------------------------------

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def to_ogg(packets: list[bytes]) -> bytes:
    """Raw Opus packets → an Ogg Opus file (the kit's OggOpusWriter, in memory)."""
    from .band import use_kit

    use_kit()
    from ogg_opus import OggOpusWriter  # vexo-open-kit/examples/python/ogg_opus.py

    chunks: list[bytes] = []

    class Sink:
        def write(self, b: bytes) -> None:
            chunks.append(bytes(b))

    w = OggOpusWriter(Sink())
    for i, pk in enumerate(packets):
        w.write(i & 0xFFFF, pk)
    w.close()
    return b"".join(chunks)


class DeepgramPrerecorded:
    """`transcribe(packets) -> [{start, end, speaker, text}]` in seconds from the first packet."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self._key = require(settings.deepgram_api_key, "DEEPGRAM_API_KEY")
        self.model = settings.deepgram_stt_model
        self._http = http

    async def transcribe(self, packets: list[bytes]) -> list[dict[str, Any]]:
        params = [("model", self.model), ("diarize", "true"), ("utterances", "true"),
                  ("smart_format", "true"), ("mip_opt_out", "true")]
        headers = {"Authorization": f"Token {self._key}", "Content-Type": "audio/ogg"}
        body = to_ogg(packets)
        if self._http is not None:
            r = await self._http.post(DEEPGRAM_URL, params=params, content=body, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=120) as http:
                r = await http.post(DEEPGRAM_URL, params=params, content=body, headers=headers)
        if not r.is_success:
            raise RuntimeError(f"deepgram status {r.status_code}")
        data = r.json()
        out = []
        for u in (data.get("results") or {}).get("utterances") or []:
            text = str(u.get("transcript") or "").strip()
            if text:
                out.append({"start": float(u.get("start") or 0), "end": float(u.get("end") or 0),
                            "speaker": u.get("speaker") if isinstance(u.get("speaker"), int)
                            else None, "text": text})
        return out


def segments_from(file_recs: list[tuple[float, bytes]],
                  utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place each utterance in real time by the packet it starts and ends in."""
    if not file_recs:
        return []

    def at(sec: float) -> float:
        i = min(len(file_recs) - 1, max(0, int(sec / PACKET_S)))
        return file_recs[i][0]

    out = []
    for u in utterances:
        started, ended = at(u["start"]), at(u["end"])
        out.append({"started_at": datetime.fromtimestamp(started, UTC).isoformat(),
                    "ended_at": datetime.fromtimestamp(max(started, ended), UTC).isoformat(),
                    "speaker": u.get("speaker"), "text": u["text"], "level": None})
    return out


async def drain(buffer: AudioBuffer, transcriber: Any, upload: Callable[[list], Any]) -> int:
    """Transcribe each buffered file, upload its segments, then delete it. Raises on failure
    (the caller backs off); a file is deleted only after its upload succeeded."""
    done = 0
    for path in buffer.files():
        recs = read_records(path)
        if recs:
            utterances = await transcriber.transcribe([pk for _, pk in recs])
            segs = segments_from(recs, utterances)
            if segs:
                await upload(segs)
        path.unlink(missing_ok=True)
        done += 1
    buffer._tidy()
    return done
