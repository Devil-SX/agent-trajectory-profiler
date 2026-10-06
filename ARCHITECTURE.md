# BatCave Trajectory architecture

## Product boundaries

Sparkstead is a protocol producer. Its worker reads bounded log slices, extracts source fields and explicit target identifiers, and transactionally saves checkpoints with an outbox. A durable server receipt acknowledges a batch. No analysis dashboard, price calculation or SQL query IPC exists in Sparkstead.

BatCave Trajectory is the analysis authority. `trajectory/product/contracts.py` defines the wire schema. `server.py` contains one operation registry from which authenticated routes and live Help are generated. `domain.py` owns the SQLite database and all writes, idempotent receipts, owner bindings, corrections, prices and analytical semantics. `projects.py` interprets the uploaded identifiers conservatively. The browser renders metrics returned by the domain without computing an independent cost model.

## Authentication and isolation

Native Identity determines whether accounts and service clients remain eligible on each request. Shared `batcave_http` validates the registered API Key and its scope. Uploads require a native machine client. An authenticated operator binds a collector to its owner. Owners read and correct only their own data; platform observers require read-all scope. Browser requests use the authenticated ingress and an origin check for writes.

Each record has a physical source ID and event ID. Mutation IDs deduplicate delivery, while consumption IDs deduplicate replayed consumption. Those identities serve different roles and must never be conflated. Missing counters, timestamps, models and prices remain explicit gaps. Tool duration requires matching start/end evidence; an unfinished tool is a symptom, not proof of a particular failure cause.

## Durability and deployment

The domain commits events, revision progress, audit metadata and receipts atomically with SQLite synchronous FULL. The producer does not advance a checkpoint independently of its outbox. Upload retries preserve the same mutation ID and body. A changed body under that ID is rejected. Online database backup uses the domain's SQLite Backup API.

Release candidates are built and tested on batcave-wsl in isolated databases and ports. Existing production services remain online. Installation and native-account changes use the remote deployment lock and recheck active releases and maintenance barriers. Public routing uses authenticated BatCave ingress; current maintenance instructions are published independently of repository worktrees.

## Legacy retirement

The 2.0 wheel includes only the `trajectory` package marker and `trajectory.product`. Legacy local CLI, database query API, frontend and native parser are excluded from installation. Their old namespace and repository history remain available until replacement verification permits cleanup. User databases are migrated through SQLite Backup API, never by copying an active DB/WAL pair.
