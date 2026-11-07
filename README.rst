When Message Rates Mislead - research review packet, revision 2
==============================================================

7 November 2026 | Unpublished, AI-assisted independent research draft

Start with research-draft-sdkperf.pdf (seven pages). It supersedes the earlier
six-page draft for the SDKPerf results and SEMP CPU discovery. This packet is
intended for technical review before public release; it contains no CV, private
Numerai code or career notes. Author attribution and publication destination
still need to be settled. No new mathematical theorem or trading profit is claimed.

What is implemented
-------------------

1. Finite-horizon, routing-aware queue admission with exact arithmetic and an
   expiring token-bucket enforcement prototype. Two local outage experiments
   accepted about 4.20x and 4.28x as much payload as a global-throttle baseline,
   without quota rejections. This is admission allocation, not broker speedup.

2. Broker-capacity experiments and compact work features. Twenty original
   controlled Node.js cases expose model errors, flow-control effects and
   variation. Six additional SDKPerf/JCSMP cases pass full CRC/order and count
   checks: 1,804,560 source messages and matching consumer receipts. Higher
   offered loads and three later failures are retained, not promoted to clean
   peak measurements. An earlier same-stream setup failure is retained too.

3. Exact sharp dependence bounds for nonnegative finite marginals, with
   attaining joint-distribution witnesses. The financial example is hypothetical
   and applies classical rearrangement mathematics, not a new theorem or backtest.

The general peak predictor remains unvalidated. The initial held-out point
models overpredicted measured rates by roughly 29-31%. The new SEMP adapter
measures source messages/bytes and queue-copy messages/bytes directly, retaining
the effect of size/fanout dependence. It also exposes pressure and stage-counter
warnings. It deliberately does not turn traffic counters into a peak claim.

New in this revision
--------------------

* broker-capacity/SDKPERF-RESULTS.rst: accepted rates, failed target checks and
  explicit study terminal states, plus JSON/CSV summaries and a static figure.
* broker-capacity/SDKPERF-SETUP.rst: SDKPerf/JCSMP reproduction, stream-ID fix,
  overload rejection and publish-end-delay controls.
* broker-capacity/SEMP-WORK-VECTOR.rst and semp_work_vector.py: exact traffic
  feature extraction, reset/scope handling and legacy pressure/CPU parsing.
* Legacy SEMP show process supplies CPU fields. A missing v2 broker-object field
  is not evidence that CPU data is unavailable through every SEMP interface.
* SDKPerf's ACKED Messages display is not treated as a success count under NACKs;
  ingress attempts, ACK events, queue copies and receipts are reconciled separately.

Audit without running a broker
-----------------------------

From this packet's root::

    python3 -m unittest discover -s spoolguard
    python3 -m unittest discover -s broker-capacity
    python3 -m unittest discover -s finance-dependence
    python3 broker-capacity/audit_study.py broker-capacity/matrix-evidence
    python3 broker-capacity/audit_study.py broker-capacity/replication-evidence
    python3 broker-capacity/audit_study.py broker-capacity/cache-window-evidence
    python3 broker-capacity/audit_sdkperf.py broker-capacity/sdkperf-validated-evidence --allow-prefix
    python3 broker-capacity/audit_sdkperf.py broker-capacity/sdkperf-followup-evidence --allow-prefix

The SDKPerf designs stopped on retained failures; --allow-prefix reports that
and audits only the accepted cases. Neither design is silently relabeled complete.
The separate drain control passes delivery/ACK/CRC/order checks but fails the
zero-surplus ingress gate and is excluded from clean calibration.

Live reproduction uses Docker and separately obtained Solace SDKs/SDKPerf. See
the component setup notes for the pinned broker image, client versions, paths,
ports and resource limits. No third-party binary dependencies are redistributed.
Some run commands show the original outputs/ prefix; adapt that prefix when
running from the extracted packet root. Never direct this lab at a live broker.

Evidence and limitations
------------------------

Short fixed-rate checks do not establish statistical stationarity, future queue
safety or unrestricted Enterprise capacity. SDKPerf and Node.js settings differ;
their comparison does not isolate language or SDK performance causally. The
longer-drain control's 224 extra ingress attempts are consistent with retries,
not directly identified by an SDK retry counter. Raw records remain available.

MANIFEST-V2-SHA256.json covers this revision's archive files. The older
research-package.zip and MANIFEST-SHA256.json describe the earlier snapshot;
they are not the current workspace's checksum manifest. Personal career
materials remain separately under career/ and are excluded from both archives.

Large rejected-case logs are compressed losslessly as .log.gz in this packet.
raw-log-manifest.json records the original filenames, byte counts and SHA-256
hashes. Decompress with gzip -dk to inspect them using their original names.
Accepted-case logs remain plain text and work directly with the auditors.
