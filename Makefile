# Usage:
#   make bt         # backtest round 1 (all days) with persisted artifacts
#   make bt R=1     # same, explicit
#   make bt R=1 D=0 # backtest round 1 day 0
#   make quick      # backtest without saving to backtests/ (faster)
#   make viz-local  # start the Dash visualizer

R ?= 1
D ?=
ALGO ?= traders/trader.py
BACKTESTER ?= backtester/target/release/rust_backtester
# Prefer rustup's toolchain (~/.cargo/bin) over any system cargo that may be too old.
export PATH := $(HOME)/.cargo/bin:$(PATH)
DATASET_ARG = --dataset round$(R)
ifdef D
  DATASET_ARG += --day $(D)
endif
FLAGS ?=

.PHONY: install build bt quick viz-local clean-logs

install:
	./scripts/setup.sh

build:
	cd backtester && cargo build --release

bt: build
	@mkdir -p backtests
	$(BACKTESTER) --trader $(ALGO) $(DATASET_ARG) \
	  --artifact-mode submission --flat \
	  --output-root backtests/_rust $(FLAGS)
	@./scripts/import_rust_run.sh

quick: build
	$(BACKTESTER) --trader $(ALGO) $(DATASET_ARG) \
	  --artifact-mode none $(FLAGS)

viz-local:
	uv run --extra viz python viz/viz.py

clean-logs:
	rm -rf backtests/*.log backtests/_rust
