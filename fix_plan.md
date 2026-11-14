# fix_plan (top to bottom, one commit per item)

## P0: onboarding, interview, skills

- [x] P0: scaffold: add deps (`itsdangerous`, `stripe`), root `conftest.py` (autouse: clear Settings env vars, chdir tmp_path), extend `config.py` (+ `call_allowlist` parsing) + config_test, update `.env.example`. Spec: SPEC.md §1
- [x] P0: `domain.py` + `store.py` (schema, CRUD, rate-limit events, `delete_user` cascade) + tests. Spec: §2, §3
- [x] P0: `auth.py` (session cookie, `current_user`, Origin check, 503 without SESSION_SECRET) + `app.py` skeleton (create_app, lifespan, /healthz, /api/config, CSP, static mounts for `/`, `/design-system/`, `/app/`) + onboarding API (§5) + tests with TestClient. Spec: §4, §5, §11
- [x] P0: `context.py`: the Exa lookup with exact kwargs, parsing, timeout, consent and rate limit, keep/remove API + tests with a fake Exa. Spec: §6
- [x] P0: `judge.py`: the Jev questions, `check()`, None on failure + tests with a fake Jev. Spec: §8
- [x] P0: `interview.py`: `assistant_body`, `NOTE_SKILL_TOOL`, `SYSTEM_PROMPT`, `VapiApi` (create/update assistant, create_call; errors scrubbed), `/api/call` (consent, allowlist, rate limit, one active call), `/api/call/status`, `/vapi/webhook` (secret, tool-calls → draft skill + Jev, status-update, end-of-call-report without storing a transcript, assistant-request for inbound) + tests (respx for Vapi REST). Spec: §7
- [x] P0: skills + network API (§9): mine, patch, people, person (followers-only locking), follow/unfollow, feed + tests. Spec: §9
- [x] P0: PWA shell: `pwa/index.html`, `api.js`, `app.js` router, `style.css`, `vendor/` copy, `manifest.webmanifest`, `sw.js`, `scripts/make_icons.py` + PNG icons; screens `#/start`, `#/context`, `#/call`, `#/skills`, `#/me` + the PWA tests. Spec: §12
- [x] P0: CLI: `serve`, `vapi-sync [--dry-run]` (secrets masked), new `doctor` rows (secrets set yes/no, allowlist count) + cli tests with CliRunner. Spec: §14

## P1: payments and the rest of the PWA

- [x] P1: `payments.py`: `StripePayments` (refuses non-test keys), `/api/follow/{id}/checkout`, `/stripe/webhook` (signature, `paid`, idempotent) + tests with a fake payments object; `doctor` Stripe row. Spec: §10, §14
- [x] P1: PWA screens `#/people`, `#/people/:id` (follow, unlock → checkout redirect), `#/feed`; offline banner; reduced motion + tests. Spec: §12
- [x] P1: `portraits.py`: MiniMax client (base64 only, error codes, respx), `to_dot_map` (Pillow) + tests, `/api/portrait` POST/PUT/DELETE with the photo-consent rule and rate limit, PWA "your picture" (words / my photo, pick one of 4), `pwa/vendor/face.js` copy, portrait on `#/people/:id` + `#/me`. Spec: §17
- [x] P1: Fly.io: `fly.toml`, `Dockerfile`, `.dockerignore`, `serve --proxy-headers`, lazy kit import + deploy tests (files only, never run `fly`). Spec: §16
- [x] P1: README: rewrite the description to match the landing page (a network for tacit knowledge; the band is how conversations become skills), plus "Run it" (bootstrap, doctor, serve, vapi-sync, Vapi number setup with inbound → server URL, Stripe test webhook via `stripe listen`) and "Deploy" (Fly.io, §16). Spec: §0–§16, plus a "the band" section: gestures, what it detects, what is shared

## P1: the band (bridge, mute, scenarios)

- [ ] P1: `gestures.py` (port of the kit recogniser, MUTE_LIMIT / UNMUTE_LIMIT), `scripts/make_gesture_templates.py` + `gesture_templates.json` (x, figure8) + tests with synthetic X / figure 8 / shake / swing / still. Spec: §13.2
- [ ] P1: pairing + bridge API on the server: `BridgeDevice` (token shown once, SHA-256 stored, TEAM_BANDS only), `/api/bridge/state|commands|segments|moments|rewind`, the PWA mute command + tests. Spec: §13.1, §13.2
- [ ] P1: `bridge.py` + `tacit bridge --sim`: connect TACIT_BAND, streams, Deepgram via kit `speech.create(diarize="true")` behind a fake in tests, **mute (gesture, stop phrase, PWA command, LED blink, rewind, saved state)**, unmute (gesture + double-tap), double-tap "keep that", uploads + tests on the pretend band. Spec: §13.1, §13.2
- [ ] P1: `motion.py` detectors (features, rules, hysteresis sessions) wired into the bridge + tests with synthetic signals. Spec: §13.6
- [ ] P1: `llm.py` (Responses API, json_schema, respx) + `scenarios.py`: segments, wearer guess by level, windows, Jev classification (fake), extraction, quote check, dedup, retention, `stop_request` → mute command + tests. Spec: §13.4
- [ ] P1: moments, draft skills from conversations, passes (16 ↔ 74), typed `/api/feed`, `/api/moments` + tests. Spec: §13.5
- [ ] P1: PWA: `#/moments`, the typed `#/feed` (PassChip), `#/me` "your band" (connect, state, mute/unmute, gestures help, per-kind toggles, share creative), ListeningPill + PWA tests. Spec: §12, §13.5
- [ ] P1: offline buffer (cap, 24 h, rewind deletes, prerecorded transcription, upload with backoff, delete after upload) + tests. Spec: §13.7

## P2: Raspberry Pi hub

- [ ] P2: `/healthz` bridge fields, `deploy/pi/tacit-bridge.service` + `deploy/pi/README.md` (files only, never run). Spec: §13.8
- [ ] P2: `tacit gestures record x|figure8 [--sim]` (3 examples → data/gestures.json, used with the built-ins) + tests. Spec: §13.2, §14

## Discovered
