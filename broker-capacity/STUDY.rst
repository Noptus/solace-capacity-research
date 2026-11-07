Predicting broker headroom from a small work vector
=================================================

Latest result: the first point models failed the held-out test
------------------------------------------------------------

The study has advanced beyond the pilot below. Twenty additional accounted
workload cases cover an eight-point training matrix, two declared held-out
size/fanout combinations, two small-message controls, four large-message
repeats and four outstanding-credit controls. The main matrix uses four
publishers, explicit consumer receipt feedback and a 60-second SDK retransmit
timeout, with retries instrumented separately. See research-draft.pdf in the
parent output folder for the review draft and the raw evidence subfolders.

* The joint-work demand model overpredicted the two unseen combinations by
  31.1% and 28.9%. A two-limit Roofline predictor had almost identical errors.
  No accurate general peak predictor has been validated.
* All twenty accepted cases reconcile sends, ACKs, consumer counts and queue
  counts, and end with empty queues. The source/counter audit is independent
  of the runner and model fitter. It is a count audit, not sequence/CRC proof.
* A repeated 128-KiB/fanout-1 case changed from 83.0 to 124.2 interior ACK
  messages/s. A single fixed prediction cannot be within 19.9% of both under
  the relative-error criterion. This observed-pair bound is not a statistical
  population result.
* Four alternating outstanding-credit controls did not isolate a cache-mode
  throughput benefit. Both budgets hit near the reported cache ceiling and
  retained disk-spooled messages. Lower credit had similar admitted totals
  within each pair and smaller maximum publisher-ACK delays in both pairs,
  but two fixed-order pairs do not establish a general causal performance law.
* The stored field steady_ack_messages_per_second is a legacy name for a
  fixed 5-25-second interior ACK statistic. Some large-message records are
  visibly transient/batched, so this field must not be interpreted as proof
  of stationary sustained capacity. variability-summary.json records separate
  descriptive diagnostics. Longer SDKPerf cross-validation is the next gate.

The mathematical companion in ../finance-dependence implements classical
sharp coupling bounds and a hypothetical finance example. It does not supply
an empirically calibrated trading strategy or a new inequality.

Status: research in progress. The captured pilot establishes a client-window
effect. It does not yet establish broker peak capacity or validate the model
proposed below. The engineering target is a reproducible market-data systems
study suitable for a public technical article and a hedge fund interview.

First measured result
---------------------

A native SMF publisher and separate queue consumer exchanged persistent
256-byte payloads on a disposable local Solace 10.26.9.13589 Standard broker.
The SDK's negotiated publish window stayed at 255. Only the application's
limit on outstanding messages changed. Each case admitted for 30 seconds,
then allowed outstanding messages to be acknowledged and consumed.

===================== ================ =============== =====================
Application limit     ACKed messages/s Mean ACK latency Publisher event-loop
===================== ================ =============== =====================
1                     0.997            1,002.690 ms    0.19%
64                    63.743           1,000.455 ms    0.79%
255                   5,790.176        41.259 ms       18.62%
===================== ================ =============== =====================

The rate denominator includes final acknowledgment drain time, not just the
30-second admission interval. This is an end-to-end pipeline rate. It is not
a steady-state broker peak estimate. All messages were acknowledged, received
once by the single consumer, matched by SEMP queue spooled-message counter
deltas, and drained to zero queue usage.

The deliberately small application limits underfilled the larger SDK window.
The approximately one-second ACK times are consistent with batched ACK/timer
behavior, but this pilot did not vary the broker's timer and threshold
independently. That mechanism is a hypothesis supported by the timing, not an
isolated causal estimate. A properly tuned small SDK window is a different
configuration and has not been measured here.

The 255-message case can still be limited by ACK credit circulation, broker
edition throttling, a data-plane thread, transport, storage, consumers or other
resources. Low publisher event-loop utilization alone does not establish
broker saturation. Solace documents a Standard Edition rate limit, which must
be treated separately from unrestricted hardware capacity.

