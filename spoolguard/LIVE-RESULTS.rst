SpoolGuard: two real Solace outage runs
======================================

On November 7, 2026, two controlled localhost experiments on Solace Event
Broker 10.26.9.13589 exercised the prototype's zero-service case. Routing-aware
admission accepted 4.20 and 4.28 times the source payload accepted by a uniform
global throttle. Both controlled policies had zero rejected publications;
all of their measured queue peaks were below their mathematical bounds.

This is an engineering result for a chosen workload. It does not establish
a novel admission-control algorithm or an expected production improvement.

Measured results
----------------

Each policy ran for 30 seconds. MB below means 1,000,000 source payload bytes,
not queue-accounted bytes, and is rounded to three decimals.

================= ============== ============== ============== ==============
Policy            Run 1 accepted Run 2 accepted Run 1 rejected Run 2 rejected
================= ============== ============== ============== ==============
Unregulated       7.868 MB       8.024 MB       2,335          2,401
Uniform throttle  1.647 MB       1.647 MB       0              0
Routing aware     6.918 MB       7.053 MB       0              0
================= ============== ============== ============== ==============

Unregulated failed responses were HTTP 503 with a spool-over-quota reason.
The successful-publication counts matched the broker's spooled-message counts
for every matching queue. That includes the healthy orders queue that shares
its publisher with the full archive: rejected messages did not get spooled to
that otherwise available queue. This is the cross-queue coupling the planner
accounts for.

Unregulated admission accepted more total payload than either controlled
policy, while rejecting a large part of the affected traffic. The controlled
policies reserve headroom and avoid those rejections. The reported 4.20-4.28x
gain compares routing-aware control with uniform global throttling, not with
unregulated admission, optimally scheduled traffic or every possible policy.

For both runs, the controlled archive's peak was exactly 2,163,344 accounted
bytes, below its 2,700,000-byte mathematical ceiling. Its unregulated copy
peaked at 3,148,316 bytes and rejected further messages. The configured quota
was 3 in the SEMP MB field; the planner deliberately used a conservative
3,000,000-byte capacity and a 300,000-byte reserve. These observations do not
establish a universal conversion between configured quotas and exact ingress
rejection thresholds, including packet overshoot and version differences.

Topology and workload
---------------------

Each policy used its own copy of three queues on the same disposable broker:

* Orders publisher -> archive and orders-processing queues.
* Analytics publisher -> archive queue.
* Payments publisher -> payments-processing queue.

Every queue had egress disabled, no consumer bindings, TTL expiry disabled
and discard NACKs enabled. Thus no release occurred during the experiment;
the final observed occupancy equals the observed peak. This avoids estimating
an unsupported positive service floor. The archive began with sixteen 65,536-
byte messages; the other workload queues began empty.

Each source requested 200,000 payload bytes per second and sent fixed 4,096-
byte messages. Source token buckets allowed two messages of burst and used
monotonic integer nanoseconds and exact rational rates. The planner reserved
three messages per stream at each queue, because each sequential HTTP stream
can have one message outstanding. RESEARCH.rst derives the corresponding
source-to-arrival envelope without assuming a transport latency bound.

Routing-aware allocation gave orders twice analytics' rate at the archive
bottleneck and preserved payments' 200,000-byte/s assigned rate. Uniform
throttling reduced all three sources by the same factor to fit that same
archive budget. Scheduling and HTTP overhead caused the highest-rate sources
to send somewhat less than their assigned budgets; these are measured accepted
bytes, not an assumption that assigned rates were achieved exactly.

Byte accounting
---------------

Twenty persistent REST messages were retained for each of three payload sizes:

================== ================== ====================
Payload per message Accounted per msg  Measured overhead
================== ================== ====================
256 bytes          316 bytes          60 bytes
4,096 bytes        4,156 bytes        60 bytes
65,536 bytes       65,596 bytes       60 bytes
================== ================== ====================

The experiment used a conservative 1.25 accounted-byte expansion per payload
byte. Calibration and final workload counters independently fit that envelope
in both runs. This empirical check applies to these fixed message formats,
headers, paths and broker version; it is not a guarantee for arbitrary clients
or future metadata changes.

