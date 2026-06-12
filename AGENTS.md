# AGENTS.md

This file provides guidance to coding agents collaborating on this repository.

## Mission

Project contains demo applications in Rust and Python to show how to build applications using IssunDB (an embedded graph database written in Rust).
Priorities, in order:

1. Correctness of application logic, schema definitions, and query patterns.
2. Simplicity and clarity of the showcase implementations.
3. Ease of running and demonstrating each application.

## Core Rules

- Use English for code, comments, docs, and tests.
- Prefer small, focused changes over broad refactoring.
- Add comments only when they clarify non-obvious behavior.
- Do not add features, error handling, or abstractions beyond what is needed for the current task.
- Keep dependencies small. Do not add new libraries or frameworks without prior discussion.

## Writing Style

- Use Oxford commas in inline lists: "a, b, and c" not "a, b, c".
- Do not use em dashes. Restructure the sentence, or use a colon or semicolon instead.
- Avoid colorful adjectives and adverbs. Write "instruction decoder" not "elegant instruction decoder".
- Use noun phrases for checklist items, not imperative verbs. Write "opcode timing table" not "build the opcode timing table".
- Headings in Markdown files must be in title case: "Build from Source" not "Build from source". Minor words (a, an, the, and, but, or, for, in, on,
  at, to, by, of) stay lowercase unless they are the first word.

## Repository Layout

- `rust/graphrag-agent/`: GraphRAG application in Rust.
- `rust/code-explorer/`: Rust source code navigator and structural analyzer using PageRank.
- `python/fraud/`: Cypher-based fraud pattern detection over transaction stream.
- `python/recommendation/`: Hybrid user friend and content recommendation system.
- `Makefile`: Chore orchestration (build, format, lint, test, demos).
- `pyproject.toml`: Workspace Python environment configuration.
- `Cargo.toml`: Rust workspace configuration.

## Required Validation

Run the relevant targets for any change:

| Target                     | Command               | What It Runs                                       |
|----------------------------|-----------------------|----------------------------------------------------|
| Build                      | `make build`          | Cargo build for all Rust applications              |
| Format check               | `make format-check`   | Checks cargo format and python ruff formatting     |
| Lint                       | `make lint`           | Runs clippy and python ruff linter                 |
| Unit tests                 | `make test`           | Runs both Rust cargo tests and Python pytest tests |
| GraphRAG demo              | `make demo-grag`      | Ingests sample docs and runs ask query             |
| Codebase explorer demo     | `make demo-code-exp`  | Indexes Rust sources and ranks functions           |
| Fraud detection demo       | `make demo-fraud`     | Runs Python fraud detection stream simulation      |
| Recommendation system demo | `make demo-recommend` | Seeds social recommendations db and runs discovery |
| Clean                      | `make clean`          | Cleans up build artifacts and generated databases  |

## Testing Expectations

- Rust application changes need to compile and pass the cargo test suite.
- Python application changes must pass the pytest suite (needs a Python (virtual) environment with `issundb` bindings package).
- Formatting and linting checks must pass before pull requests are submitted.