Small candidate abstraction
---------------------------

For each source message, define size s, matching-queue count f, persistence
indicator p and feature indicators such as TLS or replay. Over an interval,
retain the measured work vector::

    w = (source messages,
         ingress accounted bytes,
         queue-copy messages,
         queue-copy bytes,
         persistent source messages,
         persistent source bytes).

The last two components can be omitted within a fixed persistent-only class.
Add a feature interaction only when experiments show it predicts a material
cost not explained by the existing components. Physical spool writes are a
separate resource: a message matching several queues is not necessarily stored
as several independent physical payload copies.

Hypothesis: within a fixed broker version, hardware tier, protocol, relevant
feature regime and stable resource state, each resource r has approximately
affine demand d_r(w)=b_r+theta_r dot w. Its usable budget is C_r. For a workload
with per-source-message mean work phi and offered source rate lambda::

    lambda_peak ~= min_r (C_r-b_r)/(theta_r dot phi).

This is a bottleneck/work-demand model, related to established operational
analysis and Roofline reasoning. It is not claimed as a new performance law.
The scientific question is whether a very small, measurable phi predicts
held-out Solace configurations accurately, and which regime changes defeat it.
An edition's enforced rate ceiling and the client's outstanding-credit
constraint must be included as additional limits.

Why separate means are insufficient: a concrete mathematical result
------------------------------------------------------------------

Even this simple abstraction requires joint work, not just mean size times
mean fanout. Consider two equally likely message classes and any K>1::

    Mix A: (size, fanout) = (1,1) or (K,K).
    Mix B: (size, fanout) = (1,K) or (K,1).

Both mixes have identical source rates, mean size (K+1)/2 and mean fanout
(K+1)/2. Their copy-byte demands per source message differ::

    E_A[size*fanout] = (K*K+1)/2
    E_B[size*fanout] = K
    ratio = (K*K+1)/(2*K).

For K=9 the ratio is 41/9, about 4.56. As K increases the ratio has no finite
universal upper bound. Therefore no estimator that sees only source rate,
mean size and mean fanout can uniquely identify copy-byte resource demand
over arbitrary message mixes. It must observe the joint moment, obtain an
equivalent egress/copy-byte counter, or make an explicit independence/bounded-
correlation assumption. This is an elementary independently derived
counterexample, not a claim of mathematical novelty.

Under an affine resource model, mixtures with the same mean feature vector
have the same predicted capacity: linearity of expectation gives
E[theta dot phi(X)] = theta dot E[phi(X)]. That conditional sufficiency is
exact for the model, not proof that the broker actually follows the model.

SEMP measurement requirements
-----------------------------

* Use cumulative counters with observed collection times and reset detection.
  Compare deltas to publisher successes and consumer deliveries. Do not treat
  a single current-rate sample or a one-minute average as a whole experiment.
* Queue spooled-message counter deltas measure retained queue-copy work.
  Aggregate only the queues participating in the workload and record topology.
* Validate the Message VPN's guaranteed-message ingress counter against source
  attempts and retransmissions before interpreting it as a unique-source count. In the public
  schema, msgSpoolRxMsgCount is described as guaranteed messages received.
* Preserve the distinction between ordinary txMsgCount, unique guaranteed
  transmissions and copies delivered. The documented msgSpoolTxMsgCount counts
  a message sent to multiple clients only once; it is not a copy counter.
* Root rxMsgCount/txMsgCount did not exactly match application payload counts
  in the pilot. Their scope and collection boundaries must be reconciled;
  dividing them blindly would produce a misleading fanout estimate.
* Poll queue monitor endpoints at intervals of at least 30 seconds. The pilot
  sampled only the global monitor endpoint every two seconds, with queue
  collections at case boundaries separated by at least 30 seconds.
* The tested SEMP v2 Broker schema has traffic counters but no CPU-utilization
  field. Two guessed SEMP v1 resource queries were rejected by the live schema;
  the replies are retained as unsupported, not converted into measurements.
  A schema-validated show/system/detail query reports resource configuration,
  not live CPU demand. Resource utilization still needs a documented supported
  endpoint or separately recorded host telemetry for validation.

