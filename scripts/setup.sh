#!/usr/bin/env bash
# One-shot installer. Auto-installs uv + rustup if missing; otherwise just syncs
# the Python env and builds the Rust backtester. Safe to rerun.
set -euo pipefail

cd "$(dirname "$0")/.."

need_path_reload=0

# --- uv ------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "==> installing uv (Python package manager)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    need_path_reload=1
fi

# --- Python 3.11 ---------------------------------------------------------
# `uv sync` will fetch a managed interpreter if the system lacks one, so no
# explicit version check is needed — but tell the user what's happening.
echo "==> uv sync (core + viz) — will fetch Python 3.11 if missing"
uv sync --extra viz

# --- Rust toolchain ------------------------------------------------------
# Our Makefile prepends ~/.cargo/bin to PATH, but setup.sh runs outside make,
# so we need to activate the env manually if rustup just installed.
if ! command -v cargo >/dev/null 2>&1 || ! cargo --version 2>/dev/null | grep -qvE '^cargo 1\.(7[0-9]|8[0-4])\b'; then
    if [ ! -x "$HOME/.cargo/bin/cargo" ]; then
        echo "==> installing rust via rustup (needed for the backtester)"
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
        need_path_reload=1
    fi
    # shellcheck source=/dev/null
    . "$HOME/.cargo/env"
fi

echo "==> building rust_backtester (release) — a few minutes first time, cached after"
( cd backtester && cargo build --release )

# --- Smoke test ----------------------------------------------------------
echo "==> smoke test: round 1 day 0"
./backtester/target/release/rust_backtester \
    --trader traders/trader.py --dataset round1 --day 0 \
    --artifact-mode none >/tmp/p4_smoke.log 2>&1 \
  && tail -n 6 /tmp/p4_smoke.log \
  || { echo "Smoke test failed. See /tmp/p4_smoke.log"; exit 1; }

echo
echo "Setup OK. Common commands:"
echo "  make bt R=1 D=0       # backtest, drop log into backtests/"
echo "  make quick R=1        # backtest without saving a log"
echo "  make viz-local        # local Dash visualizer at http://localhost:8050"
echo
if [ "$need_path_reload" = "1" ]; then
    echo "NOTE: uv and/or cargo were just installed. Open a new shell (or run"
    echo "      'source ~/.bashrc') before using them outside of make."
fi
