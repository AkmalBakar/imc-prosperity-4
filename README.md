# Alpha Singularity — IMC Prosperity 4

Workspace for our IMC Prosperity 4 submission. The actual submission is a single file:
`traders/trader.py`. Everything else here exists to backtest it and visualize the results.

## Prerequisites

You need **[uv](https://docs.astral.sh/uv/)** and **Python ≥ 3.11**. That's it.

Install `uv` (one-liner, Linux/macOS/WSL):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If you don't already have Python 3.11+:

```bash
uv python install 3.11
```

## Setup

From this directory:

```bash
./scripts/setup.sh          # or: make install
```

This runs `uv sync --extra viz` and a smoke-test backtest. On success it prints the
last few lines of the backtest output. Everything after this uses `uv run` under the
hood, so you never need to activate a venv manually.

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

All run from this directory. `R` is the round, `D` the day (`-1` or omitted = all days).

| Command                      | What it does                                           |
| ---------------------------- | ------------------------------------------------------ |
| `make quick R=1`             | Backtest round 1 without launching the hosted viz     |
| `make bt R=1 D=0`            | Backtest round 1 day 0 + open upstream hosted viz     |
| `make merge R=1`             | Backtest with PnL merged across days                  |
| `make viz-run R=1 D=0`       | Backtest and feed the log straight into the local viz |
| `make clean-logs`            | Delete `backtests/*.log`                              |

Extra CLI flags pass through via `FLAGS=`:

- `FLAGS=--print` — stream trader stdout (debugging crashes).
- `FLAGS="--match-trades worse"` — control how the backtester fills against historical trades.
- `FLAGS="--limit ASH_COATED_OSMIUM:50"` — override a product's position limit for one run.
- `FLAGS=--no-out` — don't write a log file.

To run a different trader file, override `ALGO`: `make quick ALGO=traders/trader_brute_force.py R=1`.

## Repo layout

```
.
├── traders/              # trader.py is the live submission; siblings are alternates
├── backtester/           # prosperity4btest (editable clone, round data bundled)
├── viz/                  # local Dash visualizer (viz.py)
├── scripts/setup.sh      # one-shot installer
├── backtests/            # generated .log files land here (drop external logs here too)
└── Makefile              # install / bt / quick / merge / viz-local / viz-run / clean-logs
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

- **`uv: command not found`** — restart your shell after installing `uv`, or add
  `~/.local/bin` to `PATH`.
- **`Python >=3.11 required`** — run `uv python install 3.11` and retry `./scripts/setup.sh`.
- **`Address already in use` on port 8050** — another Dash process is running. Kill it
  (`lsof -i :8050`) or set `VIZ_PORT` in your shell before `make viz-local`.
- **Viz shows no logs** — confirm `.log` files exist under `backtests/`. If you renamed
  your trader, old logs still appear; `make clean-logs` resets the folder.
- **Smoke test fails during setup** — see `/tmp/p4_smoke.log` for the full backtester output.
