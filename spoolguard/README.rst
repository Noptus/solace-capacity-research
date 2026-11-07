SpoolGuard: queue admission with explicit uncertainty
====================================================

An executable research prototype for a practical Solace problem: one slow
subscriber can constrain publishers whose messages also reach healthy queues.
SpoolGuard uses the publisher-to-queue routing matrix to allocate rates locally
while reserving capacity for stale observations, bursts and actuation delay.

The package contains a mathematical derivation, an exact rational planner,
an offline SEMP snapshot importer, a publisher shaper with contract expiry,
synthetic and live outage experiments, captured broker evidence and tests.
Python 3.10 or newer is sufficient; there are no third-party dependencies.

Run from this directory::

    python3 -m unittest discover -v
    python3 spoolguard.py plan scenario.json
    python3 spoolguard.py import-semp semp-snapshot.example.json
    python3 experiment.py
    python3 audit_live.py live-evidence

The last command regenerates results.json and queue-outage.svg. The example
SEMP snapshot is fabricated using documented field names, not captured from
a running broker. The planner and importer never connect to a broker.
live_lab.py is the separate executable that provisions an isolated localhost
Docker broker and sends real persistent REST messages. See LIVE-RESULTS.rst
for the measured result, reproduction command and experiment limitations.

What the experiment shows
-------------------------

Three publishers each request 2 MB/s. Orders and analytics share an archive
queue; payments use an independent queue. The archive consumer is offline.
Observations are five seconds old and actuation takes one second. The planner
reserves all admitted bursts, in-flight messages and measurement uncertainty.
All three modeled queues receive zero service throughout the experiment.

===================== =========== =========== ============ ===========
Policy                Orders MB/s Analytics   Payments     Total MB/s
===================== =========== =========== ============ ===========
Unregulated           2.000       2.000       2.000        6.000
Uniform global limit  0.250       0.250       0.250        0.750
SpoolGuard            0.333       0.167       2.000        2.500
===================== =========== =========== ============ ===========

Both regulated policies keep the archive at or below its protected 90 MB
ceiling, beneath the physical 100 MB quota, for 30 seconds. Unregulated virtual
demand reaches 195 MB. Virtual demand above capacity is not a prediction of
the number of messages rejected by a real broker.

SpoolGuard admits 3.33 times as much source traffic as this uniform baseline.
This is a deliberately chosen example showing isolation, not a representative
benchmark, a claim of optimal total throughput, or a broker performance result.
Weighted max-min fairness gives orders twice the rate of analytics at their
shared bottleneck; payments are independent and retain full demand.

Inputs and outputs
------------------

Every rate uses accounted bytes per second. Every capacity, occupancy, burst
and reserve uses the same accounted bytes. A routing coefficient a_ij is an
upper bound on queue-i accounted bytes per publisher-j source byte. For fixed
message overhead h and minimum payload l, 1+h/l is one possible conservative
coefficient. Verify the accounting on the deployed broker; do not assume
payload byte counts equal quota usage.

Required per-publisher fields:

* name, demand_bps, burst_bytes. Optional weight defaults to 1.
* burst_bytes bounds arrivals over EVERY interval: B + r times interval length.
  Include packetization, transport bunching, retries and duplicates. A burst
  smaller than the largest accounted message cannot support that message.

Required per-queue fields:

* name, capacity_bytes, observed_bytes, reserve_bytes and routes.
* age_seconds: upper bound on observation age at the decision.
* actuation_seconds: upper bound until all affected publishers enforce rates.
* old_ingress_bps and old_burst_bytes: bounds on pre-enforcement arrivals,
  including uncontrolled producers; rxByteRate is only an observation.
* measurement_uncertainty_bytes and in_flight_bytes: explicit upper bounds;
  use zero only when justified.

Optional per-queue fields:

* service_floor_bps defaults to zero. A positive value requires a strict
  service guarantee on release of accounted spool bytes, with latency bounded
  by service_latency_seconds. An average consumer rate is insufficient.
* background_bps and background_burst_bytes reserve future uncontrolled
  traffic. All traffic reaching modeled queues must be covered.

