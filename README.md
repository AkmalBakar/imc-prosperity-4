# Alpha Singularity — IMC Prosperity 4

Workspace for our IMC Prosperity 4 submission. The actual submission is a single file:
`traders/trader.py`. Everything else here exists to backtest it and visualize the results.

## Install

One command, from this directory:

```bash
make install
```

That script is idempotent — rerun it any time. It will:

1. Install **[uv](https://docs.astral.sh/uv/)** (Python package manager) if missing.
2. `uv sync --extra viz` — syncs the Python env. uv fetches Python 3.11 automatically if the system lacks it.
3. Install **Rust** via [rustup](https://rustup.rs/) if missing (the backtester is written in Rust; it needs a recent toolchain, `edition2024` = cargo ≥ 1.85).
4. Build `backtester/` in release mode (~3 min the first time, cached afterwards).
5. Run a smoke-test backtest to confirm everything works.

On a fresh machine you will likely need to **open a new shell afterwards** so the newly-installed `uv` and `cargo` land on your `PATH` (they're added to `~/.bashrc` / `~/.profile`). `make` commands already prepend `~/.cargo/bin` themselves, so they work without reloading.

### Manual prerequisites (only if auto-install fails)

- `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Python ≥ 3.11: `uv python install 3.11` (or your system package manager)
- Rust toolchain: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh` then `source ~/.cargo/env`. Minimum `cargo 1.85`.
- On macOS the Rust step also needs `xcode-select --install` for the linker.
- On Windows use WSL2 (Ubuntu) and run the commands there — native Windows is not supported.

## Run the visualizer

```bash
make viz-local
```

Then open <http://localhost:8050>. From the Dash UI you can pick a round/day, kick off
a backtest, and load logs — no terminal juggling needed.

### Using logs from elsewhere

If you have a `.log` file from somewhere else (an official IMC submission log, a
teammate's backtest, a run on another machine), drop it into `backtests/` at the repo
root. The viz scans that directory and the file will appear in the log picker.

## Other commands

All run from this directory. `R` is the round, `D` the day (omit `D` to run every day in the round).

| Command              | What it does                                                      |
| -------------------- | ----------------------------------------------------------------- |
| `make bt R=1 D=0`    | Backtest round 1 day 0; drop `.log` into `backtests/`             |
| `make bt R=1`        | Backtest all days in round 1                                      |
| `make quick R=1`     | Backtest without saving a log (fastest iteration)                 |
| `make build`         | Rebuild `backtester/target/release/rust_backtester` in release    |
| `make clean-logs`    | Delete `backtests/*.log`                                          |

Extra `rust_backtester` flags pass through via `FLAGS=`, e.g.:

- `FLAGS="--trade-match-mode worse"` — how the backtester fills against historical trades.
- `FLAGS="--queue-penetration 0.5"` — how aggressively passive quotes eat the book.
- `FLAGS="--persist"` — keep the full replay bundle under `backtester/runs/`.

To run a different trader file, override `ALGO`: `make bt ALGO=traders/trader_brute_force.py R=1`.

## Repo layout

```
.
├── traders/              # trader.py is the live submission; siblings are alternates
├── backtester/           # Rust backtester (Geyzson) — datasets/ + src/ + built binary
├── backtester_archive/   # old Python backtester — kept for reference, not wired up
├── viz/                  # local Dash visualizer (viz.py)
├── scripts/              # setup.sh + import_rust_run.sh
├── backtests/            # generated .log files land here (drop external logs here too)
└── Makefile              # install / build / bt / quick / viz-local / clean-logs
```

## Submission contract

`Trader.run(state: TradingState) -> (orders_dict, conversions_int, traderData_str)`.
`traderData` is the only state that persists between ticks. Don't import anything that
wouldn't exist in the competition sandbox (stdlib + `numpy` OK; the local `datamodel`
module gets replaced at submission time).

## Round 1 products

- **ASH_COATED_OSMIUM** — bounded mean reversion, channel ≈ 10000 ± 8. Stationary
  (ADF p ≈ 1e-6), half-life ≈ 30 ticks.
- **INTARIAN_PEPPER_ROOT** — near-linear upward drift. Buy-and-hold dominates.

Position limit: **80** each (set in both `traders/trader.py` and
`backtester/prosperity4bt/data.py`).

## Troubleshooting

- **`uv: command not found`** — open a new shell, or `source ~/.bashrc`. If still missing, run the manual `uv` install one-liner above.
- **`cargo: command not found`** — same: new shell or `source ~/.cargo/env`. `make` targets work without this because they prepend `~/.cargo/bin` to `PATH` themselves.
- **`feature edition2024 is required`** — your system `cargo` is older than 1.85. You have two toolchains and the older one is winning on `PATH`. Reinstall rustup stable (`rustup update`) and make sure `~/.cargo/bin` comes before `/usr/bin` in your shell's `PATH`.
- **`libpython3.X.so.1.0: cannot open shared object file`** — the binary was built inside an active venv (e.g. uv's managed Python). Run `make rebuild` — it cleans `backtester/target/` and recompiles with `VIRTUAL_ENV` stripped and `PYO3_PYTHON` pinned to the system `python3`, so the binary links against a libpython that's always on the loader path.
- **`Python >=3.11 required`** — `uv python install 3.11`, then rerun `make install`.
- **`Address already in use` on port 8050** — another Dash process is running; `lsof -i :8050` then kill, or pass `--port` to `viz/viz.py`.
- **Viz shows no logs** — confirm `.log` files exist under `backtests/`. `make clean-logs` resets the folder.
- **Smoke test fails during setup** — full output is at `/tmp/p4_smoke.log`.
