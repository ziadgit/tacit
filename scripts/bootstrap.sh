#!/usr/bin/env bash
# One-time setup for a teammate's laptop. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d vexo-open-kit ]; then
  git clone https://github.com/VexoAI-Org/vexo-open-kit.git
else
  git -C vexo-open-kit pull --ff-only
fi
uv sync
[ -f .env ] || { cp .env.example .env; echo "Created .env: fill in your keys and TACIT_BAND."; }
git status --porcelain | grep -q '\.env$' && { echo "ERROR: .env is not ignored"; exit 1; } || true
echo "Done. Next: .venv/bin/tacit doctor"
