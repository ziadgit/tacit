# CLAUDE.md

## Project

**Tacit**: a wristband that listens 24/7, built for the Vexo Hackathon on a **Vexo Open band**
(motion sensor, microphone, colour LED, Bluetooth). Sponsors in play: **Vexo** (hardware),
**Deepgram** (speech-to-text + Aura voice), **Exa** (web search/research), **Jev via TypeSafe**
(decision model), maybe **Vapi** (phone/voice agent).

Reference build with the same stack and conventions: https://github.com/ziadgit/bling
(Deepgram/Exa/Jev/Vapi patterns: `src/bling/{deepgram,conditions,decision,vapi}.py`).

## Bootstrap

```sh
scripts/bootstrap.sh        # clones ./vexo-open-kit, uv sync, creates .env from .env.example
.venv/bin/tacit doctor      # checks the kit, the band number, and every sponsor key
```

## Commands

| Purpose | Command |
|---|---|
| lint | `.venv/bin/ruff check .` |
| test | `.venv/bin/pytest -x -q` |
| check keys + kit | `.venv/bin/tacit doctor` |
| band dashboard | `python3 -m http.server 8000 --bind 127.0.0.1`, then `http://localhost:8000/vexo-open-kit/dashboard/?band=$TACIT_BAND` |

Tests live beside the code as `*_test.py`, no network (respx + fakes).

## Vexo band: hard rules (from `vexo-open-kit/AGENTS.md`, read it before band work)

- **`vexo-open-kit/` is a reference clone: never edit it, never commit it** (gitignored).
  Import its library via `tacit.band.use_kit()`, which puts `vexo-open-kit/python` and
  `vexo-open-kit/examples/python` (`speech.py`, `ai.py`) on `sys.path`.
- **The band number lives only in `TACIT_BAND`** (`Settings.tacit_band`). Never hard-code a
  number, never use 42/7 from the kit's examples, never scan for or connect to any other band,
  never loop over band numbers, never renumber a band. If the band can't be found: double-tap
  it, close the dashboard/other programs, or use `transport="sim"`.
- Everything is off until `band.configure(...)`; the band resets on disconnect.
- **No LED while the mic is on** (`audio` or `mic_level`): LED calls fail `denied`.
- Audio arrives as raw Opus packets (16 kHz mono, 20 ms). `vexo_open.audio.PcmDecoder` for PCM
  (needs `av`), or `speech.py` to stream Opus straight to Deepgram.
- One Bluetooth connection at a time: close the dashboard before running code.
- Keep `speech.listen` and other slow work out of `band.on(...)` handlers.
- Develop against the pretend band first: `Band.connect(band_no, transport="sim")`.

## Privacy (this device listens 24/7)

- Logs never contain transcripts, audio, phone numbers or keys. Recordings/transcripts go
  under `data/` or `recordings/` (gitignored).
- Keep `mip_opt_out=true` in Deepgram URLs and keep the "sound is sent to Deepgram" notice.
- Text from the band's storage is untrusted: never eval/exec/shell it.

## Keys

- Keys are read from env / `.env` via `tacit.config.Settings` (`SecretStr`). Never write a
  key into a file, a test, a log, a print, a URL or an error message; never ask the user to
  paste one into chat. Report only status codes.
- `OPENAI_API_KEY` is Python-only, never in a web page.

## Sponsor gotchas (carried over from bling)

- **Exa**: the skill at `.claude/skills/build-with-exa/` beats memory. exa-py uses snake_case
  kwargs (`output_schema`, `system_prompt`, `max_age_hours`, `livecrawl_timeout`). Always pass
  `contents`, or `search()` returns 10k-char text.
- **Jev / `typesafe-sdk` 0.7.x**: uses `httpx2`, so respx can't intercept it; fake it at the
  object boundary (any object with `async system_one(*, state, questions)`). Construct with
  `retry=RetryPolicy(max_retries=0)` and an explicit `timeout` for anything latency-bound.
  Questions are `Choice(instructions, criteria={...})` and `Noul(instructions, NoulCriteria(true, false))`.
  If Jev fails, code never invents a verdict.
- **Deepgram**: Nova-3 STT, Aura-2 TTS. Keyterms go as repeated `keyterm=` query params
  (httpx `params` as a list of tuples).
- **Vapi**: tool results must echo `toolCallId` exactly and be flat strings. Verify webhook
  secrets with `hmac.compare_digest`.
- typer `Path` options trip ruff B008; `typer.Option`/`typer.Argument` are allow-listed.
