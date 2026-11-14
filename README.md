# tacit

> agents have skills. people have taste. tacit is how it gets around.

`tacit` is a network for tacit knowledge: the things people know how to do but never wrote
down. A **skill** is one of those things in a person's own words: what to do (the verdict), why
(the reason), and the exact words they said (the quote), signed with their name. Experts grow a
profile that builds itself from what they already say; learners follow them, and their agents
can apply the skills.

The **wristband** is how everyday conversations become skills. A Vexo Open band listens while
two people talk; when one explains how they do something, it becomes a draft skill for them to
publish, and a *pass* to the person they told.

Built in one day at **VexoHacks**, San Francisco, Nov 14, 2026. A prototype.

## The journey

1. **Connect your context.** In the app you give your name, number and a few links. With your
   consent, **Exa** looks you up; you keep or remove each thing it found.
2. **Have a short conversation with tacit.** **Vapi** calls you (or you call it). **Deepgram**
   is the call's ears (Nova-3) and voice (Aura). The interviewer draws out what you know and
   saves each skill while the call is going. **Jev** (TypeSafe) checks whether each one is
   specific and really yours.
3. **Grow your network.** You review your draft skills on your phone and publish the ones that
   are right. People follow you.
4. **Learn from people.** Following someone shows their public skills. Their followers-only
   skills unlock with a one-time **Stripe** payment (test mode). A profile picture can be made
   with **MiniMax**, drawn in the design system's dots.

## The band

The Vexo Open band (microphone, motion sensor, colour LED, Bluetooth) is driven by `tacit
bridge`, on a laptop or a Raspberry Pi. One laptop drives one band; the team's bands are **16**
and **74**, and nothing ever connects to another band.

**Gestures**

