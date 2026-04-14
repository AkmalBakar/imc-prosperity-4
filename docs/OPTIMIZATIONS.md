# Strategy optimization backlog

Current backtest: **187,107 XIRECs / 3 days** (osmium 17.6k + pepper root 169.5k). Target 200k before end of day 2, so we need ~100k/day. Ideas below are ranked by expected_value ÷ effort.

Items are **not yet implemented** — pick them off one at a time and re-run `make quick R=1` after each to measure impact.

## Osmium (`OsmiumTrader` in `traders/trader.py`) — currently ~5k/day

### O1. Tighter σ (30 min, +5-10k/day expected)
`SIGMA_BOUND = 7` (was 11). The 11 came from the 99th-percentile deviation, so we almost never hit `|z| = 1`. Using the 95th pct (~±7) reaches full target inventory at smaller deviations → bigger average position.

**Risk**: slightly more overshoot past the bounds, but the process is provably stationary (ADF p ≈ 1e-6), so this is safe.

### O2. Tighter make spread (10 min, +3-5k/day)
`SPREAD = 1` (was 2). Halves the edge demanded per fill, doubles the fill rate. For a strongly stationary series the extra fills dominate the lost per-fill edge.

### O3. Walk the book on take (1 hr, +5-10k/day)
The current take loop stops at `sp > fair`. For a strong reversion signal (`|z| > 0.5`) paying `fair + 1` or `fair + 2` to lift a heavy offer is +EV — it'll likely revert within a half-life (~30 ticks).

Change the stop condition to `sp > fair + edge_cap(z)` where `edge_cap = max(0, round(abs(z) * 3))` (at `|z|=1` we'll pay up to 3 ticks past fair).

### O4. z-scaled make size (30 min, smaller +ve)
Currently we quote full `max_allowed_*_volume` at all times. Near fair (`z ≈ 0`) this just stacks inventory uselessly. Gate size on signal: `size = capacity * max(0.3, abs(z))`.

Keeps a small base quote for market-making income but goes heavy only when signal is real.

## Pepper root (`PepperRootTrader` in `traders/trader.py`) — currently ~55k/day

### P1. Enable overbid/underbid (10 min, +10-15k/day)
The logic is already written and commented out in `get_orders` (around lines 297-308, labeled "OVERBID / UNDERBID"). Frankfurt's Kelp trader used the same pattern and gained ~30% fills. Just uncomment and test.

**Why it works**: quoting one tick ahead of the best bid/ask (when there's still room inside predicted mid) gives queue priority and fills we'd otherwise miss.

### P2. Shorter history (10 min, mixed impact)
`HISTORY = 100` instead of 200. Adapts to drift changes twice as fast.

**Risk**: Noisier slope estimate → more whipsaw quotes on flat stretches. Benchmark both.

### P3. Multi-level take (1 hr, +5k/day)
When the OLS slope is steep, also take the ask one tick past `mid_pred` — it's likely +EV by next tick. Logic:

```python
slope_strength = abs(bid_pred - bids[-1])  # tick-distance we're forecasting
extra_ticks = min(int(slope_strength), 2)
for sp, sv in self.mkt_sell_orders.items():
    if sp < mid_pred + extra_ticks:
        self.bid(sp, sv)
```

Same symmetric change for the sell side.

## Suggested execution order

1. **O1 + O2** together — both are one-line parameter changes with a combined +8-15k/day upside.
2. **P1** — uncomment the overbid/underbid block.
3. Benchmark. If still short of 100k/day:
4. **O3** (walk the book) — biggest remaining osmium lever.
5. **P3** (multi-level pepper take).
6. **O4**, **P2** for polish.

Each step: `make quick R=1`, record `Round 1 total`. Git-commit after each meaningful change so we can bisect regressions.
