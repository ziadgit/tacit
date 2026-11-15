# CLAUDE.md

## Project

**Tacit**: a wristband that listens 24/7, built for the Vexo Hackathon on a **Vexo Open band**
(motion sensor, microphone, colour LED, Bluetooth). Sponsors in play: **Vexo** (hardware),
**Deepgram** (speech-to-text + Aura voice), **Exa** (web search/research), **Jev via TypeSafe**
(decision model), maybe **Vapi** (phone/voice agent).

Reference build with the same stack and conventions: https://github.com/ziadgit/bling
(Deepgram/Exa/Jev/Vapi patterns: `src/bling/{deepgram,conditions,decision,vapi}.py`).

## Build docs

`SPEC.md` is the source of truth for the build (its §0 safety rules come first), and
`fix_plan.md` is the backlog. `PROMPT.md` runs the unattended build:
`claude --dangerously-skip-permissions -p "$(cat PROMPT.md)"`. Pages follow `design-system/README.md`.

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
- **The team owns two bands: 16 (`Vexo-HACK-16`) and 74 (`Vexo-HACK-74`).** They are listed
  once, in `tacit.config.TEAM_BANDS`; each laptop picks one with `TACIT_BAND` in `.env`
  (validated against `TEAM_BANDS`). Never hard-code a number elsewhere, never use 42/7 from the
  kit's examples, never scan for or connect to any band outside `TEAM_BANDS`, never loop over
  band numbers, never renumber a band. Each band takes one Bluetooth connection, so one laptop
  drives one band. If a band can't be found: double-tap it, close the dashboard/other
  programs, or use `transport="sim"`.
- Everything is off until `band.configure(...)`; the band resets on disconnect.
- **No LED while the mic is on** (`audio` or `mic_level`): LED calls fail `denied`.
- Audio arrives as raw Opus packets (16 kHz mono, 20 ms). `vexo_open.audio.PcmDecoder` for PCM
  (needs `av`), or `speech.py` to stream Opus straight to Deepgram.
- One Bluetooth connection at a time: close the dashboard before running code.
- Keep `speech.listen` and other slow work out of `band.on(...)` handlers.
- Develop against the pretend band first: `Band.connect(band_no, transport="sim")`.
- **Mute is safety-critical** (SPEC §13.2): an X or a figure 8 in the air, a stop phrase, or the
  PWA mutes at once (mic off, rewind the last 15 s). Unmuting needs the gesture plus a double-tap.
  Never weaken this path, and keep it working offline.

## Social: how Tacit knows about other bands

The app is social, but **awareness of other bands never happens over Bluetooth.** Each
person's own Tacit app (on their laptop, connected only to their own band) publishes what they
choose to share to the Tacit backend; everyone else learns about them from the backend.

- Opt-in only: nothing about a wearer leaves their app unless they turned sharing on, and
  they can turn it off and delete what was shared.
- Share derived data (e.g. topics, status, "in a conversation"), not raw audio or full
  transcripts. Never share data about bystanders the band overheard.
- Identity is the backend's (a user account linked to a band number by its owner), not
  "whatever band is nearby". A band number alone is not proof of who someone is.
- Our two bands (16, 74) are the test pair for every social feature.

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

## Gotchas

(Found during the build. Add one line each.)
- The CSP (`default-src 'self'`) blocks inline scripts, so `pwa/index.html` registers no SW itself: it names `/app/sw.js` + scope in `data-sw`/`data-scope` on the `app.js` script tag, and `app.js` registers it.
- `payments.create_checkout` also takes `product_name` (the "Follow <first name>'s skills on tacit" line), so fakes must accept it. A live Stripe key disables payments at startup (logged) instead of crashing the server.
- Dot-portrait eyes/mouth use the real `FACES.maya` cells (0-based: eyes row 7 cols 5 and 11, mouth row 10 cols 7–9); SPEC §17's "columns 4 and 10 / 6–8" is off by one against the template. Photo mode needs `photo_consent: true` in the POST body (403 without).
- The image runs as user `tacit` (uid 10001); a fresh Fly volume may mount root-owned, so if SQLite can't write, run `fly ssh console -C "chown -R 10001:10001 /data"` once (documented in the README, never run by the build).
- `/api/bridge/commands` answers `{"muted", "changed"}`: the bridge always obeys a mute but obeys an unmute only when `changed` (a PWA command it has not seen yet), so a stale "unmuted" never undoes a gesture mute. State reports make the stored `muted` follow the bridge unless a PWA command is pending. Bridge rate limit is in memory (240/min per device), not in the `events` table.
- The kit's `speech.DeepgramSpeech` drops speakers and urlencodes a dict, so `bridge.deepgram_ears` subclasses it (in tacit, the kit is untouched): `self.query` becomes a list of pairs for repeated `keyterm=`, and `_message`/`_say` are extended to attach the majority diarized speaker to each final piece. The bridge is async (`vexo_open.Band`) so tests drive `SimTransport(realtime=False)` with `step()`.
- The scenario pipeline runs as FastAPI `BackgroundTasks` after the bridge's request (`/api/bridge/segments`, `/state` → `tick` for the 20 s-silence trigger and 24 h retention, `/moments` kept → `on_kept`). `advice_received` never stores a quote (a bystander's words); a pass copies the giver's own quote later.
- Vapi rejects `assistant-request` in an assistant's `serverMessages` (400); it is a phone-number-level message, so `assistant_body` leaves it out (SPEC §7 listed it). Inbound needs the number's own server URL.
- `replaceChildren(null)` prints "null": app.js builds screens with `fill(node, ...kids)`, which skips empty parts. `[hidden]` needs `display:none !important` (a `.tc-btn.wide` display beat it). Bump `CACHE` in `pwa/sw.js` on every release, or installed phones keep the old shell.
