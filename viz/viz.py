"""Local Dash visualizer for Prosperity 4 backtests.

Usage:
    uv run --extra viz python viz.py              # start server, pick logs in browser
    uv run --extra viz python viz.py --port 8051  # custom port
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

try:
    import dash
    import plotly.graph_objects as go
    from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update
    from plotly.subplots import make_subplots
except ImportError:
    print("Missing dependencies. Run: uv sync --extra viz")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
BACKTESTS_DIR = ROOT / "backtests"
TRADERS_DIR = ROOT / "traders"


def get_available_traders() -> list[str]:
    if not TRADERS_DIR.exists():
        return []
    return sorted(p.name for p in TRADERS_DIR.glob("*.py") if not p.name.startswith("_"))


def sanitize_run_name(name: str) -> str:
    name = (name or "").strip().replace(" ", "-")
    return "".join(c for c in name if c.isalnum() or c in "-_") or "run"


# ---------------------------------------------------------------------------
# Log parser
# ---------------------------------------------------------------------------

def _split_sections(text: str) -> tuple[str, str, str]:
    """Split a .log file into its three sections."""
    act_marker = "\n\n\nActivities log:\n"
    trade_marker = "\n\n\n\n\nTrade History:\n"

    act_idx = text.index(act_marker)
    trade_idx = text.index(trade_marker)

    sandbox_text = text[len("Sandbox logs:\n"):act_idx]
    activities_text = text[act_idx + len(act_marker):trade_idx]
    trades_text = text[trade_idx + len(trade_marker):]

    return sandbox_text, activities_text, trades_text


def _parse_sandbox_logs(text: str) -> list[dict]:
    """Parse a stream of JSON objects from the sandbox logs section.

    Uses json.JSONDecoder.raw_decode so escaped braces inside string values
    (e.g. the lambdaLog field) don't confuse depth tracking.
    """
    entries: list[dict] = []
    dec = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        entries.append(obj)
        i = end
    return entries


def _parse_activities(text: str) -> list[dict]:
    """Parse semicolon-delimited activities CSV (skip header)."""
    rows = []
    lines = text.strip().split("\n")
    if not lines:
        return rows
    # Skip header line
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split(";")
        if len(cols) < 17:
            continue
        rows.append({
            "day": int(cols[0]),
            "timestamp": int(cols[1]),
            "product": cols[2],
            "bid_prices": [int(cols[i]) for i in (3, 5, 7) if cols[i]],
            "bid_volumes": [int(cols[i]) for i in (4, 6, 8) if cols[i]],
            "ask_prices": [int(cols[i]) for i in (9, 11, 13) if cols[i]],
            "ask_volumes": [int(cols[i]) for i in (10, 12, 14) if cols[i]],
            "mid_price": float(cols[15]) if cols[15] else None,
            "pnl": float(cols[16]) if cols[16] else 0.0,
        })
    return rows


def _parse_trades(text: str) -> list[dict]:
    """Parse the Trade History JSON array."""
    text = text.strip()
    if not text or text == "[]":
        return []
    # The backtester writes trailing commas inside objects (e.g. "quantity": 2,\n  })
    # Strip them so standard json.loads works.
    import re
    text = re.sub(r",\s*}", "}", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


def _decompress_sandbox(entries: list[dict]) -> list[dict]:
    """Extract trader orders and position from lambdaLog entries."""
    rows = []
    for entry in entries:
        ts = entry["timestamp"]
        ll = entry.get("lambdaLog", "")
        if not ll:
            rows.append({"timestamp": ts, "orders": [], "position": {}, "order_depths": {}})
            continue
        try:
            data = json.loads(ll)
        except json.JSONDecodeError:
            rows.append({"timestamp": ts, "orders": [], "position": {}, "order_depths": {}})
            continue
        state = data[0]  # [ts, traderData, listings, order_depths, own_trades, market_trades, position, obs]
        orders = data[1] if len(data) > 1 else []  # [[symbol, price, qty], ...]
        position = state[6] if len(state) > 6 else {}
        order_depths = state[3] if len(state) > 3 else {}
        td_out = data[3] if len(data) > 3 else ""
        try:
            trader_data = json.loads(td_out) if td_out else {}
        except json.JSONDecodeError:
            trader_data = {}
        rows.append({
            "timestamp": ts,
            "orders": orders,
            "position": position,
            "order_depths": order_depths,
            "trader_data": trader_data,
        })
    return rows


# Mapping product symbol -> per-trader traderData key (trader.py subclass KEY attr)
PRODUCT_TRADER_KEY = {
    "ASH_COATED_OSMIUM": "osm",
    "INTARIAN_PEPPER_ROOT": "ppr",
}


def parse_log(filepath: Path) -> dict:
    """Parse a .log file and return structured data for visualization."""
    text = filepath.read_text(encoding="utf-8")
    sandbox_text, activities_text, trades_text = _split_sections(text)

    sandbox_entries = _parse_sandbox_logs(sandbox_text)
    activities = _parse_activities(activities_text)
    trades = _parse_trades(trades_text)
    sandbox_data = _decompress_sandbox(sandbox_entries)

    # Discover products
    products = sorted({r["product"] for r in activities})

    return {
        "activities": activities,
        "trades": trades,
        "sandbox": sandbox_data,
        "products": products,
    }


# Cache parsed logs keyed on (path, mtime) so re-selecting is instant
@lru_cache(maxsize=8)
def cached_parse_log(filepath: str, mtime: float) -> dict:
    return parse_log(Path(filepath))


def load_log(filepath: Path) -> dict:
    return cached_parse_log(str(filepath), filepath.stat().st_mtime)


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def build_charts(data: dict, product: str) -> go.Figure:
    """Build a single figure with three stacked subplots sharing the x-axis."""
    activities = [r for r in data["activities"] if r["product"] == product]
    trades = [t for t in data["trades"] if t["symbol"] == product]
    sandbox = data["sandbox"]

    # --- Gather data ---
    # Market bids/asks from activities
    bid_ts, bid_prices, bid_sizes = [], [], []
    ask_ts, ask_prices, ask_sizes = [], [], []
    mid_ts, mid_prices = [], []
    pnl_ts, pnl_vals = [], []
    day_boundaries: list[int] = []
    prev_day = None

    for r in activities:
        t = r["timestamp"]
        if prev_day is not None and r["day"] != prev_day:
            day_boundaries.append(t)
        prev_day = r["day"]
        for p, v in zip(r["bid_prices"], r["bid_volumes"]):
            bid_ts.append(t)
            bid_prices.append(p)
            bid_sizes.append(v)
        for p, v in zip(r["ask_prices"], r["ask_volumes"]):
            ask_ts.append(t)
            ask_prices.append(p)
            ask_sizes.append(v)
        if r["mid_price"] is not None and r["mid_price"] != 0:
            mid_ts.append(t)
            mid_prices.append(r["mid_price"])
        pnl_ts.append(t)
        pnl_vals.append(r["pnl"])

    # Trader-published fair value (each tick). Read from traderData under the
    # trader's product key, e.g. {"osm": {"viz": {"fair": ..., "wall_mid": ...}}}.
    trader_key = PRODUCT_TRADER_KEY.get(product)
    fair_ts, fair_vals = [], []
    wall_ts, wall_mids = [], []
    if trader_key:
        for s in sandbox:
            td = s.get("trader_data") or {}
            slot = td.get(trader_key) or {}
            viz_blob = slot.get("viz") or {}
            f = viz_blob.get("fair")
            wm = viz_blob.get("wall_mid")
            if f is not None:
                fair_ts.append(s["timestamp"])
                fair_vals.append(f)
            if wm is not None:
                wall_ts.append(s["timestamp"])
                wall_mids.append(wm)

    # Trader's submitted orders from sandbox lambdaLog
    own_buy_ts, own_buy_prices, own_buy_qty = [], [], []
    own_sell_ts, own_sell_prices, own_sell_qty = [], [], []
    pos_ts, pos_vals = [], []

    for s in sandbox:
        t = s["timestamp"]
        for order in s["orders"]:
            if order[0] != product:
                continue
            price, qty = order[1], order[2]
            if qty > 0:
                own_buy_ts.append(t)
                own_buy_prices.append(price)
                own_buy_qty.append(qty)
            elif qty < 0:
                own_sell_ts.append(t)
                own_sell_prices.append(price)
                own_sell_qty.append(abs(qty))
        pos_vals.append(s["position"].get(product, 0))
        pos_ts.append(t)

    # Fills from trade history — split into own vs market
    fill_buy_ts, fill_buy_prices, fill_buy_qty = [], [], []
    fill_sell_ts, fill_sell_prices, fill_sell_qty = [], [], []
    mkt_ts, mkt_prices, mkt_qty = [], [], []

    for t in trades:
        buyer = t.get("buyer")
        seller = t.get("seller")
        if buyer == "SUBMISSION":
            fill_buy_ts.append(t["timestamp"])
            fill_buy_prices.append(t["price"])
            fill_buy_qty.append(t["quantity"])
        elif seller == "SUBMISSION":
            fill_sell_ts.append(t["timestamp"])
            fill_sell_prices.append(t["price"])
            fill_sell_qty.append(t["quantity"])
        else:
            mkt_ts.append(t["timestamp"])
            mkt_prices.append(t["price"])
            mkt_qty.append(t["quantity"])

    # Volume scaling for marker sizes
    all_vols = bid_sizes + ask_sizes
    max_vol = max(all_vols) if all_vols else 1
    size_scale = 18 / max(max_vol, 1)

    # --- Combined figure: 3 stacked subplots sharing x-axis ---
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.14, 0.14],
        vertical_spacing=0.03,
    )

    # Row 1 — Price
    fig.add_trace(go.Scattergl(
        x=bid_ts, y=bid_prices, mode="markers",
        marker=dict(color="rgba(55, 128, 255, 0.5)",
                    size=[max(v * size_scale, 3) for v in bid_sizes],
                    line=dict(width=0)),
        name="Bids",
        text=[f"Bid: {p} x {v}" for p, v in zip(bid_prices, bid_sizes)],
        hoverinfo="text+x",
    ), row=1, col=1)

    fig.add_trace(go.Scattergl(
        x=ask_ts, y=ask_prices, mode="markers",
        marker=dict(color="rgba(255, 75, 75, 0.5)",
                    size=[max(v * size_scale, 3) for v in ask_sizes],
                    line=dict(width=0)),
        name="Asks",
        text=[f"Ask: {p} x {v}" for p, v in zip(ask_prices, ask_sizes)],
        hoverinfo="text+x",
    ), row=1, col=1)

    if mid_ts:
        fig.add_trace(go.Scattergl(
            x=mid_ts, y=mid_prices, mode="lines",
            line=dict(color="rgba(150, 150, 150, 0.6)", width=1),
            name="Mid",
        ), row=1, col=1)

    if wall_ts:
        fig.add_trace(go.Scattergl(
            x=wall_ts, y=wall_mids, mode="lines",
            line=dict(color="rgba(120, 20, 180, 0.9)", width=1.4),
            name="Trader wall mid",
        ), row=1, col=1)

    if fair_ts:
        fig.add_trace(go.Scattergl(
            x=fair_ts, y=fair_vals, mode="lines",
            line=dict(color="rgba(200, 0, 120, 0.9)", width=1.6),
            name="Trader fair",
        ), row=1, col=1)

    if own_buy_ts:
        fig.add_trace(go.Scattergl(
            x=own_buy_ts, y=own_buy_prices, mode="markers",
            marker=dict(color="rgba(0, 200, 0, 0.95)", symbol="triangle-up", size=11,
                        line=dict(width=1.2, color="black")),
            name="My Buy Orders",
            text=[f"Buy order: {p} x {q}" for p, q in zip(own_buy_prices, own_buy_qty)],
            hoverinfo="text+x",
        ), row=1, col=1)

    if own_sell_ts:
        fig.add_trace(go.Scattergl(
            x=own_sell_ts, y=own_sell_prices, mode="markers",
            marker=dict(color="rgba(255, 140, 0, 0.95)", symbol="triangle-down", size=11,
                        line=dict(width=1.2, color="black")),
            name="My Sell Orders",
            text=[f"Sell order: {p} x {q}" for p, q in zip(own_sell_prices, own_sell_qty)],
            hoverinfo="text+x",
        ), row=1, col=1)

    if mkt_ts:
        fig.add_trace(go.Scattergl(
            x=mkt_ts, y=mkt_prices, mode="markers",
            marker=dict(color="rgba(40, 40, 40, 0.9)", symbol="x-thin", size=8,
                        line=dict(width=1.8, color="rgba(40, 40, 40, 0.9)")),
            name="Market Trades",
            text=[f"Market: {p} x {q}" for p, q in zip(mkt_prices, mkt_qty)],
            hoverinfo="text+x",
        ), row=1, col=1)

    if fill_buy_ts:
        fig.add_trace(go.Scattergl(
            x=fill_buy_ts, y=fill_buy_prices, mode="markers",
            marker=dict(color="lime", symbol="star", size=13,
                        line=dict(width=1.5, color="darkgreen")),
            name="My Buy Fills",
            text=[f"Bought: {p} x {q}" for p, q in zip(fill_buy_prices, fill_buy_qty)],
            hoverinfo="text+x",
        ), row=1, col=1)

    if fill_sell_ts:
        fig.add_trace(go.Scattergl(
            x=fill_sell_ts, y=fill_sell_prices, mode="markers",
            marker=dict(color="red", symbol="star", size=13,
                        line=dict(width=1.5, color="darkred")),
            name="My Sell Fills",
            text=[f"Sold: {p} x {q}" for p, q in zip(fill_sell_prices, fill_sell_qty)],
            hoverinfo="text+x",
        ), row=1, col=1)

    # Row 2 — PnL from the backtester (MtM, resets per day)
    fig.add_trace(go.Scattergl(
        x=pnl_ts, y=pnl_vals, mode="lines",
        line=dict(color="#00a784", width=2),
        name="PnL", fill="tozeroy",
        fillcolor="rgba(0, 167, 132, 0.1)",
        showlegend=False,
    ), row=2, col=1)

    # Row 3 — Position
    fig.add_trace(go.Scattergl(
        x=pos_ts, y=pos_vals, mode="lines",
        line=dict(color="#ff9f43", width=2, shape="hv"),
        name="Position",
        showlegend=False,
    ), row=3, col=1)

    # Axis styling — spike crosses all three rows because xaxes are shared
    spike_kwargs = dict(
        showgrid=True, gridcolor="rgba(0,0,0,0.08)",
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikethickness=1, spikecolor="#666",
    )
    fig.update_xaxes(**spike_kwargs)
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)

    for bx in day_boundaries:
        for r in (1, 2, 3):
            fig.add_vline(x=bx, line=dict(color="rgba(0,0,0,0.25)", width=1, dash="dash"), row=r, col=1)
    fig.update_yaxes(title_text="Price", showgrid=True, gridcolor="rgba(0,0,0,0.08)", row=1, col=1)
    pnl_axis_kwargs = dict(title_text="PnL", showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    if pnl_vals:
        sorted_pnl = sorted(pnl_vals)
        lo = sorted_pnl[int(len(sorted_pnl) * 0.01)]
        hi = sorted_pnl[int(len(sorted_pnl) * 0.99)]
        pad = max((hi - lo) * 0.1, 1)
        pnl_axis_kwargs["range"] = [lo - pad, hi + pad]
    fig.update_yaxes(**pnl_axis_kwargs, row=2, col=1)
    fig.update_yaxes(title_text="Position", showgrid=True, gridcolor="rgba(0,0,0,0.08)", row=3, col=1)

    fig.update_layout(
        template="plotly_white",
        dragmode="pan",
        hovermode="x",
        hoverlabel=dict(bgcolor="rgba(255,255,255,0.8)",
                        bordercolor="rgba(0,0,0,0.15)",
                        font=dict(size=11, color="#222"), align="left"),
        margin=dict(l=60, r=20, t=30, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    return fig


# ---------------------------------------------------------------------------
# Log browser helpers
# ---------------------------------------------------------------------------

def scan_logs() -> list[dict]:
    """Scan backtests/ for .log files (flat), newest first."""
    if not BACKTESTS_DIR.exists():
        return []
    paths = list(BACKTESTS_DIR.glob("*.log"))
    # Also surface any legacy logs that were organized in subdirs
    paths += [p for p in BACKTESTS_DIR.rglob("*.log") if p.parent != BACKTESTS_DIR]
    logs = []
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        logs.append({"path": str(path), "name": path.name, "mtime": path.stat().st_mtime})
    return logs


def build_log_tree(logs: list[dict]) -> list:
    """Flat list of log entries, newest first."""
    if not logs:
        return [html.P("No logs found", style={"color": "#888", "padding": "10px"})]
    return [
        html.Div(
            log["name"],
            id={"type": "log-item", "path": log["path"]},
            n_clicks=0,
            style={"padding": "6px 10px", "cursor": "pointer",
                   "fontSize": "13px", "color": "#222",
                   "borderLeft": "3px solid transparent",
                   "whiteSpace": "nowrap", "overflow": "hidden",
                   "textOverflow": "ellipsis"},
        )
        for log in logs
    ]


# ---------------------------------------------------------------------------
# Available rounds (scan backtester resources)
# ---------------------------------------------------------------------------

def get_available_rounds() -> list[dict]:
    """Discover which rounds/days have data in the backtester resources."""
    resources = ROOT / "backtester" / "prosperity4bt" / "resources"
    rounds = []
    if not resources.exists():
        return rounds
    for rdir in sorted(resources.iterdir()):
        if not rdir.is_dir() or not rdir.name.startswith("round"):
            continue
        try:
            rnum = int(rdir.name.replace("round", ""))
        except ValueError:
            continue
        days = []
        for f in sorted(rdir.glob("prices_round_*_day_*.csv")):
            parts = f.stem.split("_")
            day_num = int(parts[-1])
            days.append(day_num)
        if days:
            rounds.append({"round": rnum, "days": days})
    return rounds


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------

app = Dash(__name__)

SIDEBAR_STYLE = {
    "width": "280px",
    "minWidth": "280px",
    "backgroundColor": "#f5f5f7",
    "borderRight": "1px solid #d0d0d6",
    "overflowY": "auto",
    "display": "flex",
    "flexDirection": "column",
    "height": "100vh",
}

MAIN_STYLE = {
    "flex": "1",
    "backgroundColor": "white",
    "overflowY": "auto",
    "height": "100vh",
    "padding": "10px 15px",
}

available_rounds = get_available_rounds()
round_options = [{"label": f"Round {r['round']}", "value": r["round"]} for r in available_rounds]
default_round = available_rounds[0]["round"] if available_rounds else 0
available_traders = get_available_traders()
trader_options = [{"label": t, "value": t} for t in available_traders]
default_trader = available_traders[0] if available_traders else None

app.layout = lambda: html.Div([
    # Sidebar
    html.Div([
        # Title
        html.Div("PROSPERITY 4", style={
            "padding": "15px", "fontSize": "16px", "fontWeight": "bold",
            "color": "#00a784", "letterSpacing": "2px", "textAlign": "center",
            "borderBottom": "1px solid #d0d0d6",
        }),

        # Run backtest controls
        html.Div([
            html.Div("RUN BACKTEST", style={
                "color": "#666", "fontSize": "11px", "fontWeight": "bold",
                "letterSpacing": "1px", "marginBottom": "8px",
            }),
            dcc.Dropdown(
                id="trader-select",
                options=trader_options,
                value=default_trader,
                placeholder="Pick a trader",
                style={"fontSize": "13px", "marginBottom": "6px"},
                clearable=False,
            ),
            html.Div([
                dcc.Dropdown(
                    id="round-select",
                    options=round_options,
                    value=default_round,
                    style={"width": "110px", "fontSize": "13px"},
                    clearable=False,
                ),
                dcc.Dropdown(
                    id="day-select",
                    options=[{"label": "All days", "value": "all"}],
                    value="all",
                    style={"width": "110px", "fontSize": "13px"},
                    clearable=False,
                ),
            ], style={"display": "flex", "gap": "5px", "marginBottom": "6px"}),
            dcc.Input(
                id="run-name",
                type="text",
                placeholder="Run name (optional)",
                debounce=False,
                style={"width": "100%", "fontSize": "13px", "padding": "6px",
                       "marginBottom": "8px", "border": "1px solid #d0d0d6",
                       "borderRadius": "4px", "boxSizing": "border-box"},
            ),
            html.Button("Run", id="run-btn", n_clicks=0, style={
                "width": "100%", "padding": "8px", "backgroundColor": "#00a784",
                "color": "white", "border": "none", "borderRadius": "4px",
                "fontWeight": "bold", "cursor": "pointer", "fontSize": "13px",
            }),
            html.Div(id="run-status", style={
                "color": "#666", "fontSize": "12px", "marginTop": "5px",
                "minHeight": "18px",
            }),
        ], style={"padding": "12px", "borderBottom": "1px solid #d0d0d6"}),

        # Log browser
        html.Div([
            html.Div("LOGS", style={
                "color": "#666", "fontSize": "11px", "fontWeight": "bold",
                "letterSpacing": "1px", "padding": "8px 10px 0",
            }),
            html.Div(id="log-tree", children=build_log_tree(scan_logs())),
        ], style={"flex": "1", "overflowY": "auto"}),
    ], style=SIDEBAR_STYLE),

    # Main content
    html.Div([
        # Product tabs
        dcc.Tabs(id="product-tabs", value="", children=[], style={
            "marginBottom": "5px",
        }),
        # Charts
        dcc.Graph(id="main-chart", config={"scrollZoom": True}, style={"height": "calc(100vh - 90px)"}),
        # Hidden store for current log data
        dcc.Store(id="current-log-path"),
        dcc.Store(id="parsed-products"),
        dcc.Store(id="crosshair-dummy"),
    ], style=MAIN_STYLE),
], style={"display": "flex", "fontFamily": "'Segoe UI', sans-serif", "margin": 0, "padding": 0})


# --- Callbacks ---

# Update day options when round changes
@app.callback(
    Output("day-select", "options"),
    Output("day-select", "value"),
    Input("round-select", "value"),
)
def update_day_options(round_num):
    for r in available_rounds:
        if r["round"] == round_num:
            opts = [{"label": "All days", "value": "all"}]
            opts += [{"label": f"Day {d}", "value": d} for d in r["days"]]
            return opts, "all"
    return [{"label": "All days", "value": "all"}], "all"


# Run backtest
@app.callback(
    Output("run-status", "children"),
    Output("log-tree", "children", allow_duplicate=True),
    Output("current-log-path", "data", allow_duplicate=True),
    Input("run-btn", "n_clicks"),
    State("trader-select", "value"),
    State("round-select", "value"),
    State("day-select", "value"),
    State("run-name", "value"),
    prevent_initial_call=True,
)
def run_backtest(n_clicks, trader_file, round_num, day_val, run_name):
    if not n_clicks:
        return no_update, no_update, no_update
    if not trader_file:
        return "Pick a trader first", no_update, no_update

    target = str(round_num) if day_val == "all" else f"{round_num}-{day_val}"
    timestamp = datetime.now().strftime("%m%d-%H%M%S")
    trader_stem = Path(trader_file).stem
    run_part = sanitize_run_name(run_name)
    out_file = BACKTESTS_DIR / f"{timestamp}-{run_part}-{trader_stem}.log"
    BACKTESTS_DIR.mkdir(parents=True, exist_ok=True)

    trader_path = str(TRADERS_DIR / trader_file)
    cmd = ["uv", "run", "prosperity4btest", trader_path, target, "--out", str(out_file)]
    try:
        result = subprocess.run(
            cmd, cwd=ROOT,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            err = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
            return f"Error: {err}", no_update, no_update
    except subprocess.TimeoutExpired:
        return "Timeout (>5min)", no_update, no_update

    tree = build_log_tree(scan_logs())
    return f"Done: {out_file.name}", tree, str(out_file)


# Click on log item (pattern-matching callback)
@app.callback(
    Output("current-log-path", "data"),
    Input({"type": "log-item", "path": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_log(n_clicks_list):
    if not any(n_clicks_list):
        return no_update
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    prop_id = ctx.triggered[0]["prop_id"]
    # prop_id looks like '{"path":"/some/path","type":"log-item"}.n_clicks'
    try:
        id_dict = json.loads(prop_id.rsplit(".", 1)[0])
        return id_dict["path"]
    except (json.JSONDecodeError, KeyError):
        return no_update


# Load log and update product tabs
@app.callback(
    Output("product-tabs", "children"),
    Output("product-tabs", "value"),
    Output("parsed-products", "data"),
    Input("current-log-path", "data"),
    prevent_initial_call=True,
)
def load_log_file(log_path):
    if not log_path:
        return [], "", None
    path = Path(log_path)
    if not path.exists():
        return [], "", None

    data = load_log(path)
    products = data["products"]
    if not products:
        return [], "", None

    tabs = [dcc.Tab(label=p, value=p, style={"padding": "6px 16px"},
                    selected_style={"padding": "6px 16px", "borderTop": "2px solid #00a784"})
            for p in products]
    return tabs, products[0], products


# Update chart when product tab or log changes
@app.callback(
    Output("main-chart", "figure"),
    Input("product-tabs", "value"),
    State("current-log-path", "data"),
    prevent_initial_call=True,
)
def update_charts(product, log_path):
    if not product or not log_path:
        empty = go.Figure()
        empty.update_layout(template="plotly_white", paper_bgcolor="white",
                            plot_bgcolor="white")
        return empty

    path = Path(log_path)
    if not path.exists():
        empty = go.Figure()
        empty.update_layout(template="plotly_white", paper_bgcolor="white",
                            plot_bgcolor="white")
        return empty

    return build_charts(load_log(path), product)


# Crosshair: draw a vertical line across ALL subplots at the hovered x.
# yref="paper" makes it span the full figure height; xref="x" anchors to the
# (shared) top x-axis — subplots below match via shared_xaxes so it lines up.
_CROSSHAIR_JS = """
(hoverData) => {
    const gd = document.getElementById('main-chart');
    if (!gd || !window.Plotly) return window.dash_clientside.no_update;
    if (!hoverData || !hoverData.points || !hoverData.points.length) {
        try { window.Plotly.relayout(gd, {shapes: []}); } catch (e) {}
        return window.dash_clientside.no_update;
    }
    const x = hoverData.points[0].x;
    const line = {
        type: 'line', xref: 'x', yref: 'paper',
        x0: x, x1: x, y0: 0, y1: 1,
        line: {color: 'rgba(60,60,60,0.55)', width: 1, dash: 'dot'},
        layer: 'above',
    };
    try { window.Plotly.relayout(gd, {shapes: [line]}); } catch (e) {}
    return window.dash_clientside.no_update;
}
"""

app.clientside_callback(
    _CROSSHAIR_JS,
    Output("crosshair-dummy", "data"),
    Input("main-chart", "hoverData"),
    prevent_initial_call=True,
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prosperity 4 local visualizer")
    parser.add_argument("--port", type=int, default=8050, help="Server port (default: 8050)")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    print(f"Starting visualizer at http://localhost:{args.port}")
    app.run(debug=True, port=args.port)
