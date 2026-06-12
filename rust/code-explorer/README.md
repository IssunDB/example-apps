## Codebase Explorer

This example indexes Rust source code, builds a syntax dependency graph, and ranks functions by structural importance.

### How It Works

1. Parses Rust source files into abstract syntax trees (using the `syn` library).
2. Stores syntax elements (like modules, functions, and structs) as nodes, and dependencies (like calls, imports, and definitions) as edges in IssunDB.
3. Computes the structural importance of functions using the PageRank algorithm on the constructed graph.

More detailed workflow is shown below:

<div align="center">
  <picture>
    <img alt="Workflow" src="../../assets/diagrams/code_explorer.svg" height="70%" width="70%">
  </picture>
</div>