Passive throughput counters alone cannot identify an unvisited saturation
boundary. Two systems may emit identical counters at the same low offered
load and differ arbitrarily in their unused capacity. Calibration, a controlled
load sweep, or additional justified resource information is required.

Experiment protocol to test the abstraction
------------------------------------------

1. Eliminate generator artifacts: vary application credit, actual SDK window,
   publisher-session count and consumer count separately. Record client CPU,
   event-loop utilization, ACK distributions, queue backlog and broker counters.
2. Measure size and fanout combinations in randomized order, initially using
   persistent messages and explicit consumer ACKs. Use several offered loads
   per combination, repeated runs, warm-up exclusion and a drain/accounting gate.
3. Separate sustained capacity from spool filling. A queue that grows throughout
   the test has not demonstrated a sustainable throughput, even if ingress ACKs
   remain fast. Define a latency/backlog SLO alongside the raw throughput peak.
4. Fit a nonnegative resource-demand model using only a declared training set.
   Evaluate completely held-out sizes, fanouts and mixed message distributions.
   Compare against constant messages/s, constant bytes/s, a size-only model and
   a naive product-of-means model. Report signed and absolute prediction errors.
5. Introduce TLS, topic matching complexity, replay and persistence regimes one
   at a time, then with a sparse interaction design. Record failures of the small
   model. Do not claim it spans feature combinations that were never tested.
6. Establish whether saturation is a software edition limit, a client/network
   constraint, or broker resource saturation. Standard Edition experiments do
   not identify unrestricted Enterprise hardware capacity.

Finance application and publication target
-----------------------------------------

Market-data message streams contain different event types and downstream
subscription patterns. A change in their joint mix can change infrastructure
work while leaving events/s and average payload size nearly unchanged. The
counterexample above explains a concrete failure mode of average-only headroom
dashboards. It is relevant to planning feed-handler, risk and strategy fanout
capacity, rather than a claim of a profitable signal or trading strategy.

A candidate technical article is ``When Message Rates Mislead: Predicting
Market-Data Infrastructure Headroom from Measured Work``. The eventual public
package should contain runnable experiments, raw telemetry, a small validated
model, out-of-sample errors, failure cases and a finance workload stress test.
The current pilot can support a narrowly framed engineering case study; it
cannot yet support the proposed peak-prediction claim.

For a quantitative developer application, emphasize reproducible systems work,
protocol knowledge, measurement discipline, mathematical modeling and honest
limits. For a quantitative researcher application, add an execution/latency
model with falsifiable empirical evaluation and stronger statistical design.
No job outcome or peer-reviewed novelty has been established. No article,
repository or application has been published or sent externally by this work.

Primary references
------------------

* Solace guaranteed-message publish windows and ACK correlation:
  https://docs.solace.com/API/API-Developer-Guide-JavaScript/JavaScript-API-Sending-Guaranteed-Messages.htm
* Official Solace Node.js API examples used to check API usage:
  https://github.com/SolaceSamples/solace-samples-nodejs/tree/master/src/basic-samples
* Solace performance tiers and Standard Edition rate limits:
  https://solace.com/blog/optimizing-performance-pubsub-event-broker/
* SEMP schema discovery and polling constraints:
  https://docs.solace.com/Admin/SEMP/SEMP-API-Ref.htm
  https://docs.solace.com/Admin/SEMP/SEMP-Features.htm
* Denning and Buzen, Operational Analysis of Queueing Networks:
  https://docs.lib.purdue.edu/cstech/165/
* Williams, Waterman and Patterson, Roofline:
  https://escholarship.org/uc/item/5tz795vq
* Nasdaq's primary market-data message specification:
  https://nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf
* Lehalle and Mounjid on latency and adverse selection (finance research
  context, not empirical support for this broker experiment):
  https://arxiv.org/abs/1610.00261
