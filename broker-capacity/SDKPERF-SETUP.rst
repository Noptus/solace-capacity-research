Independent SDKPerf crosscheck
==============================

This adds an independent native-Java/JCSMP tool to the prior custom Node.js
SMF experiments. It does not constitute a controlled comparison of programming
languages or a proof of unrestricted broker peak capacity.

Tool sources
------------

Solace SDKPerf documentation:
https://docs.solace.com/API/SDKPerf/SDKPerf.htm

Solace SDKPerf Java download (the recorded download resolved to 10.30.3):
https://products.solace.com/download/SDKPERF_JAVA

Java: Eclipse Temurin ARM64 macOS JRE 17. The exact release, provider URL and
verified SHA-256 are in sdkperf-validated-evidence/tool-provenance.json.
No third-party SDKPerf or Java binaries are redistributed in the research output.

SDKPerf is a developmental testing tool; Solace describes it as non-production
and provided as-is. The SolaceLabs performance harness is existing related work:
https://github.com/SolaceLabs/solace-perftest-harness

Design and interpretation
-------------------------

The eight-case design was written before running the corrected study: payloads
256, 32768 and 131072 bytes; one durable queue; four publishers; 60 seconds of
messages at each requested rate; a final repeat of the 8000-message/s small case.
Fixed-count publishers may take longer than 60 seconds when backpressured.
Report that as failure to achieve the target, even if every message later drains.

Broker settings match the earlier study: pinned Standard-edition ARM64 image,
two-CPU Docker quota, 3 GiB memory, 1 GiB shared memory, localhost-only ports.
Java clients run on the host. SDKPerf publisher and subscriber ACK windows are
255; publisher ACK timeout is 5000 ms (the tool's documented CLI maximum),
unlike the earlier Node.js study's 60000 ms. SDKPerf also adds CRC/order metadata
and uses its own rate control rather than the previous app-credit controller.
These differences preclude attributing any rate difference solely to a client
language, SDK, broker or single setting.

The runner records raw logs, SEMP v2 VPN and queue snapshots, SEMP v1 spool
detail, and supplementary container CPU counters. The interior diagnostic uses
samples whose controller timestamps fall between 10 and 50 seconds. A target
tracks operationally if ingress is within 5% of the requested rate and queue
byte growth by least-squares slope is no more than 2% of offered payload bytes/s.
Those tolerances are a declared finite-window diagnostic, not a statistical
stationarity test or a future service guarantee. Max sampled queue size is not
the true instantaneous maximum. Raw snapshots are retained for reanalysis.

The integrity gate separately requires all expected publisher sends/ACKs,
no publisher NACKs, matching SEMP ingress attempts, consumer count, CRC and
per-stream order checks, and a fully drained queue. A failed throughput target
does not itself invalidate the integrity of a completed experiment.

Retained setup failure
----------------------

sdkperf-evidence contains the initial failed 4000-message/s run. All four
publisher processes defaulted to the same SDKPerf order-check stream, so each
reused sequence numbers 1..60000. The consumer reported 180000 duplicate
sequence numbers and 59999 out-of-order numbers despite matching message
counts, zero CRC errors and matching broker attempts. This is an invalid
multi-source sequence-check configuration, not evidence of broker duplication.
It is excluded from the corrected study. The fix assigns distinct positive
publish stream offsets with -pso=1,2,3,4. The original run-source is preserved.

The preliminary single-publisher 200-message pilot passed CRC/order, ACK,
receive and drain checks. It is retained separately in sdkperf-pilot-evidence.

Reproduce and audit
-------------------

Download/extract the tool and an appropriate Java runtime under work/ first.
Then, from the original workspace root (choose a fresh output directory)::

    python3 outputs/broker-capacity/sdkperf_crosscheck.py \
      --output work/sdkperf-reproduction \
      --design-file outputs/broker-capacity/sdkperf-validated-evidence/design.json \
      --java /absolute/path/to/java \
      --sdkperf /absolute/path/to/sdkperf-jcsmp-10.30.3

The broker image must already be available to Docker. Preserve the sibling
spoolguard folder used by capacity_probe's Broker helper. The runner removes
only its own disposable broker and temporary credential file. It refuses to
overwrite an output directory containing design.json. The required localhost
ports are 18080, 15555 and 15550.

After a completed run, audit retained evidence without a running broker::

    python3 outputs/broker-capacity/audit_sdkperf.py \
      outputs/broker-capacity/sdkperf-validated-evidence --allow-prefix

The independent auditor imports no runner code. Audit success establishes the
listed integrity checks and recomputed rates, not broker peak capacity.

Actual terminal states and follow-up controls
--------------------------------------------

The original corrected eight-case design stopped at its fifth case (32 KiB,
1000/s), after a 300 MB queue-quota overload. Its first four cases are accepted
and independently audited; the complete original design is not marked complete.
--allow-prefix explicitly audits that accepted prefix while reporting the
failed/unrun cases, rather than fabricating a completed-study marker.

The separate follow-up repeats the 256-byte 8000/s offer, then tests 128 KiB at
76/s and 152/s. The larger-message queue quota is explicitly 1250 MB. SEMP v1
show process is sampled every fifth poll, with separate probe timestamps.
The first two follow-up cases pass integrity. The third has an unresolved tail
after the default two-second publish-end delay and is excluded from calibration.

A final single-case control uses 128 KiB / 152/s and a 60-second publisher-end
delay. All 9120 source messages are ACKed and received with CRC/order checks,
but SEMP records 9344 ingress attempts. The 224 extra attempts are consistent
with protocol retries, though the SDK retry counter was not instrumented.
The zero-surplus calibration gate correctly rejects that case too. It remains
useful completion/counter evidence; it is not discarded or silently called clean.

SDKPERF-RESULTS.rst and sdkperf-summary.json report the six accepted cases.
The accepted-prefix audits total 126 checks and 1804560 source messages and
matching consumer receipts. Failure records and source snapshots remain intact.
