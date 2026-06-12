"""Real-time fraud and identity link analysis on an IssunDB graph.

This showcase application streams simulated financial transaction events into
an embedded IssunDB graph database and runs Cypher-based fraud detection rules
(transfer rings, shared devices, money-mule fan-in, velocity bursts) after
every batch.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
