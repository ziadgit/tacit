# tacit: the build spec (single source of truth)

`tacit` is a network where people pick up skills from the people they talk to. A **skill** is
one thing a person knows how to do, in their own words: what to do (the **verdict**), why (the
**reason**), and the exact words they said (the **quote**). It is signed with that person's
name. Learners follow experts and their agents can apply the skills.

This build covers the landing page's journey, phone first:

1. **Connect your context.** In the PWA a person gives their name, phone number and a few links
   about themselves. With their consent, **Exa** looks them up. They keep or remove each item.
2. **Have a short conversation with tacit.** **Vapi** calls them. **Deepgram** is the call's
   ears (Nova-3) and voice (Aura). The interviewer draws out what they know but never wrote
   down, and saves each skill through a tool call while the call is still going. **Jev** checks
   whether each saved skill is a real one.
3. **Grow your network.** The person reviews their draft skills on their phone and publishes
   the ones they want. Others can follow them.
4. **Learn from people.** Following someone shows their public skills. Their followers-only
   skills unlock with a one-time **Stripe** payment, in test mode.
5. **The wristband notices everything** (§13). The Vexo band's mic and motion feed a wide set
   of detectors: advice given and received, explanations, lessons, commitments, writing,
   drawing and more. Advice becomes draft skills and passes in the social feed. Drawing an
   **X or a figure 8 in the air mutes the band**.

The **Raspberry Pi hub** (§13.8) is secondary. It runs the same bridge off-grid and syncs later.

Every decision here is final. Do not re-open it. If something is truly impossible as written,
make the smallest change, record it under "Gotchas" in `CLAUDE.md`, and move on.

## 0. Safety rules for an unattended build

This spec is built with `--dangerously-skip-permissions`. These rules override everything else
in this file.

- **No live network calls to Exa, TypeSafe, Deepgram, Vapi or Stripe**, even though keys may be
  in `.env`. Tests use `respx` and fakes. `uv sync` / `uv add` are fine.
- **Never place a phone call or send a payment.** No `tacit vapi-sync`, no `tacit serve` left
  running against real keys, no `curl` to service APIs.
- **Never deploy.** No `fly` commands at all (`fly launch`, `fly deploy`, `fly secrets`, ...).
  The build only writes the deploy files (§16).
- **Never connect to a real band.** Use the pretend band only (`transport="sim"`), and only with
  numbers from `TEAM_BANDS`. Never run `tacit bridge` or `tacit gestures record` without `--sim`.
