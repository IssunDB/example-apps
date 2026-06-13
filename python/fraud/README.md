## Fraud Detection System

This example detects suspicious patterns and fraudulent behaviors in a real-time transaction stream.

### How It Works

1. Generates a deterministic, (seeded) stream of financial events (that includes account, device, and merchant registrations, transfers, payments, and
   device logins information).
2. Ingests the stream into IssunDB; maps accounts, devices, and merchants as nodes and transfers, payments, and logins as edges.
3. Runs four Cypher-based detectors after every batch insert to flag things like circular transfer rings, shared devices, money-mule fan-in, and
   velocity bursts.

More detailed workflow is shown below:

<div align="center">
  <picture>
    <img alt="Workflow" src="../../assets/diagrams/fraud.svg" height="70%" width="70%">
  </picture>
</div>