horizon_seconds starts when the new contract is fully enforced. The output
contains rates as exact rational strings, plus a peak bound and margin for
every modeled queue. Preserve these strings or round publisher rates DOWN.
Ceil byte reservations when converting fractional capacities to whole bytes.

An uncertified result exits with status 2 and supplies no admission rates.
It means the supplied assumptions cannot establish the claimed bound.
Stopping a controlled publisher may still leave unavoidable in-flight or
background traffic; the tool cannot promise recovery in that situation.

Solace integration path
----------------------

1. Read the deployed broker's /SEMP/v2/monitor/spec and /help. The bundled
   importer was checked against Solace's public software-broker monitor
   specification on November 7, 2026. Confirm compatibility with your version.
2. Collect queue observations using a read-only monitoring account. Include
   every collection page; the importer rejects a response advertising a next
   page. Use a collection timestamp or the oldest per-queue observation to
   establish the age bound; HTTP completion time alone is insufficient.
3. Merge observed_bytes into an explicitly reviewed scenario with capacities,
   traffic contracts and complete routing. The importer leaves the reported
   MB quota unconverted: determine the deployed broker's MB accounting and
   convert explicitly. It rejects zero quotas, which denote last-value mode.
4. Start with service_floor_bps = 0. Validate the planner against a disposable
   broker, including stopped consumers, delayed ACKs, variable message sizes,
   retries, subscription changes, and stale or missing telemetry.
5. Enforce the rates and bursts in publisher-side shapers. These shapers are
   a required integration component. enforcement.py supplies an exact byte
   bucket with monotonic activation and expiry; live_lab.py demonstrates its
   use for one sequential REST publisher per stream. The planner itself only
   computes advice. It does not intercept or control other publisher clients.
   Bound total actuation delay and include old messages still in flight.
6. Renew the contract before expiry. If renewal fails, cease new admission
   early enough that residual arrivals fit the already reserved envelope.
   Across renewals, preserve valid arrival envelopes; do not reset burst
   buckets without reserving each reset. Recompute after topology changes.

Solace recommends polling queue monitor endpoints no more often than once
every 30 seconds; responses can take longer. Choose horizon, age and reserves
to cover collection, processing, transport and enforcement. Do not solve a
small safety horizon by aggressively polling SEMP.

The certificate covers the modeled queue quotas only. It does not certify
broker-wide or VPN spool quotas, spool-file exhaustion, replay logs, HA,
replication, message-count limits, per-flow unacknowledged limits, or partitions
not represented in the model. Physical message storage can be shared across
fanout destinations, so summing queue usage is not an exact physical-spool
model. Those resources require separate conservative constraints and bounds.

Further decisive experiments
----------------------------

The captured live run covers a complete consumer outage and fixed message
sizes. Extend the disposable Solace broker experiment with delayed consumer
ACKs, jitter, reconnects, variable messages and contract renewal,
measuring publisher ACK/NACK behavior, actual queue occupancy, consumer ACK
delay, and upstream publisher backlog. Verify byte accounting and burst
enforcement first. Count upstream waiting as waiting, not as throughput won.
Accept a safety claim only for fault cases included in the traffic and service
contracts. Compare against per-topic throttles and existing admission methods
before making any novelty or general performance claim.

References
----------

* Solace message spooling and ACK behavior:
  https://docs.solace.com/Messaging/Guaranteed-Msg/Message-Spooling.htm
* SEMP endpoint polling, paging and monitoring guidance:
  https://docs.solace.com/Admin/SEMP/SEMP-Features.htm
* SEMP specification discovery:
  https://docs.solace.com/Admin/SEMP/SEMP-API-Ref.htm
* Public software-broker monitoring reference and linked OpenAPI definition:
  https://docs.solace.com/API-Developer-Online-Ref-Documentation/swagger-ui/software-broker/monitor/index.html
* Le Boudec and Thiran, Network Calculus (established theoretical foundation):
  https://leboudec.github.io/netcal/

See RESEARCH.rst for the conditional theorem, proof and limits on novelty.