- Never read, print, log or commit secrets. Never `cat .env`. Never print `os.environ`.
- **Do not edit** `vexo-open-kit/` (reference clone), `landing/` or `design-system/` (a
  teammate's work). Read them. Serve them. Copy from `design-system/components/bundle.*` into
  `pwa/` if needed.
- Stay inside this repo. Commit locally after each item. **Never `git push`**, never rewrite
  history, never delete branches.
- Code enforces the same rules at runtime: outbound calls only to `CALL_ALLOWLIST` (§1),
  Stripe refuses live keys (§10), band numbers only from `TEAM_BANDS`.

## 1. Layout, stack, settings

```
pyproject.toml  .python-version (3.11)  conftest.py (repo root, autouse env/tmp isolation)
src/tacit/
  config.py      Settings, TEAM_BANDS, require(), require_band()      (exists; extend)
  band.py        use_kit(): Vexo kit on sys.path                       (exists)
  doctor.py      key checks                                            (exists; add Stripe)
  domain.py      pydantic models (§2)
  store.py       SQLite Store (§3)
  auth.py        signed session cookie (§4)
  context.py     Exa lookup → ContextItems (§6)
  judge.py       Jev check on a skill (§8)
  interview.py   Vapi: assistant body, tools, webhook handling, VapiApi (§7)
  payments.py    Stripe Checkout + webhook (§10)
  app.py         create_app() FastAPI (§11)
  bridge.py      the band bridge: streams, mute, upload, offline buffer (§13.1, §13.2, §13.7)
  gestures.py    X / figure-8 recogniser, a port of the kit's gesture trainer (§13.2)
  gesture_templates.json   built-in X and figure-8 templates (made by scripts/)
  motion.py      writing / drawing / whiteboard / typing / making detectors (§13.6)
  scenarios.py   windows, Jev classification, extraction, moments, passes (§13.4, §13.5)
  llm.py         OpenAI Responses API over httpx, JSON-schema output (§13.4)
  cli.py         doctor | serve | vapi-sync | bridge | gestures
  *_test.py      tests beside code
pwa/             the mobile-first PWA, no build step (§12)
Dockerfile  .dockerignore  fly.toml   deployment to Fly.io (§16)
```

Python ≥ 3.11, uv, hatchling, `src/` layout (already set up). Add the runtime deps
`itsdangerous` and `stripe`. The API takes JSON only, so `python-multipart` isn't needed. All
service I/O is async. Exa, Jev, Vapi and Stripe are **duck-typed parameters**, so tests pass
fakes. HTTP that we make ourselves (Vapi REST) goes through `httpx.AsyncClient` and is mocked
with `respx`. The root `conftest.py` has an autouse fixture that deletes every Settings env var
and `chdir`s to `tmp_path`, so tests never read the real `.env`.

`Settings` (extend the existing class; `env_file=".env"`, `env_ignore_empty=True`, no prefix):

| field | type | default |
|---|---|---|
| tacit_band | `int \| None`, must be in `TEAM_BANDS` | None (exists) |
| deepgram_api_key, openai_api_key, exa_api_key, typesafe_api_key, vapi_api_key | `SecretStr \| None` | None (exist) |
| vapi_server_secret, session_secret, stripe_secret_key, stripe_webhook_secret | `SecretStr \| None` | None |
| tacit_bridge_token | `SecretStr \| None` | None (bridge side: from pairing, §13.1) |
| tacit_server_url | `str \| None` | None (bridge side: where to upload; defaults to `public_base_url`) |
| openai_model | str | `"gpt-6-luna"` (as the kit's `ai.py`) |
| scenario_threshold | float | 0.6 |
| windows_per_hour | int | 40 |
| mute_rewind_s | int | 15 |
| bridge_buffer_mb | int | 500 |
| vapi_assistant_id, vapi_phone_number_id | `str \| None` | None |
| tacit_phone_display | `str \| None` | None (the inbound number shown in the PWA, e.g. "(415) 555-0100") |
| public_base_url | `str \| None` | None (https, no trailing slash) |
| call_allowlist | `list[str]` (E.164; env is comma-separated) | `[]` = **no outbound calls at all** |
| vapi_llm_provider / vapi_llm_model | str | `"openai"` / `"gpt-4.1"` |
| vapi_voice_id | str | `"asteria"` |
| jev_model | str | `"jev-1.13.0"` (exists) |
| deepgram_stt_model / deepgram_tts_model | str | `"nova-3"` / `"aura-2-thalia-en"` (exist) |
| interview_max_seconds | int | 600 |
| follow_price_cents | int | 500 (USD, one-time) |
| tacit_data_dir | Path | `Path("data")` (gitignored); the DB is `data/tacit.db` |
| exa_timeout_s / jev_timeout_s | float | 8.0 / 5.0 |
| calls_per_user_per_day / lookups_per_user_per_day | int | 3 / 3 |

`call_allowlist` parses `"+14155550100,+15105550101"` into a list, and each entry must match
`^\+[1-9]\d{7,14}$`. Update `.env.example` with every new field and a one-line comment each.
`SESSION_SECRET` and `VAPI_SERVER_SECRET` come from `openssl rand -hex 32`.

## 2. Domain (`domain.py`, pydantic v2)

```python
Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{7,14}$")]   # E.164 only

class User(BaseModel):
    id: str                      # uuid4 hex
    name: str                    # 1..80 chars, stripped
    phone: Phone
    headline: str | None = None  # "Ten years in product", 0..140 chars; helps Exa find the right person
    links: list[HttpUrl] = []    # 0..5, given by the user
    consent_lookup: bool         # "Look me up on the web with Exa"
    consent_call: bool           # "tacit may call me at this number"
    created_at: datetime

class ContextItem(BaseModel):    # one fact Exa found; shown for review, never auto-kept
    id: str; user_id: str
    kind: Literal["role", "expertise", "work", "writing", "other"]
    text: str                    # ≤ 200 chars
    source_url: str
    status: Literal["pending", "kept", "removed"] = "pending"

class Skill(BaseModel):
    id: str; owner_id: str
    title: str                   # ≤ 80 chars, imperative: "Open an update with the number"
    verdict: str                 # what to do, ≤ 280 chars
    reason: str                  # why, ≤ 280 chars
    quote: str | None = None     # the person's exact words, ≤ 200 chars
    source: Literal["interview", "conversation"] = "interview"
    status: Literal["draft", "published", "removed"] = "draft"
    visibility: Literal["public", "followers"] = "public"
    jev_specific: float | None = None    # Jev Noul probabilities (§8); None = not checked
    jev_own: float | None = None
    created_at: datetime

class Follow(BaseModel):
    follower_id: str; expert_id: str
    paid: bool = False
    stripe_session_id: str | None = None
    created_at: datetime

class Call(BaseModel):
    id: str; user_id: str
    vapi_call_id: str | None = None
    direction: Literal["outbound", "inbound"]
    status: Literal["queued", "ringing", "in-progress", "ended", "failed"] = "queued"
    ended_reason: str | None = None
    created_at: datetime
```

API responses use separate `...Out` models. **Another person's phone, links and context items
are never in any response.** `PersonOut` = id, first name, headline, skill count, follower count.

## 3. Store (`store.py`)

`Store(path: Path)` uses stdlib `sqlite3` (WAL mode, `check_same_thread=False`, one connection,
a `threading.Lock` around writes). The schema is created on open: tables `users`, `context_items`,
`skills`, `follows` (primary key follower_id+expert_id), `calls`, `events` (for rate limits:
user_id, kind, at), `stripe_events` (event id primary key, for idempotency). Methods are plain
sync functions that return domain models. Store `links` as JSON text. Add the methods each
section needs. `delete_user(user_id)` removes the user and **every** row that references them,
in one transaction: skills, follows both ways, calls, context items, events.

Tests use `Store(tmp_path / "t.db")`.

## 4. Auth (`auth.py`)

No passwords at this stage. The session is created at onboarding.

- Cookie `tacit_session` = `itsdangerous.URLSafeTimedSerializer(SESSION_SECRET, salt="session")`
  over `{"uid": user_id}`. Flags: `HttpOnly`, `SameSite=Lax`, `Secure` when `public_base_url`
  starts with https, `Max-Age` 30 days.
- FastAPI dependency `current_user` → `User`, or 401 `{"detail": "not signed in"}`.
- `SESSION_SECRET` unset → every `/api/*` route except `GET /api/config` answers 503
  `{"detail": "SESSION_SECRET is not set"}`.
- A `Origin` header on a state-changing request (POST/PATCH/DELETE under `/api/`) must equal
  `public_base_url` or `http://localhost:<port>` / `http://127.0.0.1:<port>`, otherwise 403.

## 5. Onboarding API

- `POST /api/onboarding` `{name, phone, headline?, links?, consent_lookup, consent_call}` →
  creates the user, sets the cookie, 201 `MeOut`. If the phone already belongs to a user, 409
  `{"detail": "this number already has an account"}` (no sign-in by phone at this stage).
- `GET /api/me` → `MeOut`: the user + their context items + their calls + counts.
- `DELETE /api/me` → `store.delete_user`, clears the cookie, 204. The PWA calls this
  "delete everything".
- `PATCH /api/me` `{headline?, links?, consent_lookup?, consent_call?}`.

## 6. Context lookup with Exa (`context.py`)

Read `.claude/skills/build-with-exa/SKILL.md` and `references/search.md` first, and check the
installed `exa-py` for real attribute names.

`POST /api/context/lookup` (needs `consent_lookup`, else 403; rate limit
`lookups_per_user_per_day`, else 429) → runs `lookup(user, exa, settings)` → stores the items
as `pending` → returns them. `PATCH /api/context/{id}` `{status: "kept" | "removed"}`. Only
`kept` items ever go into the interview.

`lookup` makes **one** search about the person themselves. `exa` is any object with
`async def search(query, **kwargs)` (`exa_py.AsyncExa` in production), run under
`asyncio.timeout(settings.exa_timeout_s)`. `N` = name, `H` = headline or "", `L` = the user's
own links joined with " ":

```python
PROFILE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {
        "kind": {"type": "string", "enum": ["role", "expertise", "work", "writing", "other"]},
        "text": {"type": "string"}, "source_url": {"type": "string"}},
    "required": ["kind", "text", "source_url"]}}}, "required": ["items"]}

await exa.search(
    f"{N} {H} {L}".strip(),
    type="auto",
    objective=(f"Find public professional information about {N} ({H}): roles, areas of expertise, "
               "notable work and writing. Prefer the pages the person linked and pages they wrote "
               "themselves. Exclude other people with the same name, people-search and data-broker "
               "sites, and anything about their private life, family, address or health."),
    system_prompt=("Only include facts about this one person that are clearly supported by a "
                   "source. Each item is one short fact in plain words with its source URL. Never "
                   "guess; return an empty list when unsure it is the same person."),
    output_schema=PROFILE_SCHEMA,
    contents={"highlights": True},
)
```

Read `output.content` (it may be a dict or a JSON string; handle both). Drop invalid items, any
item whose `source_url` is not http(s), and any beyond 12. A timeout or error → 502
`{"detail": "couldn't look you up right now"}`, and nothing is stored. Never search for anyone
other than the signed-in user. Never put the phone number in a query. Tests assert the exact
kwargs.

## 7. The interview call (`interview.py`): Vapi + Deepgram

Same pattern as https://github.com/ziadgit/bling `src/bling/vapi.py`.

**Assistant** `assistant_body(settings) -> dict`, created/updated by `tacit vapi-sync`:

```python
{"name": "tacit interview",
 "firstMessage": "Hi {{name}}, it's tacit. I'd like to learn one or two things you know how to do "
                 "that you've never written down. Have you got a few minutes?",
 "maxDurationSeconds": settings.interview_max_seconds,
 "transcriber": {"provider": "deepgram", "model": settings.deepgram_stt_model, "language": "en",
                 "endpointing": 300},
 "voice": {"provider": "deepgram", "voiceId": settings.vapi_voice_id},
 "model": {"provider": settings.vapi_llm_provider, "model": settings.vapi_llm_model,
           "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
           "tools": [NOTE_SKILL_TOOL]},
 "server": {"url": f"{public_base_url}/vapi/webhook", "headers": {"x-tacit-secret": <secret>}},
 "serverMessages": ["tool-calls", "status-update", "end-of-call-report", "assistant-request"],
 # only when DEEPGRAM_API_KEY is set: Deepgram usage is billed to the team's own account
 "credentials": [{"provider": "deepgram", "apiKey": <deepgram key>}]}
```

`SYSTEM_PROMPT` (a constant): "You are tacit's interviewer. You are talking with {{name}}. What
they confirmed about themselves: {{context}}. Your job is to draw out one to three skills: things
they know how to do that they never wrote down. Ask about a concrete recent situation, then what
they did, what most people get wrong, and why they do it their way. Ask one short question at a
time and let them talk. When you have heard a skill clearly, call note_skill with a short
imperative title, the verdict (what to do), the reason (why), and their own exact words as the
quote. Then say in one sentence what you saved, and ask if it's right. Never invent anything
they didn't say. Never ask about their private life, health, money or other people's details.
After three skills, or when they want to stop, thank them and say their skills are waiting for
them in the app. Short sentences. No lists."

`NOTE_SKILL_TOOL`: a function tool `note_skill(title: str, verdict: str, reason: str,
quote?: str)` with `"messages": [{"type": "request-start", "content": "Let me write that down."}]`.

**Outbound call** (`POST /api/call`):
1. 403 unless `consent_call`. 429 past `calls_per_user_per_day`. 409 if the user has a call in
   queued/ringing/in-progress.
2. **403 `{"detail": "calls are limited to the team's test numbers right now"}` unless
   `user.phone in settings.call_allowlist`.** An empty allowlist means no outbound calls.
3. `VapiApi.create_call(...)`: `POST https://api.vapi.ai/call`, `Authorization: Bearer`, body
   `{"assistantId", "phoneNumberId", "customer": {"number": phone, "name": first_name},
   "assistantOverrides": {"variableValues": {"name": first_name, "context": context_text},
   "metadata": {"tacit_call_id": call.id}}}`. `context_text` = the kept items' `text` joined
   with "; ", ≤ 600 chars, or "nothing yet". Store the response's `id` as `vapi_call_id`.
4. On a Vapi error the call is `failed`, and the PWA offers the inbound number
   (`tacit_phone_display`) instead. Vapi error text never echoes the request body.

**Inbound call.** The Vapi phone number has no fixed assistant. Vapi sends `assistant-request`
with `message.call.customer.number`. If that number belongs to a user with `consent_call`,
create an inbound `Call` and answer `{"assistantId": vapi_assistant_id, "assistantOverrides":
{...same variableValues and metadata...}}`. Otherwise answer `{"error": "Please sign up in the
tacit app first, then call again."}`.

**Webhook `POST /vapi/webhook`.** It requires header `x-tacit-secret` == `VAPI_SERVER_SECRET`
(`hmac.compare_digest`), else 401. It finds the `Call` by `message.call.assistantOverrides.
metadata.tacit_call_id`, then `message.call.metadata.tacit_call_id`, then `message.call.id` ==
`vapi_call_id`. Parse tolerantly: missing fields never raise. Handlers by `message.type`:
- `tool-calls`: for each call in `message.toolCallList` (`arguments` may be a dict or a JSON
  string), `note_skill` → validate lengths (trim to the limits), run `judge.check` (§8), store a
  `draft` Skill with `source="interview"`. Respond `{"results": [{"name", "toolCallId",
  "result": "Saved: <title>."}]}`, or `"error"` in place of `"result"`, never both. Echo
  `toolCallId` exactly. Results are flat strings.
- `status-update`: map `message.status` onto `Call.status` (unknown values are ignored).
- `end-of-call-report`: status `ended`, `ended_reason = message.endedReason`. **Do not store
  the transcript, the recording URL or the summary.**
- anything else → 200 `{}`.

`GET /api/call/status` → the latest call + the count of skills from it (the PWA polls every 3 s
while a call is active).

## 8. Jev check (`judge.py`)

Use `typesafe_sdk` exactly as `src/tacit/doctor.py` and bling's `decision.py` do:
`AsyncTypeSafeClient(api_key=..., model=settings.jev_model, retry=RetryPolicy(max_retries=0),
timeout=settings.jev_timeout_s)`, then `system_one(state=..., questions=...)` and
`response.nouls[k].noul`. `jev` is duck-typed (it may be None).

```python
QUESTIONS = {
  "specific": Noul(
    instructions="Is `skill` a specific, usable piece of know-how: a clear verdict about what to "
                 "do in a kind of situation, with a reason, rather than generic advice anyone "
                 "would give?",
    criteria=NoulCriteria(true="Specific: someone could act on it and it says why.",
                          false="Generic, vague, or missing what to do or why.")),
  "own": Noul(
    instructions="Does `quote` show that the speaker themselves practises `skill`, in their own "
                 "words, rather than repeating someone else's advice or the interviewer's words?",
    criteria=NoulCriteria(true="Their own practice, in their words.",
                          false="Not clearly theirs, or there is no quote.")),
}
state = {"skill": {"title", "verdict", "reason"}, "quote": quote or "none"}
```

`check(skill, jev, settings) -> (specific, own)` floats, or `(None, None)` when Jev is None,
raises, or times out. **Code never drops or publishes a skill based on Jev.** The scores are
shown to the owner (§12) and the owner decides.

## 9. Skills and the network API

- `GET /api/skills/mine` → all of the owner's skills except `removed`, newest first.
- `PATCH /api/skills/{id}` (owner only, else 404) `{title?, verdict?, reason?, quote?, status?,
  visibility?}`. `status` may be `published` or `removed`.
- `GET /api/people` → `PersonOut` for users with ≥ 1 published skill, most skills first, max 50.
- `GET /api/people/{id}` → `PersonOut` + published skills. Skills with `visibility="followers"`
  appear only with `title` (verdict/reason/quote `null`, `locked: true`) unless the viewer is the
  owner or has a `paid` follow.
- `POST /api/follow/{id}` (free follow; following yourself → 400), `DELETE /api/follow/{id}`.
- `GET /api/feed` → typed feed items (§13.5): published skills (public, and unlocked
  followers-only ones), passes, shared creative sessions and posts from people the viewer
  follows, plus the viewer's own private picked-up items. Newest first, max 50.

## 10. Payments with Stripe (`payments.py`), test mode only

`payments` is duck-typed: `async create_checkout(*, expert_id, follower_id, amount_cents,
success_url, cancel_url) -> (session_id, url)` and `parse_event(payload: bytes, signature: str)
-> dict`. Production `StripePayments(settings)` wraps the official `stripe` package. Check the
installed version for the client and method names (`stripe.StripeClient`, the checkout sessions
create call, `stripe.Webhook.construct_event`); don't guess.

- **`StripePayments` raises `RuntimeError("live Stripe keys are not allowed")` if the secret key
  does not start with `sk_test_` (or `rk_test_`).** `doctor` shows the mode, never the key.
- `POST /api/follow/{id}/checkout` → creates the follow row (unpaid) if missing, then a Checkout
  Session: `mode="payment"`, one line item, `price_data` {currency "usd", unit_amount
  `follow_price_cents`, product_data.name `"Follow <first name>'s skills on tacit"`},
  `client_reference_id` = follower id, `metadata` {follower_id, expert_id}, success_url
  `{base}/app/#/people/{id}?paid=1`, cancel_url `{base}/app/#/people/{id}`. Returns `{url}`; the
  PWA redirects to it.
- `POST /stripe/webhook`: `parse_event(raw body, Stripe-Signature header)`. A bad signature → 400.
  On `checkout.session.completed` with `payment_status == "paid"`: set `paid=True` and
  `stripe_session_id` on that follow. Idempotent: an event id already in `stripe_events` → 200
  and no change. Other events → 200.
- No payouts to experts in this build (Stripe Connect is a later decision; list it under
  "Discovered").

## 11. App (`app.py`)

`create_app(settings=None, *, store=None, exa=None, jev=None, vapi=None, payments=None) ->
FastAPI`. The lifespan builds the real clients from whatever keys are set, unless they are
injected (tests inject fakes). `docs_url=None, redoc_url=None, openapi_url=None`.

Routes: everything in §4–§10, plus
- `GET /healthz` → `{"status": "ok"}`
- `GET /api/config` → `{"phone_display", "follow_price_cents", "calls_enabled":
  bool(allowlist and vapi set), "lookup_enabled", "payments_enabled"}` (no secrets)
- `GET /` → the teammate's `landing/` (StaticFiles, html=True); `/design-system/` → `design-system/`
- `/app/` → `pwa/` (StaticFiles, html=True). Register every API route first and mount `/` last,
  or the landing mount swallows `/api/*`. `sw.js` is served with
  `Cache-Control: no-cache`. `manifest.webmanifest` is served as `application/manifest+json`.

Every response carries a strict CSP: `default-src 'self'; style-src 'self'
https://fonts.googleapis.com 'unsafe-inline'; font-src https://fonts.gstatic.com; img-src
'self' data:; connect-src 'self'; frame-ancestors 'none'`. Logging: route, status, timing,
tool names, call status. **Never** log phone numbers, names, skill text, transcripts, request
bodies or keys.

## 12. The PWA (`pwa/`)

Mobile first, installable, **plain HTML + CSS + ES modules, no build step, no npm packages**.
It follows `design-system/README.md` exactly (read it in full first) and uses its tokens
and classes. Copy `design-system/components/bundle.css` and `bundle.js` into `pwa/vendor/`
(that's a copy, not an edit), with a header comment naming the source.

```
pwa/
  index.html            one page; screens are <section>s shown by a hash router
  app.js                router + screens; imports api.js
  api.js                fetch wrapper: same-origin, credentials "same-origin", JSON, errors → messages
  style.css             mobile layout on top of vendor/bundle.css
  sw.js                 service worker
  manifest.webmanifest  name "tacit", short_name "tacit", start_url "/app/", scope "/app/",
                        display "standalone", background/theme colours from tokens.json
  icons/                icon.svg, icon-192.png, icon-512.png, maskable-512.png
  vendor/               bundle.css, bundle.js (copied from design-system)
```

Generate the PNG icons with a small stdlib-only Python script in `scripts/make_icons.py`
(zlib + struct): the lavender ground with a cream plus. Commit the PNGs.

**Screens** (hash routes). Each fits a 375×812 phone with no sideways scroll; tap targets
≥ 44px; body text ≥ 16px; lower-case titles; "skill", never "move":
- `#/start`: the wordmark, the tagline, the first-run form: name, phone (with a country code,
  validated as E.164 before sending), headline, up to 5 links, and two **unticked** consent
  checkboxes: "Look me up on the web (Exa) so the interview starts from what's public" and
  "tacit may call me at this number". Under the checkboxes: "Calls are recorded only as the
  skills you approve. We don't keep the audio or the transcript."
- `#/context`: a "look me up" button (hidden without `consent_lookup`); each found item as a
  card with its source domain and keep / remove. "Nothing found" is a fine result.
- `#/call`: "call me" (when `calls_enabled`), then status (queued → ringing → in the call →
  ended) and skills appearing live as they are saved (poll `/api/call/status` and
  `/api/skills/mine` every 3 s while active). It always also shows "or call
  {phone_display}". **No blue here**: blue means only that the band is listening.
- `#/skills`: the owner's skills as SkillCards: title, verdict, reason, the quote in
  handwriting, the Jev line ("looks specific" when `jev_specific ≥ 0.5`, "might be generic"
  when below, nothing when null), edit, publish, public/followers, remove.
- `#/people` and `#/people/:id`: PersonRings with handwritten first names; a person's page
  with their skills, follow / unfollow, and "unlock followers-only skills for $X" → checkout.
- `#/feed`: typed items (§13.5) as SkillCards, PassChips (the orange "lit" colour only while a
  pass is new, then off), creative sessions ("ana sketched for 25 minutes") and posts. Your own
  picked-up items are marked "only you see this".
- `#/moments`: the wearer's private timeline, grouped by hour: every detected moment with its
  kind, time and confidence; keep / dismiss / share (share only for recommendation, lesson and
  idea); a draft skill links to `#/skills`.
- `#/me`: consents (toggleable); **your band**: connect a band (16 or 74; the token is shown
  once, with the two `.env` lines for the bridge), its live state, a big **mute / unmute**
  button, a reminder of the gestures (draw an X or a figure 8 to mute; the same, then a
  double-tap, to unmute; double-tap to keep the last minute), a toggle per scenario kind, and
  "share creative sessions" (off); "delete everything" (asks twice in-page; **no
  `confirm()`/`alert()`**); sign-out = clear the cookie.
- **ListeningPill**, top right on every screen, shown **only** while the wearer's bridge reports
  `listening` (polled every 5 s). It is the only blue in the app. Muted: the pill says "muted",
  in cream, not blue.

Rules:
- All data from the API is set with `textContent` or attributes, never `innerHTML`.
- No third-party requests except Google Fonts. No analytics. No `localStorage` for personal
  data; `localStorage` may hold only the last route.
- `sw.js`: a versioned cache (`tacit-shell-v1`) of the shell (index.html, app.js, api.js,
  style.css, vendor/*, icons/*, manifest). Cache-first for the shell. **Network-only for
  `/api/*`, never cached.** On a failed navigation offline, serve the cached index, which shows
  a "you're offline" banner. Old caches are deleted on `activate`.
- Respect `prefers-reduced-motion` (show settled frames, as the design system says).

**Tests** for the PWA (Python, no browser): the manifest is valid JSON with the required
fields and existing icon files; the PNGs have the right dimensions; `index.html` links the
manifest and registers `/app/sw.js` with scope `/app/`; no `innerHTML`, `eval(`, `alert(`,
`confirm(` or external `fetch` in `pwa/*.js` (excluding vendor); `sw.js` never caches
`/api/`; TestClient serves `/app/`, `/app/sw.js` (no-cache) and the manifest content type.

## 13. The band: bridge, mute gestures, scenario detection

tacit is **maximalist about noticing** and **conservative about sharing**. While capture is on,
it tries to detect every scenario in the catalogue (§13.3) from the wrist's microphone and
motion. Each detection is a **moment**, private to the wearer. A moment reaches the social feed
only by the rules in §13.5. Detection is generous; publishing is never automatic, except for
the content-free kinds a user explicitly turned on.

### 13.1 The bridge (`bridge.py`, `tacit bridge`)

The bridge is the program connected to a band. It runs on a laptop (the demo) or on the Pi
(§13.8), with the same code.

- It connects to `TACIT_BAND` only (`use_kit()`, `Band.connect(band, auto_reconnect=True)`) and
  checks `band.number`. It never scans for, lists or connects to another band.
- On every connect and `reconnected` it applies `set_motion(accel_range=8, gyro_range=1000)`
  and `configure(events=True, motion=100, sensors="both", activity=1, battery=60)`. While
  listening it adds `audio=True, mic_level=0.1`. (Motion at 100 Hz with both sensors is within
  the Bluetooth limit with audio on, rule 14 in the kit's AGENTS.md.)
- Before the microphone first starts, it prints the kit's line that the sound goes to Deepgram.
  It streams Opus to Deepgram with the kit's `speech.create(...)`, passing `model=nova-3`,
  `endpointing=300`, `diarize="true"`, and up to 20 `keyterm`s from the wearer's kept context.
  `mip_opt_out=true` stays (the kit fixes it).
- **Pairing.** In the PWA (`#/me` → "connect a band"), the wearer picks 16 or 74. The server
  checks it is in `TEAM_BANDS` and not linked to another user, then creates a `BridgeDevice`
  and shows a token **once**. Only its SHA-256 is stored. The bridge's `.env` gets
  `TACIT_BRIDGE_TOKEN` and `TACIT_SERVER_URL` (the Fly URL, §16).
- **Bridge API** (Bearer bridge token, else 401; rate-limited per device):
  - `POST /api/bridge/state`, every 10 s: `{connected, listening, muted, battery, buffer_mb}`.
  - `GET /api/bridge/commands`, polled every 2 s: `{"muted": bool}`, as set from the PWA.
  - `POST /api/bridge/segments`: final transcript segments (§13.4).
  - `POST /api/bridge/moments`: motion sessions and gesture events (§13.6).
  - `POST /api/bridge/rewind` `{seconds}`: deletes this device's segments from the last N
    seconds, and any moment built only from them.
- **Raw motion never leaves the bridge.** Only session summaries do. Raw audio leaves only
  to Deepgram, or sits in the offline buffer (§13.7).

### 13.2 Mute: draw an X or a figure 8 in the air

Mute is safety-critical, so it is **easy to trigger and hard to undo**.

- **States.** `listening` means `audio` and `mic_level` are on, and the band's LED is solid blue
  by itself (kit rule 4). `muted` means both are off and the Deepgram stream is stopped. On
  entering mute, the LED blinks white twice (`set_led("#ffffff", pattern="blink",
  period=200)` for 0.8 s), then goes off. **Blue light = listening; no blue = not listening.**
- **To mute:** draw an **X** or a **figure 8** in the air. The mic must be off within 1 s of the
  gesture ending. In the motion handler, the gesture check runs before anything else.
- **Rewind on mute.** People mute right after something they didn't want kept. On mute, the
  bridge drops whatever audio and segments it hasn't uploaded from the last `MUTE_REWIND_S`
  (default 15 s), and calls `/api/bridge/rewind` with the same number of seconds.
- **To unmute:** the same gesture, **then a double-tap within 3 s**, or "unmute" in the PWA.
  Mute never times out.
- The muted state is saved in `data/bridge-state.json`. After a restart, a crash or a
  reconnect, the bridge comes back muted if it was muted. The PWA's mute button sets the server
  command, and the bridge applies it within one poll (≤ 2 s).
- **Someone asks to stop.** If a final segment matches
  `\b(stop recording|turn (it|that) off|don'?t record|off the record|mute (it|that))\b` (case
  insensitive), the bridge mutes at once, with the rewind. The server also checks every window
  with Jev (`stop_request`, §13.4). If that fires, it sets the mute command and rewinds 60 s.
- **The recogniser** (`gestures.py`: pure functions, no band). It is a Python port of the kit's
  `projects/gesture-trainer/recogniser.js` (`Segmenter`, `to_shape`, `match`), with the same
  constants at the top and the same comment that they are untested guesses. Two thresholds:
  `MUTE_LIMIT` (looser; a near-miss still mutes) and `UNMUTE_LIMIT` (stricter). Built-in
  templates for `x` and `figure8` live in `src/tacit/gesture_templates.json`. They are made by
  `scripts/make_gesture_templates.py`, which turns a drawn path (two crossing strokes; a
  lemniscate) into wrist turning rates and accelerations, and then into `to_shape` points.
  `tacit gestures record x|figure8 [--sim]` saves 3 of the wearer's own examples to
  `data/gestures.json`, used alongside the built-ins.
- **Other band gestures.** **Double-tap = "keep that"** (when not in the unmute window): it
  marks the last 60 s. The server runs every text detector on that window with
  `forced=True` and always makes a `kept` moment, even when nothing is detected. Single tap,
  free-fall and tilt do nothing (too common to mean something).
- Tests (pretend band + `play_motion`): an X and a figure 8 each mute within 1 s; the rewind
  call is sent; the LED blinks then turns off; unmute needs the gesture *and* the double-tap;
  the pretend band's own swing, a shake and a still hand never mute; the state survives a
  restart; the stop-phrase regex mutes.

### 13.3 The scenario catalogue

| kind | from | how | goes to |
|---|---|---|---|
| `stop_request` | audio | regex on the bridge + Jev | **mute + rewind** (§13.2) |
| `conversation` | audio | ≥ 2 diarized speakers within 2 min | private span |
| `advice_given` | audio | Jev + extraction; giver = wearer | **draft skill** (§13.5) |
| `advice_received` | audio | Jev + extraction; giver = other | private "picked up"; a **pass** if matched |
| `explanation` | audio | a how-to with steps | draft skill (verdict holds the steps) |
| `lesson` | audio | "the mistake we made was…" | draft skill |
| `question` | audio | the wearer asks for advice | private; shows people in their network with a matching skill |
| `decision` | audio | "let's go with X" | private |
| `commitment` | audio | "I'll send it tomorrow" | private, with the due text |
| `recommendation` | audio | a book, tool, person or place called worth it | private; shareable as a post |
| `idea` | audio | a new idea said out loud | private |
| `presenting` | audio + motion | the wearer speaks ≥ 3 min, mostly alone, gesturing | private span |
| `writing` | motion | handwriting | creative session |
| `drawing` | motion | sketching | creative session |
| `whiteboard` | motion | drawing with the forearm raised | creative session |
| `typing` | motion | keyboard bursts | focus session (private) |
| `making` | motion | sustained rhythmic tool use | creative session (low confidence) |
| `walking_meeting` | motion + audio | walking + a conversation | private span |
| `demonstration` | audio + motion | an explanation during drawing, whiteboard or making | draft skill, **ranked first** |
| `kept` | double-tap | the last 60 s | private; detectors forced on it |

Each kind can be switched off in `#/me`; they all start **on**.

### 13.4 Text detectors (`scenarios.py`, `llm.py`, on the server)

- **Segments.** `{started_at, ended_at, speaker (Deepgram diarized int), text, level}`, where
  `level` is the median `rms_db` from `mic-level` during the segment. **A lower `rms_db` is
  louder** (the kit's dashboard draws 52 as empty and 12 as full). The likely wearer is the
  speaker with the lowest median level, by ≥ 6 dB. Otherwise the wearer is unknown and Jev
  decides.
- **Windows.** A window is up to 3 minutes of segments, with 30 s overlap. One runs after 90 s
  of new speech, after 20 s of silence, and at once on "keep that". Lines are written
  `S0 (likely wearer): …`. There is a cap of `windows_per_hour` (default 40) per device.
- **Step 1, Jev classifies** (one `system_one` call per window): a `Noul` per kind (`advice`,
  `explanation`, `lesson`, `question`, `decision`, `commitment`, `recommendation`, `idea`,
  `stop_request`), plus `Choice` `giver` ∈ {`wearer`, `other`, `both`, `none`} with criteria for
  each. A probability ≥ `scenario_threshold` (default 0.6) moves that kind to step 2. Jev
  unavailable → no detections for that window (never guess). Tests use a fake Jev.
- **Step 2, extraction** (`llm.py`): OpenAI Responses API over httpx, `POST
  https://api.openai.com/v1/responses` `{model: settings.openai_model, input, text: {format:
  {type: "json_schema", name, schema, strict: true}}}`, read the output text, parse JSON. The
  default model is `"gpt-6-luna"`, the same as the kit's `ai.py`. One schema per kind: advice
  / explanation / lesson / demonstration → `{title, verdict, reason, quote, giver, steps[]}`;
  commitment → `{what, who, when_text}`; decision → `{what, why}`; recommendation → `{thing,
  kind, why}`; question → `{question, topic}`; idea → `{idea}`. Tests use respx.
- **No invented quotes.** A `quote` is kept only if it appears in the window text, compared
  with case and whitespace normalised. Otherwise it is set to null.
- **Dedup.** Same kind, title token Jaccard ≥ 0.6, within 30 min → merge into the earlier moment.
- **Retention.** Segments are deleted after 24 h, and at once on rewind. Moments and skills stay
  until the user removes them.

### 13.5 Moments, skills, passes and the feed

- **`advice_given`, `explanation`, `lesson`, `demonstration` with the wearer as giver** → a
  draft `Skill` (`source="conversation"`), checked by Jev as in §8 and linked to the moment.
  It appears in followers' feeds only after the owner publishes it.
- **`advice_received`** → a private "picked up" item for the wearer: title, verdict, reason,
  credited to "someone you talked with". The quote and the giver's words are kept **only if
  the giver is a matched tacit user** (below).
- **Passes.** Two linked devices whose `conversation` moments overlap by ≥ 60 s are in the same
  conversation. An `advice_given` on one and an `advice_received` on the other, within ±2 min
  (or title Jaccard ≥ 0.4), make a `Pass {giver_id, receiver_id, skill_id}`. When the giver
  publishes that skill, both feeds get a pass item (a PassChip: "maya passed *open an update
  with the number* to ana"). The receiver's picked-up item then shows the giver's name. Bands
  16 and 74 are the test pair. This is the only way one person's band data affects another
  person, and it happens on the server, never over Bluetooth.
- **Creative sessions** (`writing`, `drawing`, `whiteboard`, `making` ≥ 5 min) → a private
  moment with its duration. If the user turned on "share creative sessions" (off by default),
  followers see a content-free item: "ana sketched for 25 minutes".
- **Everything else** stays in the private `#/moments` timeline. The wearer can turn a
  `recommendation`, `lesson` or `idea` into a feed **post** by hand.
- `GET /api/feed` returns typed items, newest first, max 50: `skill`, `pass`, `creative` and
  `post` from people you follow (and passes involving you), plus your own `picked_up` items
  (only you see these). `GET /api/moments` returns the wearer's own moments.
  `PATCH /api/moments/{id}` `{status: kept | dismissed | shared}`.
- Domain additions: `BridgeDevice(id, user_id, band, token_sha256, muted, last_state,
  last_seen)`, `Segment`, `Moment(id, user_id, kind, started_at, ended_at, title, body: dict,
  confidence, source: audio|motion|both, status: new|kept|dismissed|shared, skill_id?)`,
  `Pass`, `FeedItemOut`. `delete_user` also deletes these.

### 13.6 Motion detectors (`motion.py`, on the bridge, pure functions)

- Input: 100 Hz motion. Windows are 4 s with a 2 s hop. Features, in pure Python (no numpy):
  accel-magnitude std, gyro-magnitude mean and std, dominant gyro frequency (autocorrelation
  peak, 0.5–12 Hz), forearm pitch from low-pass gravity, the fraction of still samples, and
  burstiness (short spikes per second).
- Rules, as constants at the top (guesses to tune on a real wrist, said so in a comment,
  as the kit does):
  - `writing`: gyro mean 15–120 °/s, dominant 3–8 Hz, accel std < 0.15 g, wrist pitched down.
  - `drawing`: gyro mean 10–150 °/s, dominant 0.5–3 Hz, accel std 0.05–0.4 g, with pauses.
  - `whiteboard`: drawing-like with forearm pitch > 30° up.
  - `typing`: high burstiness at 5–12 Hz, gyro mean < 20 °/s, wrist level.
  - `making`: rhythmic 1–3 Hz, accel std > 0.3 g, ≥ 2 min.
  - `gesturing`: intermittent large motions while speech is active (feeds `presenting` and
    `demonstration`).
- **Sessions** use hysteresis: a session starts after 60 s with ≥ 70% of windows matching, and
  ends after 45 s without a match. Only sessions ≥ 2 min are reported. Confidence = the share of
  matching windows. Only `{kind, started_at, ended_at, confidence}` is uploaded.
- Tests: a helper makes synthetic signals for each kind (sine mixes plus noise); each is
  labelled right, and the pretend band's swing is labelled nothing. One end-to-end run uses
  `play_motion`.

### 13.7 Offline buffering (bridge, anywhere)

- No internet: Opus packets go to `data/bridge/<date>/<hh>.opus-packets` (length-prefixed),
  capped at `BRIDGE_BUFFER_MB` (default 500) and 24 h, oldest dropped first. Motion sessions
  and gesture events queue in `data/bridge/queue.jsonl`. **Mute still works offline**
  (it is local), and a rewind also deletes buffered audio.
- Back online: transcribe the buffer with Deepgram's prerecorded API (`diarize=true`), upload
  the segments, **then delete the audio**. Upload retries use exponential backoff, max 5 min.
- Tests: buffering while the uploader fails, the size cap, deletion after upload, rewind
  deleting buffered audio.

### 13.8 On a Raspberry Pi (secondary, P2)

- A Pi 4/5 (64-bit Raspberry Pi OS, Python 3.11, BlueZ) runs `tacit bridge` for one of the
  team's own bands as an off-grid hub. `tacit serve` can run on it too, so phones on the Pi's
  Wi-Fi get the PWA locally. Exa, Vapi and Stripe show "needs internet" (`/api/config` flags
  them off when unreachable).
- `GET http://<pi>:8000/healthz` adds `{band_connected, listening, muted, buffer_mb, last_sync}`
  when a bridge runs there.
- Ship `deploy/pi/tacit-bridge.service` (systemd, `Restart=always`, user `tacit`,
  `WorkingDirectory=/opt/tacit`, `EnvironmentFile=/opt/tacit/.env`) and `deploy/pi/README.md`
  (install uv, clone, `scripts/bootstrap.sh`, pair Bluetooth, enable the service; optionally
  hostapd for an off-grid Wi-Fi network). These are files only; the build never runs them.

## 14. CLI (`cli.py`)

- `tacit doctor`: exists. Add a Stripe row: `GET https://api.stripe.com/v1/balance` with Basic
  auth (key as the username), report `works (test mode)` / `status N`, and **FAIL "live key"
  for a non-test key without calling Stripe**. Add rows for `SESSION_SECRET`,
  `VAPI_SERVER_SECRET`, `PUBLIC_BASE_URL` and `CALL_ALLOWLIST` being set (yes/no; never the
  values; for the allowlist, the count only).
- `tacit serve [--host 127.0.0.1] [--port 8000]`
- `tacit vapi-sync [--dry-run]`: PATCH if `VAPI_ASSISTANT_ID` is set, else POST and print "Add
  VAPI_ASSISTANT_ID=<id> to .env". `--dry-run` prints the body with every secret as `"***"`.
- `tacit bridge [--sim]`: runs the bridge (§13.1). `--sim` uses the pretend band with the kit's
  sample speech as its voice and a fake speech client unless `DEEPGRAM_API_KEY` is set.
- `tacit gestures record x|figure8 [--sim]`: records 3 examples of the wearer's own gesture.

## 15. Privacy (this product is built on people's voices)

- Consent is explicit and unticked by default, and stored per user. No lookup without
  `consent_lookup`; no call without `consent_call`.
- Exa looks up only the signed-in user, from what they gave. Every found item is reviewed;
  only `kept` ones are used.
- We store **skills the person approved**, not audio, transcripts or recording URLs from calls.
  Band audio exists only in the offline buffer, and is deleted once transcribed. Band transcript
  segments are deleted after 24 h, or at once on mute. Raw motion never leaves the bridge.
- **Bystanders.** The band hears people who never signed up. Their words are never published,
  never quoted, and never credited by name unless they are a tacit user matched in the same
  conversation (§13.5). Anyone saying "stop recording" mutes the band (§13.2). The blue light
  stays visible, and the wearer is told to tell the people around them.
- Mute is local and works offline. Unmuting needs a deliberate second step.
- A skill is public only after the owner publishes it. Removing it hides it everywhere.
- "Delete everything" really deletes every row.
- Never log personal data (see §11).

## 16. Deployment on Fly.io

The server (`tacit serve`: API, PWA, landing page, Vapi and Stripe webhooks) runs on Fly.io.
Bridges (§13, on laptops or the Pi) are not deployed there; they upload to the Fly app. The build writes these files
and **never runs `fly`** (§0).

- **One machine, one volume.** SQLite can't be shared, so the app runs as exactly one machine
  with a Fly volume `tacit_data` mounted at `/data`, and `TACIT_DATA_DIR=/data`. Never scale it
  out (`fly scale count 1`). Back up with `fly ssh console -C "sqlite3 /data/tacit.db .dump"`
  (documented in the README, not automated).
- **Always on.** Vapi and Stripe webhooks must answer within seconds, so no cold starts:
  `auto_stop_machines = "off"`, `min_machines_running = 1`.
- `fly.toml`:

```toml
app = "tacit-vexohacks"          # change it if the name is taken; PUBLIC_BASE_URL follows it
primary_region = "sjc"

[build]

[env]
  TACIT_DATA_DIR = "/data"
  PUBLIC_BASE_URL = "https://tacit-vexohacks.fly.dev"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    path = "/healthz"
    timeout = "5s"

[mounts]
  source = "tacit_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

- `Dockerfile`: `python:3.11-slim`, copy `uv` from `ghcr.io/astral-sh/uv` (pinned tag), `uv sync
  --frozen --no-dev`, copy `src/`, `pwa/`, `landing/`, `design-system/`. Run as a non-root user.
  `CMD ["/app/.venv/bin/tacit", "serve", "--host", "0.0.0.0", "--port", "8000"]`.
  The image does **not** contain `vexo-open-kit/` (the server never talks to a band), `.env`,
  `data/`, `.venv/`, `.git/`, tests or `deploy/`. All of these go in `.dockerignore`, so
  nothing in the server path may import the kit at module load (`band.use_kit()` is called
  lazily, as `doctor` already does).
- `tacit serve` gains `--proxy-headers`, on by default, passed to uvicorn with
  `forwarded_allow_ips="*"`, because Fly's proxy terminates TLS. The `Secure` cookie flag and
  the Origin check (§4) use `PUBLIC_BASE_URL`, which is `https://<app>.fly.dev`.
- **Secrets** live only in Fly: `fly secrets set SESSION_SECRET=... VAPI_SERVER_SECRET=...
  VAPI_API_KEY=... DEEPGRAM_API_KEY=... EXA_API_KEY=... TYPESAFE_API_KEY=...
  STRIPE_SECRET_KEY=... STRIPE_WEBHOOK_SECRET=... OPENAI_API_KEY=... CALL_ALLOWLIST=...` (typed by a
  person, never by the build). `fly.toml` holds no secrets.
- After the first deploy: run `tacit vapi-sync` locally with `PUBLIC_BASE_URL` set to the Fly
  URL, so Vapi's webhook points to `https://<app>.fly.dev/vapi/webhook`, and point the Vapi
  number's server URL there for inbound calls. In the Stripe dashboard, test mode, add the
  webhook `https://<app>.fly.dev/stripe/webhook` for `checkout.session.completed`, then put its
  signing secret in `STRIPE_WEBHOOK_SECRET`.
- Tests: `fly.toml` parses (`tomllib`) with the values above (one mount at `/data`, the
  `/healthz` check, `auto_stop_machines = "off"`, port 8000); `.dockerignore` lists `.env`,
  `vexo-open-kit`, `data`, `.venv`; the Dockerfile doesn't `COPY . .` and doesn't copy the kit;
  `create_app()` imports and serves `/healthz` with `vexo-open-kit/` absent from `sys.path`.
- The README's "Deploy" section: `fly launch --no-deploy` (keep the existing `fly.toml`),
  `fly volumes create tacit_data --region sjc --size 1`, `fly secrets set ...`, `fly deploy`,
  `fly logs`, then the Vapi and Stripe steps above.
