# Two-slot compact cache validation

This is historical isolated validation, not a production deployment procedure.
The change retains at most two compact Domain snapshots and adds no database DDL,
expression indexes, alternate ledger or source-contribution cache.

## Environment and sample

- Remote host: `batcave-wsl`, kernel `6.18.33.2-microsoft-standard-WSL2`.
- Baseline: installed Trajectory `3.2.3-64f4c97007a0`, source `44b2d55`.
- Candidate `domain.py` SHA-256: `cdf7e225e300a15a4c38e046b6a6f5acc4ccc99868e6cdd1994a23b930ede4a2`.
- Sample: existing isolated e6 backup reproduction, 489,668 immutable ledger events.
  Original backup size was 5,247,266,816 bytes. Earlier isolated index experiments
  left free pages, so the same fixture file measured 5,597,061,120 bytes for this test.
  No production database was queried or copied. This test asserted that all earlier
  experimental indexes were absent and changed no schema or event data.
- Execution: one isolated process, 1 GiB memory limit, swap disabled. A-B-B-A order
  on the same remote filesystem and sample, with no profiler in timed operations.
- Background: production model jobs and normal synchronization shared the host.
  Four model jobs were reported at experiment start; per-job load was not continuously
  sampled. These results are not an uncontended benchmark or an HTTP availability probe.

## Results

Each cell is the median of two measurements. A is the installed single-slot Domain;
B is the real candidate Domain source, loaded against the same installed dependencies.

| Operation | A | B |
| --- | ---: | ---: |
| Account cold calculation | 15.794 s | 14.775 s |
| Global cold calculation | 15.883 s | 15.450 s |
| Account read after global view | 14.937 s | 0.384 ms |
| Source contributions, uncached | 4.999 s | 4.809 s |

The intended gain is removal of account/global cache thrashing. Cold calculation
and source reads use the unchanged calculator; their small timing differences are
not claimed as algorithmic improvements. Cache hits still acquire the existing
shared calculation lock and may wait for a concurrent source scan.

All four complete output types had matching SHA-256 values across all four runs,
after recursively excluding only `generated_at`. Two cached snapshots serialized
to 8,369,604 bytes and retained zero event-contribution arrays. The process high-water
RSS was 204,096 KiB. A cgroup sample during the final phase reported peak memory
663,883,776 bytes, swap zero, and all max/OOM counters zero. The cgroup sample is not
represented as an observation taken after process exit.

Capacity is bounded by two snapshots, not by a fixed byte count. Aggregate counts,
identity maps and the selected source can still grow with the workload.

## Regression coverage and evidence

Remote complete product/client tests: **143 passed, no skips**, with both pinned native
binaries configured. Ruff, Black and mypy passed. Tests cover concurrent account/global
reads with distinct account totals, third-owner/date eviction, ingest/price/correction
invalidation of both views, direct-calculator output parity, and exclusion of a 256 KB
raw reference from cached values. Source reads preserve the compact cache and retain
no source-contribution array in it.

Receipts and scripts are retained under remote
`/home/saveer/BatCave/tests/trajectory-latency-20261019` and the controller's
`output/trajectory-latency-20261019`: `two-slots-abba-receipt.json`,
`two-slots-abba-run.txt`, `experiment_two_slots_abba.py`,
`two-slots-full-tests.txt` and `two-slots-cgroup-final-phase.txt`.

Expression indexes were explicitly rejected from this patch. A separate two-record
fixture showed that an owner/kind/time index changes the existing unordered
request-route winner from Wenshu to Ops. Any future index change must first preserve
the baseline account primary-key and global rowid traversal semantics and test
conflicting references and ties. Large-corpus output parity alone does not prove this.
