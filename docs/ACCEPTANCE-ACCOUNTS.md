# Deployment acceptance accounts

Release verification needs authenticated reads against real data. This document
records the accounts that exist for that purpose, their exact permissions and how
to rotate or revoke them. It contains no credentials: only key IDs and hashes
live in the service key registry, and secrets stay in root-only files.

## Accounts

| Purpose | Native identity | Account ID | Key ID | Scopes | Notes |
|---|---|---|---|---|---|
| Upload from the production collector | machine client `sparkstead-trajectory-collector` | `20e104b1-330c-40a3-bc6f-160ed9d24a3f` | `2d9dce64-3aea-4078-b0f7-597e529bb952` | `upload` | Bound to `/trajectory` only; cannot read sessions |
| Platform aggregation for Ops | machine client `ops-trajectory-observer` | `986bea29-fb5d-4a7e-809d-8fb6f9e3e917` | `a4b37b56-b575-41d6-a85b-e88fc951b446` | `read_all` | Reads `api/platform` and request traces only |
| Authentication, scope and isolation probe | machine client `trajectory-read-acceptance` | `142dd516-535e-4898-901c-3d4bb40686fb` | `d158131c-2e4f-488c-8413-f7afe126f066` | `read` | Owns no data, so it must see an empty session list; any other-account row is an isolation defect |
| Interactive owner access | human account (owner) | `937c154a-010a-420a-af47-90b53d0cc28d` | issued per device, never recorded here | `read`, `configure`, `read_all` | Human key. Never used by automation or monitoring |

The first three are native service clients whose accounts are members of the
`/trajectory` group only. Identity re-validates each request; disabling the
client, revoking the key or removing the group denies the next call.

## Owner-scoped data acceptance

Session lists and analysis details are scoped to the calling account. A dedicated
machine account therefore cannot read a human owner's sessions, and that is
intended. Acceptance that must read real sessions uses a temporary `read` key
issued to the data owner:

1. Issue the key from the private host administrator into a root-only client
   file, bound to `service=trajectory`, the owner account and scope `read`.
2. Run the read acceptance on the candidate port. Record account ID, key ID,
   request count, concurrency, latency, memory samples and OOM counters.
3. Revoke the key by ID, delete the client file, and confirm the reused token is
   rejected with `403`. Do not store the token in evidence, logs or documents.

A permanent owner key is never used for release automation, and a machine token
never impersonates a human owner.

## Rotation and revocation

- Keys are verified by SHA-256 hash from the service registry; rotation means
  issuing a new key ID, installing it, and revoking the old ID.
- Revocation is effective on the next request. There is no positive
  authorization cache, so no drain is required for a revoked key.
- Changing the machine client (`client_id`) requires re-issuance with the same
  account or a new account; a machine account without a registered native client
  is rejected.
- Registry files must remain root-owned, group-readable by the service group and
  never world-readable. The service refuses a registry with looser permissions.

## What acceptance must prove

| Check | Account | Expected |
|---|---|---|
| Unauthenticated business request | none | `401` |
| Owner session list and analysis detail | temporary owner `read` key | `200`, expected session and task counts |
| Other accounts' sessions | `read` machine probe | empty list |
| Platform aggregation after a machine read | `ops-trajectory-observer` | `200` |
| Revoked key reuse | any revoked key | `403` |
| Scope boundary | `read` key calling `api/platform` | `403` |

## Current state

The 4.0.1 deployment created the `trajectory-read-acceptance` machine client and
its `read` key, and revoked the temporary owner key immediately after the
authenticated acceptance. The probe currently reports an empty session list and
`403` for platform aggregation.

Retiring the probe requires revoking
`d158131c-2e4f-488c-8413-f7afe126f066`, removing the account from the
`/trajectory` group and disabling the native client. Keep revoked key entries in
the registry instead of deleting history.
