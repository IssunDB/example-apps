## IssunDB Example Applications

[![Tests](https://img.shields.io/github/actions/workflow/status/IssunDB/example-apps/tests.yml?label=tests&style=flat&labelColor=282c34&logo=github)](https://github.com/IssunDB/example-apps/actions/workflows/tests.yml)
[![Code Coverage](https://img.shields.io/codecov/c/github/IssunDB/example-apps?label=coverage&style=flat&labelColor=282c34&logo=codecov)](https://codecov.io/gh/IssunDB/example-apps)
[![Python version](https://img.shields.io/badge/python-%3E=3.10-3776ab?style=flat&labelColor=282c34&logo=python)](https://github.com/IssunDB/example-apps)
[![License: MIT](https://img.shields.io/badge/license-MIT-ffd343?style=flat&labelColor=282c34&logo=open-source-initiative)](LICENSE)

This repository includes a collection of example applications that use the [IssunDB](https://github.com/IssunDB/issun-db) graph database.

---

### Examples

Currently, the following table lists the included examples:

| # | Example                                               | Language | Description                                                                              |
|---|-------------------------------------------------------|----------|------------------------------------------------------------------------------------------|
| 1 | [GraphRAG Pipeline](rust/graphrag-agent)              | Rust     | Knowledge graph extraction and retrieval-augmented generation using an LLM.              |
| 2 | [Codebase Explorer](rust/code-explorer)               | Rust     | Syntax dependency graph constructor and function ranking using PageRank.                 |
| 3 | [Fraud Detection System](python/fraud)                | Python   | Real-time financial transaction stream analyzer using Cypher queries.                    |
| 4 | [Social Recommendation System](python/recommendation) | Python   | Hybrid friend and content recommender using collaborative filtering and semantic search. |

---

### Quickstart

#### Prerequisites

To build and run the example applications, you need:

- Rust (version 1.85 or newer) toolchain: [Install Rust](https://www.rust-lang.org/tools/install)
- Python (version 3.10 or newer) with `uv` package manager: [Install uv](https://github.com/astral-sh/uv)

#### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/IssunDB/example-apps.git
   cd example-apps
   ```

2. Set up the Python virtual environment and install dependencies:
   ```bash
   uv sync --all-extras
   ```

3. Build the Rust applications:
   ```bash
   make build
   ```

#### Running the Demos

You can run any of the demos using the provided `Makefile` targets:

- Run the GraphRAG pipeline:
  ```bash
  make demo-grag
  ```
- Run the Codebase Explorer:
  ```bash
  make demo-code-exp
  ```
- Run the Fraud Detection stream:
  ```bash
  make demo-fraud
  ```
- Run the Social Recommendation system:
  ```bash
  make demo-recommend
  ```

---

### Reporting Bugs

Please report bugs and issues you encounter via the [issue page](https://github.com/IssunDB/example-apps/issues).

### License

This project is licensed under the MIT License (see [LICENSE](LICENSE)).