| do this | and |
|---|---|
| draw an **X** or a **figure 8** in the air | **mute**: the mic is off within a second, the LED blinks white twice and goes dark, and the last 15 s are dropped |
| the same gesture, **then a double-tap** within 3 s | unmute (mute never times out; the app's unmute button works too) |
| **double-tap** | "keep that": the last minute becomes a kept moment |
| say "stop recording", "off the record", "don't record", … | anyone nearby can mute the band this way |

**Blue light = listening. No blue = not listening.** The app shows a blue *listening* pill only
while the band is listening.

**What it notices.** Advice given and received, explanations, lessons, questions, decisions,
commitments, recommendations, ideas, presenting, conversations, walking meetings, and from motion:
writing, drawing, whiteboard, typing and making. Each detection is a *moment*, private to the
wearer, in `#/moments`. Each kind can be turned off in `#/me`.

**What is shared.** Nothing, unless you choose it:

- advice you gave becomes a **draft** skill; it's public only after you publish it;
- a **pass** ("maya passed *open an update with the number* to ana") appears when two tacit
  wearers were in the same conversation and the giver publishes that skill;
- creative sessions ("ana sketched for 25 minutes") only if you turn on "share creative
  sessions" (off by default), with no content;
- a recommendation, lesson or idea only if you share it by hand.

Other people's words are never published or credited by name unless they are a tacit user
matched in the same conversation. Awareness of other bands goes through the tacit server,
never over Bluetooth. Raw motion never leaves the bridge; band audio goes only to Deepgram
(`mip_opt_out=true`) or sits in the offline buffer until it is transcribed, then is deleted.
Transcript segments are deleted after 24 hours, or at once on mute.

## Run it

```sh
scripts/bootstrap.sh          # clones ./vexo-open-kit, uv sync, creates .env from .env.example
# fill in .env (see .env.example: one line per setting)
.venv/bin/tacit doctor        # checks the kit, the band number, every key; never prints a key
.venv/bin/tacit serve         # http://127.0.0.1:8000 : landing page at /, the app at /app/
```

`SESSION_SECRET` and `VAPI_SERVER_SECRET` come from `openssl rand -hex 32`. Outbound calls go
only to the numbers in `CALL_ALLOWLIST` (E.164, comma-separated); empty means no outbound calls.

**Vapi.** Create or update the interview assistant (its webhook is `PUBLIC_BASE_URL/vapi/webhook`):

```sh
.venv/bin/tacit vapi-sync --dry-run   # prints the body, every secret as "***"
.venv/bin/tacit vapi-sync             # then add VAPI_ASSISTANT_ID=... to .env, as it says
```

For inbound calls, give the Vapi phone number **no fixed assistant** and set its server URL to
`PUBLIC_BASE_URL/vapi/webhook`: tacit answers `assistant-request` for people who signed up.
Put the number's id in `VAPI_PHONE_NUMBER_ID` and how to show it in `TACIT_PHONE_DISPLAY`.

**Stripe (test mode only; live keys are refused).** Forward test webhooks to your laptop:

```sh
stripe listen --forward-to localhost:8000/stripe/webhook   # prints whsec_... → STRIPE_WEBHOOK_SECRET
```

**The band.** Pair a band in the app (`#/me` → "your band"), put the two lines it shows in the
bridge's `.env`, then run the bridge. Close the kit's dashboard first (one Bluetooth connection
per band). Without a band, use the pretend one:

```sh
.venv/bin/tacit bridge --sim
```

**Tests.** `.venv/bin/ruff check . && .venv/bin/pytest -x -q` (no network: respx and fakes).

## Deploy (Fly.io)

The server runs as **one machine with one volume** (SQLite can't be shared), always on so the
Vapi and Stripe webhooks answer at once. Bridges are not deployed; they upload to the Fly app.

```sh
fly launch --no-deploy                                  # keep the existing fly.toml
fly volumes create tacit_data --region sjc --size 1
fly secrets set SESSION_SECRET=... VAPI_SERVER_SECRET=... VAPI_API_KEY=... \
  DEEPGRAM_API_KEY=... EXA_API_KEY=... TYPESAFE_API_KEY=... STRIPE_SECRET_KEY=... \
  STRIPE_WEBHOOK_SECRET=... OPENAI_API_KEY=... MINIMAX_API_KEY=... CALL_ALLOWLIST=...
fly deploy
fly logs
fly scale count 1                                       # never more than one machine
```

If the app can't write to `/data` on a fresh volume, run
`fly ssh console -C "chown -R 10001:10001 /data"` once.

Then:

- run `tacit vapi-sync` locally with `PUBLIC_BASE_URL=https://<app>.fly.dev`, and point the Vapi
  number's server URL at `https://<app>.fly.dev/vapi/webhook`;
- in the Stripe dashboard (test mode) add the webhook `https://<app>.fly.dev/stripe/webhook` for
  `checkout.session.completed`, and put its signing secret in `STRIPE_WEBHOOK_SECRET`;
- set each bridge's `TACIT_SERVER_URL` to `https://<app>.fly.dev`.

Back up the database by hand: `fly ssh console -C "sqlite3 /data/tacit.db .dump" > backup.sql`.

## Privacy

- Consent is explicit and unticked by default. No lookup without "look me up", no call without
  "tacit may call me".
- We keep the skills you approve, not call audio, transcripts or recording URLs.
- Your own photo goes to MiniMax only with your ticked consent and is never stored; only the
  dot picture is kept.
- "Delete everything" deletes every row about you.
- Logs never hold names, phone numbers, skill text, transcripts or keys.

## Stack

| piece | job |
|---|---|
| [Vexo Open band](https://github.com/VexoAI-Org/vexo-open-kit) | the wristband: mic, motion, LED, Bluetooth |
| [Deepgram](https://deepgram.com) | Nova-3 speech to text, Aura voice |
| [Exa](https://exa.ai) | looking a person up from what they gave |
| Jev ([TypeSafe](https://typesafe.ai)) | typed questions: is this a real skill? what kind of moment is this? |
| [Vapi](https://vapi.ai) | the interview phone call |
| [Stripe](https://stripe.com) | one-time unlocks, test mode |
| [MiniMax](https://www.minimax.io) | profile pictures, kept only as dots |
| FastAPI + SQLite, a no-build PWA | the server and the app |

Python 3.11, managed with [uv](https://docs.astral.sh/uv/).