Evidence audit
--------------

Each run has four raw records: live-results.json, send-traces.json,
snapshot-before.json and snapshot-after.json. An independent auditor imports
neither the planner nor the shaper and checks:

* Every inclusive source interval against its byte envelope, using a prefix
  minimum rather than replaying the implementation's token bucket.
* Activation, expiry, request ordering and at most one outstanding message.
* Publisher HTTP success counts against all matching broker queue counters.
* Accounting expansion, absence of release, and measured final/peak equality.
* Protected bounds recomputed from the actual assigned rates and input model.
* The gain recomputed from successful raw publication counts.

All 117 checks passed for each captured run. Five audit tests also require
that tampered expiry times, traffic traces, fanout counts and peaks be detected.
The 31 mathematical-planner and enforcement tests pass as well, for 36 total
tests. The mathematical randomized cases remain fixed-seed and reproducible.

The audit establishes internal consistency of the captured experiment. The
records are locally generated evidence, not an externally authenticated
attestation or proof of production coverage.

Reproduce
---------

The offline evidence audit needs only Python 3.10 or later::

    python3 -m unittest discover -v
    python3 audit_live.py live-evidence
    python3 audit_live.py live-evidence-repeat

The live experiment additionally needs Docker with at least 3 GiB available
for the broker, sufficient Docker storage, and these localhost ports free:
18080 (SEMP), 19000 (REST), and 15550 (spool readiness). It is restricted to
localhost and does not accept a production broker URL. From this directory::

    docker pull solace/solace-pubsub-standard@sha256:adbdf6c060abafb0e30dac3d46e335c1e5ea56a7ff02804f9f64b08d84b7b00e
    python3 live_lab.py --work-dir ../../work/reproduce --output ../../work/reproduced-evidence
    python3 audit_live.py ../../work/reproduced-evidence

The digest pins the ARM64 image actually tested on this machine. An x86 host
would require compatible emulation or a separately pinned x86 image, which
has not been tested here. The script never pulls images implicitly. It creates
an isolated container with a random local administrator credential, waits for
the message spool and default VPN to be ready, and removes the container and
its anonymous volumes after the experiment. Credentials are kept out of the
evidence. The Docker image remains cached for future runs.

One initial attempt at a fresh-container replay failed with a SEMP HTTP 400
while provisioning after /about had responded. The exact response body was
not captured, so its precise root cause is unproven. This exposed an inadequate
readiness gate; the harness now checks the guaranteed-active health endpoint
and the default VPN before provisioning and retains error details on failure.
The corrected clean-start replay completed and supplied the second run above.

Limits and next work
--------------------

Two runs and a topology selected to expose isolation are insufficient for a
general performance claim. All three policy copies shared the broker during
each run, so they may influence one another's scheduling. This was a small,
fixed-message consumer-outage experiment, not a saturated broker benchmark.
It counts payload accepted into the broker, not business processing completion.

The next experiments should introduce delayed consumer ACKs, variable message
sizes and metadata, transport faults, subscription changes, concurrent
producers and contract renewal. Broker/VPN physical spool, message-count,
HA and replication constraints remain outside this queue certificate. The
example does not implement automatic topology discovery or general SDK
interception. No positive service-floor claim has been validated live.

Relevant primary documentation
------------------------------

* Spooling, fanout match retention and acknowledgment behavior:
  https://docs.solace.com/Messaging/Guaranteed-Msg/Message-Spooling.htm
* Discard rejection and effects on other matching queues:
  https://docs.solace.com/Messaging/Guaranteed-Msg/Configuring-Queues.htm
* Persistent REST publication and producer acknowledgment:
  https://docs.solace.com/API/REST/Using-REST.htm
* Solace health checks and guaranteed-active spool readiness:
  https://docs.solace.com/Admin/Health-Checks-Readiness-Probes.htm
* Queue monitoring and recommended polling intervals:
  https://docs.solace.com/Admin/SEMP/SEMP-Features.htm
