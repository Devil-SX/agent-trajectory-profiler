# BatCave Trajectory

Trajectory analyzes Agent usage by project: daily tokens, estimated activity time, API-equivalent cost and evidence of slow or failed tools. Human users and Agents use the same authenticated HTTP service.

Open `/trajectory/` on your BatCave host. Use the persistent “Only analyzed” status filter to find stored results, or filter by source directory and sort by original session activity. Select a session in Task Analysis to inspect an expandable task tree, non-contiguous execution segments, a cost flamegraph and original evidence. Task names and groupings can be revised without changing original records. The dashboard also shows collection coverage, daily token and activity charts, project comparisons, partial API cost estimates, exact detail tables and anomalies. Human investment cards and daily charts count only proven human inputs. Input characters mean non-whitespace Unicode characters in submitted text, including pasted or reused text, not tokens or actual typed keystrokes. Missing text and unknown origins remain explicit gaps; these counts do not estimate actual human working time. Date filters use Shanghai time. Project filtering applies to project summaries and evidence; daily charts require all projects because the HTTP overview does not publish per-project daily aggregates. Names come from the live Ops service catalogue and icons reuse the shared Ops assets. Unknown values remain unknown. Activity estimates do not represent human working hours; API-equivalent estimates do not represent a subscription bill.

Sparkstead uploads supported log metadata through the open collector protocol. In Sparkstead Settings > Trajectory, enable background collection and configure the batch HTTP URL, origin-bound credential file and remote sync toggle. Collection runs in a worker and persists checkpoints with pending batches. The historical metadata-only stream does not contain enough content for semantic segmentation. A separately authorized source synchronizer can supply execution records for remote analysis while preserving the original collector progress. Historical content gaps remain visible. Sparkstead has no local analysis interface.

Any conforming collector may upload. Discover current endpoints, scopes and input schemas through `/trajectory/help`; obtain the protocol JSON Schema at `/trajectory/protocol`. Each collector requires an enabled native machine account and an API Key with the upload scope, bound to its authenticated owner. Revoked keys or disabled clients are rejected on subsequent requests.

Requests receive a request ID. Bounded request traces distinguish verified accounts and machines, scope denials, unrecognized credentials, and public discovery or health access. Administrators discover the trace reader through authenticated Help. Trace metadata excludes query values, bodies and credentials.

The service provides account-scoped project corrections and dated prices through the same HTTP API. Operators may read platform summaries with a separate read-all grant. Prices are not invented when source metadata is missing.

Developer architecture and protocol details are in [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md). Current production maintenance instructions are independently published and discovered through BatCave Ops Help. Installation, release and runtime credentials are administered by BatCave; they are not user-facing CLI business interfaces.

The former local profiler, its database-query CLI and its React dashboard are retired from the current source. Their history remains in Git; historical user databases and source logs are preserved. Current release status is reported by authenticated service discovery rather than this document.

Developer validation and remote-runner prerequisites are described in [ARCHITECTURE.md](ARCHITECTURE.md#development-validation).

Model-based task analysis uses the BatCave Jindu gateway. Administrators configure an independent native machine account with the selected route and `jindu.invoke`/`jindu.read`; the service holds no upstream supplier credential. Discover allowed routes through authenticated Jindu Help. Analysis provenance records Jindu call/receipt IDs, per-request duration and provider-reported usage.

Batch analysis is available in the workbench and through the same authenticated
HTTP interface discovered in Help. Select sessions and a bounded concurrency;
progress, errors, model usage and elapsed time remain available after reload.
The server configuration selects the Jindu model and reasoning effort. Recorded
provenance identifies the configuration actually used by each analysis.
