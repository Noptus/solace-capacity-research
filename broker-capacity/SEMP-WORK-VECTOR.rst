A compact SEMP work vector
===========================

The useful abstraction is traffic work per observation interval, followed by
explicit resource calibration. Traffic measurements alone do not identify peak.

semp_work_vector.py implements this small representation from SEMP v2 counters:

* dataRxMsgCount delta: incoming client data messages, excluding control traffic;
* dataRxByteCount delta: incoming broker-counted data bytes, including message
  overhead rather than just payload;
* sum of selected queues' spooledMsgCount deltas: durable queue-ingress copies;
* sum of their spooledByteCount deltas: durable queue-ingress byte work;
* msgSpoolRxMsgCount delta: a separate guaranteed-ingress attempt diagnostic.

Divide by elapsed time for a work-rate vector. Divide by source data-message
count for per-message demand features. Python Fraction preserves the supplied
integer counts and nanosecond duration exactly; polling uncertainty remains.
Zero source traffic produces no per-message estimate. Counters update at
different pipeline stages: changing in-flight work can make interval deltas
differ even when final run totals reconcile. The adapter flags a guaranteed-
stage delta larger than the source-data delta. Normalized ratios then describe
the observed windows, not an exact per-message service cost. Longer aligned
windows and pipeline-boundary checks are needed for calibration.

The adapter rejects counter decreases/resets, changed queue membership,
duplicate queue observations and VPN mismatches. A generic caller must state
whether the selected queues cover its intended scope. This cannot be inferred
from one queue collection if polling/pagination omitted queues. All observed
queue sets must be closed over the interval; pre/post calls are not atomic.

Example on recorded SDKPerf evidence, without a running broker::

    python3 outputs/broker-capacity/semp_work_vector.py \
      outputs/broker-capacity/sdkperf-validated-evidence/sdk-0-256-4000.json

For the 256-byte, fanout-one SDKPerf case, source data bytes per message are
331 in the final run counters, while queue-spooled bytes per message are 256.
These are distinct work quantities. The JavaScript client's overhead need not
match. Never replace either quantity with the size of the application payload
without checking the counter definition and actual message format.

Why keep copy bytes separate?
----------------------------

For a stationary stream with size S and matching-queue count F, queue-copy byte
work per source message corresponds to E[S*F], when those selected counters
measure payload bytes and all relevant routes are covered. It is not generally
E[S]*E[F]. The two-point test with sizes/fanouts 1 and 9 has identical separate
means yet work of 9 or 41 depending on their pairing. The adapter retains the
copy-byte quantity directly instead of imposing independence.

Counters alone still do not reveal feature-specific CPU or storage costs.
The candidate calibrated abstraction is a resource roofline::

    peak = min(edition_limit, min_r capacity_r / dot(demand_r, work_per_message))

Nonnegative demands and capacities need to be estimated under a fixed hardware,
protocol and feature class, with a verified saturation/stability frontier.
TLS, compression, persistence, replay, HA and routing/filter behavior may need
additional work dimensions or separate classes; a flag is not evidence of a
known resource cost. Cache-to-disk transitions can invalidate a single linear
regime. The existing held-out point models remain unvalidated.

Consequently the adapter deliberately reports peak_messages_per_second as null.
It is a measured input abstraction and diagnostic foundation, not a trained
or validated general peak predictor. Keep edition limits separate from observed
finite-window rates and from unrestricted Enterprise capacity.

Pressure telemetry through SEMP v1
--------------------------------

The request schema supports these read-only queries on the tested broker::

    <rpc><show><message-spool><detail/></message-spool></show></rpc>
    <rpc><show><message-spool><stats/></message-spool></show></rpc>
    <rpc><show><memory/></show></rpc>
    <rpc><show><process/></show></rpc>

The process reply contains top-style aggregate CPU fields, per-process cpu-usage
and cpu-time, and memory information. This corrects a broader interpretation of
the earlier SEMP v2 broker-object limitation. The adapter preserves raw CPU fields;
it does not turn a percentage into a broker utilization fraction without knowing
the denominator and sample semantics. In this container the memory reply shows
roughly the Docker VM's 8 GiB total, not its 3 GiB cgroup quota. Supplementary
cgroup measurements and configured limits must remain distinguishable.

The adapter returns cache usage divided by the reported cache limit, and the
disk-spooled count. That same-unit ratio avoids treating max-cache-usage=10 as
10 MB. A single low CPU/cache observation cannot establish spare throughput,
rule out I/O delays or identify a hidden per-thread/service/edition limit.

Counter caution under overload
------------------------------

The rejected 32768-byte / 1000-message/s SDKPerf trial attempted 60000 messages,
with 30016 queue-quota rejections and 29984 consumer receipts. Its SEMP ingress
attempt counter still advanced by 60000. It is excluded from clean calibration.

SDKPerf 10.30.3's Total ACKED Messages summary was also not a success count in
that trial: it summed to 90016. Per-message ACK Events summed to 29984; NACK
Events summed to 30016. The numerical relation in this observation is
ACKED-summary = attempts + NACK Events. The internal implementation cause has
not been established; do not infer a general correction formula from one case.
The accepted cases have zero NACKs and reconcile all relevant counters.

A finance-facing use
-------------------

An event-driven research or signal platform can measure incoming events, bytes,
downstream model/consumer copies and copied bytes. This describes infrastructure
work even when the highest-value events also create the most fanout. Combine
it with the separate dependence-bound tool to stress an illustrative opportunity
and capture-fraction joint distribution. Neither operation establishes trading
returns or translates broker ACK time into an execution delay.

Six tests cover exact rates, reset/membership rejection, zero traffic, stage
counter timing, the
dependence counterexample and legacy pressure/CPU parsing. Primary API field
definitions were read from the tested broker's SEMP monitor OpenAPI schema;
raw records and the tested broker version accompany this output.
