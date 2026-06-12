RUST_BACKTRACE := 1
SHELL := /bin/bash

# Use ruff from the active environment; fall back to uvx when not installed.
RUFF := $(shell command -v ruff >/dev/null 2>&1 && echo ruff || echo uvx ruff)

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show help messages for all available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## .*$$' Makefile | \
	awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: build
build: ## Build the Rust example applications
	@cargo build

.PHONY: format
format: ## Format Rust and Python sources
	@cargo fmt
	@$(RUFF) format python

.PHONY: format-check
format-check: ## Check formatting without modifying files (for CI)
	@cargo fmt --all --check
	@$(RUFF) format --check python

.PHONY: lint
lint: ## Run clippy and ruff
	@cargo clippy --workspace --all-targets -- -D warnings
	@$(RUFF) check python

.PHONY: test
test: ## Run Rust and Python tests
	@RUST_BACKTRACE=$(RUST_BACKTRACE) cargo test --workspace
	@.venv/bin/python -m pytest

.PHONY: demo-graphrag demo-grag
demo-graphrag: demo-grag
demo-grag: ## Ingest the sample corpus and run an example question (GraphRAG)
	@cd rust/graphrag-agent && \
	cargo run -q -- ingest ./sample_docs && \
	cargo run -q -- ask "Who designed the quiet power bus and where is it used?"

.PHONY: demo-code-explorer demo-code-exp
demo-code-explorer: demo-code-exp
demo-code-exp: ## Index this repository's Rust sources and rank functions (Code Explorer)
	@cd rust/code-explorer && \
	cargo run -q -- index .. && \
	cargo run -q -- rank --top 10

.PHONY: demo-fraud
demo-fraud: ## Run the Python fraud detection stream demo
	@PYTHONPATH=python/fraud/src .venv/bin/python -m fraud_detection_stream --events 2000 --batch-size 200 --seed 33

.PHONY: demo-recommend
demo-recommend: ## Run the Python social recommendations demo
	@PYTHONPATH=python/recommendation/src .venv/bin/python -m social_recommendations seed
	@PYTHONPATH=python/recommendation/src .venv/bin/python -m social_recommendations discover --user ada_lund_003 --query "borrow checker"

.PHONY: clean
clean: ## Remove build artifacts and example databases
	@cargo clean
	@rm -rf rust/graphrag-agent/rag-data rust/code-explorer/codegraph-data \
	        fraud-stream-data python/fraud/src/fraud-stream-data \
	        python/recommendation/src/social-data
	@find python -type d -name __pycache__ -prune -exec rm -rf {} +


.PHONY: setup-hooks
setup-hooks: ## Install Git hooks (pre-commit and pre-push)
	@echo "Setting up Git hooks..."
	@if ! command -v pre-commit &> /dev/null; then \
	   echo "pre-commit not found. Please install it using 'pip install pre-commit'"; \
	   exit 1; \
	fi
	@pre-commit install --hook-type pre-commit
	@pre-commit install --hook-type pre-push
	@pre-commit install-hooks

.PHONY: test-hooks
test-hooks: ## Test Git hooks on all files
	@echo "Testing Git hooks..."
	@pre-commit run --all-files
