## Contribution Guidelines

Thank you for considering contributing to the project.
Contributions are always welcome!

### How to Contribute

Please check the [issue tracker](https://github.com/IssunDB/example-apps/issues) to see whether there is an issue you would like to work on or whether
it has already been resolved.

#### Reporting Bugs

1. Open an issue on the [issue tracker](https://github.com/IssunDB/example-apps/issues).
2. Include steps to reproduce, expected behavior, actual behavior, environment details, and relevant logs or screenshots.

#### Suggesting Features

1. Open an issue on the [issue tracker](https://github.com/IssunDB/example-apps/issues).
2. Provide the feature goal, expected output, and why it benefits the showcase applications.

### Submitting Pull Requests

- Make sure relevant tests and format checks pass before submitting a pull request.
- Write a clear description of the behavior change and the reason for it.

> [!IMPORTANT]
> If you use an AI-assisted coding tool like Claude Code or Codex, make sure it follows the instructions in the root [AGENTS.md](AGENTS.md) file.

### Development Workflow

#### Architecture Considerations

The repository is organized around four showcase applications:

1. `rust/graphrag-agent`: Graph RAG application showcasing vector search, full-text search, and hybrid graph expansion.
2. `rust/code-explorer`: Rust source code navigator illustrating structural graph analysis (PageRank, components, shortest path) on code syntax trees.
3. `python/fraud`: Cypher-based fraud pattern detection over a simulated transaction stream.
4. `python/recommendation`: Hybrid friend-of-friend and content recommendation system.

Keep application-specific logic inside the respective subdirectories. Use the top-level `Makefile` to orchestrate builds, tests, linting, and runs.

#### Code Style

- Use standard formatting for both Rust (`cargo fmt`) and Python (`ruff format`).
- Keep changes small and focused.
- Ensure all tests pass.

#### Running Tests

```bash
make test
```

#### Running Demos

```bash
# GraphRAG
make demo-grag

# Code Explorer
make demo-code-exp

# Fraud Detection Stream
make demo-fraud

# Social Recommendations
make demo-recommend
```

#### See Available Commands

```bash
make help
```
