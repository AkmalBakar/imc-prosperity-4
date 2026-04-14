from datamodel import Listing, Observation, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState, Order
from typing import Any, List
import json
import numpy as np


LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        # Only truncate free-form `logs`. Leave state.traderData and trader_data
        # untouched so downstream consumers (viz) can reparse them as JSON.
        base_length = len(
            self.to_json([self.compress_state(state, state.traderData), self.compress_orders(orders), conversions, trader_data, ""])
        )
        max_logs_length = max(0, self.max_log_length - base_length)

        print(
            self.to_json(
                [
                    self.compress_state(state, state.traderData),
                    self.compress_orders(orders),
                    conversions,
                    trader_data,
                    self.truncate(self.logs, max_logs_length),
                ]
            )
        )
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        out = []
        for arr in trades.values():
            for t in arr:
                out.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return out

    def compress_observations(self, observations: Observation) -> list[Any]:
        conv = {}
        for product, o in observations.conversionObservations.items():
            conv[product] = [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [observations.plainValueObservations, conv]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        out = []
        for arr in orders.values():
            for o in arr:
                out.append([o.symbol, o.price, o.quantity])
        return out

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


def linear_forecast(y: List[float], horizon: int = 1) -> float:
    """OLS fit on (i, y[i]) for i in [0, n); return prediction at i = n - 1 + horizon."""
    n = len(y)
    if n == 0:
        return 0.0
    if n == 1:
        return float(y[0])
    x = np.arange(n)
    slope, intercept = np.polyfit(x, np.asarray(y, dtype=float), 1)
    return float(intercept + slope * (n - 1 + horizon))


class ProductTrader:
    def __init__(self, name: str, state: TradingState, new_trader_data: dict) -> None:
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data
        self.orders: List[Order] = []

        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            self.last_traderData = {}

        depth = state.order_depths.get(name)
        buy = depth.buy_orders if depth is not None else {}
        sell = depth.sell_orders if depth is not None else {}
        self.mkt_buy_orders = {p: abs(v) for p, v in sorted(buy.items(), key=lambda x: x[0], reverse=True)}
        self.mkt_sell_orders = {p: abs(v) for p, v in sorted(sell.items(), key=lambda x: x[0])}

        self.best_bid = max(self.mkt_buy_orders) if self.mkt_buy_orders else None
        self.best_ask = min(self.mkt_sell_orders) if self.mkt_sell_orders else None
        self.bid_wall, self.ask_wall, self.wall_mid = self.compute_walls()

        self.position_limit = LIMITS.get(name, 50)
        self.initial_position = state.position.get(name, 0)
        self.max_allowed_buy_volume = self.position_limit - self.initial_position
        self.max_allowed_sell_volume = self.position_limit + self.initial_position

    @staticmethod
    def _vwap(levels: dict[int, int]) -> float | None:
        tot = sum(levels.values())
        if tot <= 0:
            return None
        return sum(p * v for p, v in levels.items()) / tot

    def compute_walls(self) -> tuple[float | None, float | None, float | None]:
        """Volume-weighted bid/ask walls across all displayed levels, and their mid.

        Weighted reduces the noise of min/max-level snapshotting when a single
        tiny level flickers in/out of the book.
        """
        bid_wall = self._vwap(self.mkt_buy_orders)
        ask_wall = self._vwap(self.mkt_sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2 if bid_wall is not None and ask_wall is not None else None
        return bid_wall, ask_wall, wall_mid

    def bid(self, price: float, volume: int) -> None:
        qty = min(abs(int(volume)), self.max_allowed_buy_volume)
        if qty <= 0:
            return
        self.orders.append(Order(self.name, int(price), qty))
        self.max_allowed_buy_volume -= qty

    def ask(self, price: float, volume: int) -> None:
        qty = min(abs(int(volume)), self.max_allowed_sell_volume)
        if qty <= 0:
            return
        self.orders.append(Order(self.name, int(price), -qty))
        self.max_allowed_sell_volume -= qty

    def get_orders(self) -> dict[str, List[Order]]:
        return {self.name: self.orders}


class OsmiumTrader(ProductTrader):
    """ASH_COATED_OSMIUM: bounded mean-reversion around ~10000.

    Research (research/osmium.ipynb): stationary channel, mean ~10000,
    sigma ~4.7, 1/99 percentile at ~10000 +/- 11, AR(1) half-life ~30 ticks,
    ADF p-value ~1e-6.

    Strategy: linear-inventory around a z-score signal.
      - fair = rolling mean of wall_mid (falls back to hardcoded 10000).
      - z = (wall_mid - fair) / sigma_bound, clipped to [-1, 1].
      - target_pos = -limit * z -- lean fully against the deviation at the
        bounds, neutral at fair (Ornstein-Uhlenbeck optimal policy shape).

    Execution each tick:
      1. Take: buy any ask <= fair (walking up the book) until pos >= target,
         symmetric for sells.
      2. Make: quote the leftover capacity at fair +/- spread with an
         inventory-skew bias so quotes pull us toward target.
    """

    KEY = "osm"
    HISTORY = 500          # rolling-mean window
    FALLBACK_FAIR = 10000  # hardcoded until history fills
    SIGMA_BOUND = 11.0     # ~99th pct deviation; z=1 means fully extended
    SPREAD = 2             # base half-spread for passive quotes
    SKEW = 0.03            # ticks-of-bias per unit of position

    def get_orders(self) -> dict[str, List[Order]]:
        prev = self.last_traderData.get(self.KEY, {"wm": []})

        if self.wall_mid is None:
            self.new_trader_data[self.KEY] = prev
            return {self.name: self.orders}

        wm_hist = (prev["wm"] + [self.wall_mid])[-self.HISTORY:]

        fair = float(np.mean(wm_hist)) if len(wm_hist) >= 50 else float(self.FALLBACK_FAIR)
        z = max(-1.0, min(1.0, (self.wall_mid - fair) / self.SIGMA_BOUND))
        target = int(round(-self.position_limit * z))

        self.new_trader_data[self.KEY] = {
            "wm": wm_hist,
            "viz": {"fair": fair, "wall_mid": float(self.wall_mid), "target": target, "z": z},
        }

        # --- 1. TAKE toward target ---
        pos = self.initial_position
        if target > pos:
            need = target - pos
            for sp, sv in self.mkt_sell_orders.items():
                if need <= 0 or sp > fair:
                    break
                take = min(sv, need, self.max_allowed_buy_volume)
                if take > 0:
                    self.bid(sp, take)
                    need -= take
                    pos += take
        elif target < pos:
            need = pos - target
            for bp, bv in self.mkt_buy_orders.items():
                if need <= 0 or bp < fair:
                    break
                take = min(bv, need, self.max_allowed_sell_volume)
                if take > 0:
                    self.ask(bp, take)
                    need -= take
                    pos -= take

        # --- 2. MAKE around fair with inventory skew ---
        # Skew shifts both quotes by -SKEW * pos ticks so long inventory
        # makes us sell cheaper / buy harder (pulls us toward neutral).
        skew = self.SKEW * pos
        bid_px = int(round(fair - self.SPREAD - skew))
        ask_px = int(round(fair + self.SPREAD - skew))
        self.bid(bid_px, self.max_allowed_buy_volume)
        self.ask(ask_px, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class PepperRootTrader(ProductTrader):
    """INTARIAN_PEPPER_ROOT: OLS-forecast walls; take across predicted mid, make one tick inside."""

    HISTORY = 200
    KEY = "ppr"

    def get_orders(self) -> dict[str, List[Order]]:
        prev = self.last_traderData.get(self.KEY, {"bids": [], "asks": []})

        if self.bid_wall is None or self.ask_wall is None:
            self.new_trader_data[self.KEY] = prev
            return {self.name: self.orders}

        bids = (prev["bids"] + [self.bid_wall])[-self.HISTORY:]
        asks = (prev["asks"] + [self.ask_wall])[-self.HISTORY:]

        if len(bids) < self.HISTORY:
            self.new_trader_data[self.KEY] = {
                "bids": bids, "asks": asks,
                "viz": {"wall_mid": float(self.wall_mid) if self.wall_mid is not None else None},
            }
            return {self.name: self.orders}

        bid_pred = linear_forecast(bids)
        ask_pred = linear_forecast(asks)
        mid_pred = (bid_pred + ask_pred) / 2

        self.new_trader_data[self.KEY] = {
            "bids": bids, "asks": asks,
            "viz": {
                "fair": float(mid_pred),
                "wall_mid": float(self.wall_mid),
                "bid_pred": float(bid_pred),
                "ask_pred": float(ask_pred),
            },
        }

        # TAKE: asks strictly below predicted mid -> buy
        for sp, sv in self.mkt_sell_orders.items():
            if sp < mid_pred:
                self.bid(sp, sv)

        # TAKE: bids strictly above predicted mid -> sell
        for bp, bv in self.mkt_buy_orders.items():
            if bp > mid_pred:
                self.ask(bp, bv)

        # TAKE-AT-MID (inventory unwind)
        for sp, sv in self.mkt_sell_orders.items():
            if sp == int(round(mid_pred)) and self.initial_position < 0:
                self.bid(sp, min(sv, abs(self.initial_position)))
        for bp, bv in self.mkt_buy_orders.items():
            if bp == int(round(mid_pred)) and self.initial_position > 0:
                self.ask(bp, min(bv, self.initial_position))

        bid_price = int(round(bid_pred)) + 1
        ask_price = int(round(ask_pred)) - 1

        # # OVERBID / UNDERBID inside predicted wall (Frankfurt StaticTrader:306-324) — disabled
        # for bp, bv in self.mkt_buy_orders.items():
        #     overbid = bp + 1
        #     if bv > 1 and overbid < mid_pred:
        #         bid_price = max(bid_price, overbid); break
        #     elif bp < mid_pred:
        #         bid_price = max(bid_price, bp); break
        # for sp, sv in self.mkt_sell_orders.items():
        #     underbid = sp - 1
        #     if sv > 1 and underbid > mid_pred:
        #         ask_price = min(ask_price, underbid); break
        #     elif sp > mid_pred:
        #         ask_price = min(ask_price, sp); break

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


TRADERS: dict[str, type[ProductTrader]] = {
    "ASH_COATED_OSMIUM": OsmiumTrader,
    "INTARIAN_PEPPER_ROOT": PepperRootTrader,
}


class Trader:
    def run(self, state: TradingState) -> tuple[dict[str, List[Order]], int, str]:
        new_trader_data: dict = {}
        result: dict[str, List[Order]] = {}

        for symbol in state.order_depths:
            cls = TRADERS.get(symbol)
            if cls is None:
                continue
            trader = cls(symbol, state, new_trader_data)
            result.update(trader.get_orders())

        conversions = 0
        trader_data = json.dumps(new_trader_data, separators=(",", ":"))
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
