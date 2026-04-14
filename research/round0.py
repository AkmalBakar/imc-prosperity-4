"""
Quick analysis of round data.
Run: uv run python research/round0.py
"""
import csv
import matplotlib.pyplot as plt
from pathlib import Path
from collections import defaultdict

# The backtester bundles data under the prosperity4bt package
import prosperity4bt

DATA_DIR = Path(prosperity4bt.__file__).parent / "resources"


def load_prices(round_num: int, day: int) -> dict[str, list[dict]]:
    """Load price data grouped by product."""
    path = DATA_DIR / f"round{round_num}" / f"prices_round_{round_num}_day_{day}.csv"
    if not path.exists():
        print(f"No data at {path}")
        return {}

    products: dict[str, list[dict]] = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            products[row["product"]].append(row)
    return products


def plot_mid_prices(products: dict[str, list[dict]]):
    """Plot mid price for each product."""
    fig, axes = plt.subplots(len(products), 1, figsize=(14, 4 * len(products)), sharex=True)
    if len(products) == 1:
        axes = [axes]

    for ax, (product, rows) in zip(axes, products.items()):
        timestamps = []
        mids = []
        for r in rows:
            ts = int(r["timestamp"])
            # bid/ask columns vary by format — adapt as needed
            try:
                bid_str = r.get("bid_price_1") or r.get("best_bid", "")
                ask_str = r.get("ask_price_1") or r.get("best_ask", "")
                if bid_str and ask_str:
                    mid = (float(bid_str) + float(ask_str)) / 2
                    timestamps.append(ts)
                    mids.append(mid)
            except (ValueError, KeyError):
                continue

        ax.plot(timestamps, mids, linewidth=0.5)
        ax.set_ylabel(product)
        ax.set_title(f"{product} mid price")

    plt.xlabel("timestamp")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    products = load_prices(round_num=0, day=0)
    if products:
        print(f"Products found: {list(products.keys())}")
        print(f"Sample row: {list(products.values())[0][0]}")
        plot_mid_prices(products)
    else:
        print("No data found. Check DATA_DIR path.")
        print(f"DATA_DIR = {DATA_DIR}")
        # List what's available
        if DATA_DIR.exists():
            for p in sorted(DATA_DIR.rglob("*.csv")):
                print(f"  {p.relative_to(DATA_DIR)}")
