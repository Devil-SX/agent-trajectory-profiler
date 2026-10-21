---
name: trajectory-client
description: Use when operating Trajectory sessions, task analysis, research statistics or sampling schedules through its authenticated HTTP API.
---

# Trajectory HTTP client

Use the installed `batcave` HTTP client and the provisioned private connection.
Resolve the connection through [local installation](references/local-installation.md).
Never print credentials or use server files, SSH or a browser cookie as a business API fallback.

1. Run `batcave --config "$BATCAVE_TRAJECTORY_CONFIG" help trajectory`.
   Verify the actual account UUID, native machine client, Key ID and credential profile.
   Discover current operations, schemas, scopes and side effects from this authenticated Help.
2. Use each advertised API path relative to the configured service URL. Supply JSON using
   `--body-file`; save sensitive or large responses using `--output` in a private directory.
3. Machine identity and resource ownership are distinct. Use only the explicitly delegated
   resource owner recorded in the private connection. A resource-owner parameter does not
   replace the caller's native account, Key or client binding.
4. Keep a mutation ID and exact request payload stable. After a timeout, query the existing
   receipt before retrying. A queued analysis or enabled schedule is not a completed analysis.
   Inspect the persisted selected sources, revisions, batch progress and cost coverage.
5. Paid automation uses the service's authenticated Jindu route. Preserve stable upstream call
   IDs and reconcile uncertain receipts; do not switch provider or issue a new paid request
   merely because the response was lost. Never install upstream provider secrets in clients.

Analysis-profile credentials intentionally exclude unrelated service administration. If Help
or a request denies an operation, use the separately authorized Ops control-plane workflow
for the existing native machine identity; do not borrow an operator key for automation.
Credential revocation and disabled clients must take effect on the next request.

For development or deployment, first use Ops Help to discover the current maintenance
publication and verify its revision and hashes. A connection skill does not authorize a
second writer, production database access, service restart or provider bypass.
