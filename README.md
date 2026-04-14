# Prosperity 4

IMC Prosperity 4 trading challenge workspace. Single-file submission: `traders/trader.py`.

## Quickstart

```bash
# one-shot install (requires uv + Python ≥ 3.11)
./scripts/setup.sh        # or: make install

# daily workflow
make quick R=1            # backtest round 1, no viz
make viz-local            # local Dash visualizer at http://localhost:8050
make bt R=1 D=0           # backtest one day + upstream hosted viz
```

See `docs/OPTIMIZATIONS.md` for the current strategy backlog.

## Repo layout

```
prosperity4/
├── traders/              # trader.py submissions (one is live per backtest)
├── backtester/           # prosperity4btest (editable clone, round data bundled)
├── viz/                  # local Dash visualizer (viz.py)
├── research/             # jupyter notebooks — per-product analysis
├── docs/                 # strategy notes (see OPTIMIZATIONS.md)
├── scripts/setup.sh      # one-shot installer
└── Makefile              # bt / quick / merge / viz-local / install / clean-logs
```

## Submission contract

`Trader.run(state: TradingState) -> (orders_dict, conversions_int, traderData_str)`.
`traderData` is the only state that persists between ticks. Don't import anything that wouldn't exist in the competition sandbox (stdlib + numpy OK; local `datamodel` gets replaced at submission time).

## Round 1 products

- **ASH_COATED_OSMIUM** — bounded mean reversion, channel ≈ 10000 ± 8. Stationary (ADF p ≈ 1e-6), half-life ≈ 30 ticks. See `research/osmium.ipynb`.
- **INTARIAN_PEPPER_ROOT** — near-linear drift. Local OLS forecast on wall-bid/ask history. See `research/round1.ipynb`.

Position limit: **80** each (set in both `traders/trader.py` and `backtester/prosperity4bt/data.py`).

## Architecture

- **Trader** owns fair-value estimation and publishes `traderData["<key>"]["viz"] = {fair, wall_mid, ...}` each tick for the viz to render.
- **Backtester** is the authoritative PnL source (resets per-day, liquidates open positions at EOD). Its `profit_and_loss` CSV column is what we plot.
- **Viz** renders what's already computed — never recomputes PnL or fair.

## Useful flags (`FLAGS=`)

- `--print` — stream trader stdout (debugging).
- `--match-trades worse|all|none` — how the backtester fills against historical trades.
- `--limit EMERALDS:80` — override a product limit per-run.
- `--no-out` — skip log file.

## Running in the Docker sandbox

`sandbox/docker-claude/sandbox_claude.sh` rsyncs this tree into an isolated container. Inside the container, run `./scripts/setup.sh` and you're set.
