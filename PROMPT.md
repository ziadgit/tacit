# Build tacit (unattended, 150-minute time box)

Run from the repo root:

    claude --dangerously-skip-permissions -p "$(cat PROMPT.md)"

You are running with `--dangerously-skip-permissions` in this repo. Build what `SPEC.md`
describes by working through `fix_plan.md` top to bottom, in this one session, in **150 minutes
of wall-clock time**.

## Start

1. Run `date +%s > .build_start` (it's gitignored). That is t=0.
2. Read `SPEC.md` in full (the source of truth, **§0 safety rules first**), `fix_plan.md`,
   `CLAUDE.md`, `design-system/README.md`, `.claude/skills/build-with-exa/SKILL.md`, and before any band item
   `vexo-open-kit/AGENTS.md` and `vexo-open-kit/projects/gesture-trainer/recogniser.js`.
3. `uv sync`, then `.venv/bin/ruff check . && .venv/bin/pytest -x -q` must pass before you begin.

## For each unchecked `- [ ]` item, in order

1. **Check the clock:** `echo $(( $(date +%s) - $(cat .build_start) ))`. If 145 minutes (8700 s)
   or more have passed, go to "Finish" now.
2. **Implement the item fully.** No `TODO`s, no stubs, no placeholder data in the product.
   Tests sit beside the code (`foo.py` → `foo_test.py`).
3. **Verify:** `.venv/bin/ruff check . --fix && .venv/bin/ruff check . && .venv/bin/pytest -x -q`.
   Fix any failure before moving on.
4. **Record:** check the item off (`[ ]` → `[x]`), add any gotcha to "Gotchas" in `CLAUDE.md`,
   then `git add -A && git commit -m "<scope>: <what>"`. Check that `git status` never shows
   `.env` or `vexo-open-kit/`.

## Rules

- **SPEC.md §0 overrides everything.** In short: no live calls to Exa, TypeSafe, Deepgram,
  Vapi or Stripe; never place a phone call or a payment; never deploy (no `fly` commands);
  never connect to a real band; never touch secrets; never edit `vexo-open-kit/`, `landing/` or `design-system/`; **never
  `git push`**.
- Be fast and decisive. Don't explore beyond what the item needs. SPEC.md decisions are final.
  If something is impossible as written, make the smallest change and note it in `CLAUDE.md`.
- To learn an SDK's real names (exa-py, typesafe-sdk, stripe), inspect the installed package in
  `.venv` instead of guessing.
- Never use `alert()`, `confirm()` or `prompt()` in the PWA, and don't open a browser.
- Stay inside this repo.

## Finish

Make sure the last commit has passing tests. Then print: the minutes elapsed, the items done
and still pending, and the `## Discovered` follow-ups from `fix_plan.md`. Stop. Don't push.
