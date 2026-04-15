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
export PATH := $(HOME)/.cargo/bin:$(PATH)

# Shell snippet that builds the rust backtester against a non-venv python so
# the compiled binary's libpython dependency is always on the loader path.
BUILD_CMD = \
  clean_path=$$(printf %s "$$PATH" | tr : "\n" | grep -v '/\.venv/' | paste -sd:); \
  env -u VIRTUAL_ENV PATH="$$clean_path" \
    PYO3_PYTHON="$$(PATH="$$clean_path" command -v python3)" \
    cargo build --release
DATASET_ARG = --dataset round$(R)
ifdef D
  DATASET_ARG += --day $(D)
endif
FLAGS ?=

.PHONY: install build clean-build bt quick viz-local clean-logs

install:
	./scripts/setup.sh

# Explicit clean rebuild. Use this after toolchain/env changes.
build: clean-build
	@cd backtester && $(BUILD_CMD)

clean-build:
	@rm -rf backtester/target

# Lazy build: only compiles when the binary is missing.
$(BACKTESTER):
	@cd backtester && $(BUILD_CMD)

bt: $(BACKTESTER)
	@mkdir -p backtests
	$(BACKTESTER) --trader $(ALGO) $(DATASET_ARG) \
	  --artifact-mode submission --flat \
	  --output-root backtests/_rust $(FLAGS)
	@./scripts/import_rust_run.sh

quick: $(BACKTESTER)
	$(BACKTESTER) --trader $(ALGO) $(DATASET_ARG) \
	  --artifact-mode none $(FLAGS)

viz-local:
	uv run --extra viz python viz/viz.py

clean-logs:
	rm -rf backtests/*.log backtests/_rust
