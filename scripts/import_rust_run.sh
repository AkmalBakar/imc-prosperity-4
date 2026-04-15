#!/usr/bin/env bash
# After a Rust backtest, move submission.log files from backtests/_rust/ up
# into backtests/ so the viz picks them up, tagged with a timestamp + trader name.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUST_DIR="$ROOT/backtests/_rust"
DEST="$ROOT/backtests"

[ -d "$RUST_DIR" ] || exit 0

ts="$(date +%m%d-%H%M%S)"
found=0
while IFS= read -r -d '' f; do
    name="$(basename "$(dirname "$f")")"  # e.g. round1-day-0
    cp "$f" "$DEST/${ts}-rust-${name}.log"
    found=1
done < <(find "$RUST_DIR" -type f -name 'submission.log' -print0)

rm -rf "$RUST_DIR"

if [ "$found" = "1" ]; then
    echo "Imported rust logs → $DEST/${ts}-rust-*.log"
fi
