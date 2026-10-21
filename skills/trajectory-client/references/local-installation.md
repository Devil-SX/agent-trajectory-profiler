# Provisioned connection

The installation may set `BATCAVE_TRAJECTORY_CONFIG` to its private JSON connection file.
On this workstation, the canonical provisioned analysis connection is
`$HOME/.config/batcave-trajectory/analysis-http.json`. Set the variable to that path when it
is not already provided. The directory must be mode 0700 and the file mode 0600.

The file uses the installed BatCave HTTP client's standard `services.trajectory` connection
schema. Local provisioning metadata records native account, machine client, Key identifier
and explicitly delegated resource owner. Read only that metadata when checking identity;
never echo the file or its credential field. The live authenticated Help remains authoritative
for the effective caller and allowed operations.

If the connection is absent, use Ops Help and the existing native machine client's formal
profile grant and one-time Key delivery workflow. The interactive administrator performs
setup only. Save a newly delivered machine credential directly to private storage; query
metadata after uncertain issuance, revoke an undelivered Key explicitly and then request a
new issuance. Never create a duplicate account merely to obtain another connection.
