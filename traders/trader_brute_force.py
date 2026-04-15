from datamodel import Listing, Observation, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState, Order
from typing import Any, List
import json


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
            state.timestamp, trader_data,
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


# ---------------------------------------------------------------------------
# Base class: parses order book, enforces position limits on order helpers
# ---------------------------------------------------------------------------

class ProductTrader:
    def __init__(self, name: str, state: TradingState, new_trader_data: dict) -> None:
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data
        self.orders: List[Order] = []

        depth = state.order_depths.get(name)
        buy = depth.buy_orders if depth is not None else {}
        sell = depth.sell_orders if depth is not None else {}
        # Sorted: bids high→low, asks low→high; volumes always positive
        self.mkt_buy_orders = {p: abs(v) for p, v in sorted(buy.items(), key=lambda x: x[0], reverse=True)}
        self.mkt_sell_orders = {p: abs(v) for p, v in sorted(sell.items(), key=lambda x: x[0])}

        self.best_bid = max(self.mkt_buy_orders) if self.mkt_buy_orders else None
        self.best_ask = min(self.mkt_sell_orders) if self.mkt_sell_orders else None

        self.position_limit = LIMITS.get(name, 50)
        self.initial_position = state.position.get(name, 0)
        self.max_buy = self.position_limit - self.initial_position
        self.max_sell = self.position_limit + self.initial_position

    def bid(self, price: float, volume: int) -> None:
        qty = min(abs(int(volume)), self.max_buy)
        if qty <= 0:
            return
        self.orders.append(Order(self.name, int(price), qty))
        self.max_buy -= qty

    def ask(self, price: float, volume: int) -> None:
        qty = min(abs(int(volume)), self.max_sell)
        if qty <= 0:
            return
        self.orders.append(Order(self.name, int(price), -qty))
        self.max_sell -= qty

    def get_orders(self) -> dict[str, List[Order]]:
        return {self.name: self.orders}


# ---------------------------------------------------------------------------
# Osmium: stationary around ~10 000, wide spread (~16 ticks).
# Strategy: join best bid/ask with full capacity. No history, no skew.
# The wide spread provides enough edge per fill and the stationary process
# means inventory self-corrects without active management.
# ---------------------------------------------------------------------------

class OsmiumTrader(ProductTrader):
    KEY = "osm"

    def get_orders(self) -> dict[str, List[Order]]:
        if self.best_bid is None or self.best_ask is None:
            self.new_trader_data[self.KEY] = {}
            return {self.name: self.orders}

        self.new_trader_data[self.KEY] = {
            "viz": {"best_bid": self.best_bid, "best_ask": self.best_ask},
        }

        self.bid(self.best_bid, self.max_buy)
        self.ask(self.best_ask, self.max_sell)
        return {self.name: self.orders}


# ---------------------------------------------------------------------------
# Pepper Root: drifts upward ~+0.1 / tick (~+1 000 / day).
# Strategy: long-biased market making.
#   - TAKE: buy every ask up to mid + 7 (cross the spread to accumulate).
#   - MAKE: bid aggressively (best_bid + 5), ask reluctantly (best_ask + 1).
# No sell takes — stay long and let the drift work.
# ---------------------------------------------------------------------------

class PepperRootTrader(ProductTrader):
    KEY = "ppr"
    BID_OFFSET = 5  # ticks inside best bid — aggressive accumulation
    ASK_OFFSET = 1  # ticks outside best ask — reluctant selling
    TAKE_EDGE = 7   # buy asks up to mid + TAKE_EDGE

    def get_orders(self) -> dict[str, List[Order]]:
        if self.best_bid is None or self.best_ask is None:
            self.new_trader_data[self.KEY] = {}
            return {self.name: self.orders}

        mid = (self.best_bid + self.best_ask) / 2.0

        self.new_trader_data[self.KEY] = {
            "viz": {"mid": mid, "pos": self.initial_position},
        }

        # TAKE: buy aggressively
        for price, vol in self.mkt_sell_orders.items():
            if price <= mid + self.TAKE_EDGE:
                self.bid(price, vol)

        # MAKE: long-biased quotes
        self.bid(self.best_bid + self.BID_OFFSET, self.max_buy)
        self.ask(self.best_ask + self.ASK_OFFSET, self.max_sell)
        return {self.name: self.orders}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

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
