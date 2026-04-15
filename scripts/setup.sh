#!/usr/bin/env bash
# One-shot installer. Requires uv and Python >= 3.11 pre-installed.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> uv sync (core + viz)"
uv sync --extra viz

echo "==> smoke test: round 1 day 0"
uv run prosperity4btest traders/trader.py 1-0 --no-out >/tmp/p4_smoke.log 2>&1 \
  && tail -n 6 /tmp/p4_smoke.log \
  || { echo "Smoke test failed. See /tmp/p4_smoke.log"; exit 1; }

cat <<'EOF'

Setup OK. Common commands:
  make quick R=1        # backtest round 1, no viz
  make viz-local        # local Dash visualizer at http://localhost:8050
  make bt R=1 D=0       # backtest + upstream visualizer

See README.md for more.
EOF
