# Usage:
#   make bt         # backtest tutorial round, open visualizer
#   make bt R=1     # backtest round 1
#   make bt R=1 D=0 # backtest round 1 day 0
#   make quick      # backtest without visualizer (faster)
#   make merge      # backtest with merged PnL across days

R ?= 0
D ?=
ALGO ?= traders/trader.py
FLAGS ?=

ifdef D
TARGET = $(R)-$(D)
else
TARGET = $(R)
endif

.PHONY: install bt quick merge viz-local viz-run clean-logs

install:
	./scripts/setup.sh

bt:
	prosperity4btest $(ALGO) $(TARGET) --vis $(FLAGS)

quick:
	prosperity4btest $(ALGO) $(TARGET) $(FLAGS)

merge:
	prosperity4btest $(ALGO) $(TARGET) --merge-pnl --vis $(FLAGS)

viz-local:
	uv run --extra viz python viz/viz.py

viz-run:
	uv run --extra viz python viz/viz.py --run $(TARGET)

clean-logs:
	rm -rf backtests/*.log
