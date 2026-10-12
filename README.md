# BatCave Trajectory

Trajectory analyzes Agent usage by project: daily tokens, estimated activity time, API-equivalent cost and evidence of slow or failed tools. Human users and Agents use the same authenticated HTTP service.

Open `/trajectory/` on your BatCave host. The dashboard shows collection coverage, daily token and activity charts, project comparisons, partial API cost estimates, exact detail tables and anomalies. Date filters use Shanghai time. Project filtering applies to project summaries and evidence; daily charts require all projects because the HTTP overview does not publish per-project daily aggregates. Names come from the live Ops service catalogue and icons reuse the shared Ops assets. Unknown values remain unknown. Activity estimates do not represent human working hours; API-equivalent estimates do not represent a subscription bill.

Sparkstead uploads supported log metadata through the open `trajectory-batch/1` protocol. In Sparkstead Settings > Trajectory, enable background collection and configure the batch HTTP URL, origin-bound credential file and remote sync toggle. Collection runs in a worker and persists checkpoints with pending batches. Raw prompts, tool arguments, code and credentials stay local. Sparkstead has no local analysis interface.

Any conforming collector may upload. Discover current endpoints, scopes and input schemas through `/trajectory/help`; obtain the protocol JSON Schema at `/trajectory/protocol`. Each collector requires an enabled native machine account and an API Key with the upload scope, bound to its authenticated owner. Revoked keys or disabled clients are rejected on subsequent requests.

Requests receive a request ID. Bounded request traces distinguish verified accounts and machines, scope denials, unrecognized credentials, and public discovery or health access. Administrators discover the trace reader through authenticated Help. Trace metadata excludes query values, bodies and credentials.

The service provides account-scoped project corrections and dated prices through the same HTTP API. Operators may read platform summaries with a separate read-all grant. Prices are not invented when source metadata is missing.

Developer architecture and protocol details are in [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md). Current production maintenance instructions are independently published and discovered through BatCave Ops Help. Installation, release and runtime credentials are administered by BatCave; they are not user-facing CLI business interfaces.

Status: version 2.0.1 is deployed on BatCave. Windows desktop installation and project attribution improvements remain in progress. Historical profiler source remains in Git history; historical user databases and source logs are preserved during migration.
