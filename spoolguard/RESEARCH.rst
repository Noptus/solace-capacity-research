Finite-horizon admission under stale telemetry and fanout
=======================================================

Research status: a derived application of established network calculus and
weighted max-min allocation. No claim of a new mathematical discovery,
publication-level novelty or production readiness. The zero-service case
has now been exercised on a real disposable Solace broker; see
LIVE-RESULTS.rst and the saved evidence for that limited empirical result.

Model
-----

Let i index queues and j index publisher classes. The routing matrix a_ij >= 0
upper-bounds queue-accounted bytes generated per source byte. A class must
have uniform routing or use a conservative upper bound for all of its messages.
The topology and capacities remain fixed for the certified interval.

Publisher j enforces a token-bucket arrival envelope b_j + x_j*u at the QUEUE
for every interval of duration u, with x_j >= 0. Future background traffic has
envelope b_i^bg + g_i*u. Packetization, delayed transit, retries, duplicate
messages and header/accounting expansion belong in these bounds.

At decision time the queue observation q_i is at most d_i seconds old. Rate
enforcement completes within l_i seconds. Until then, aggregate traffic has
an upper envelope b_i^old + r_i^old*u. Measurement uncertainty is at most e_i
bytes; additional residual in-flight traffic is at most f_i bytes. A valid
conservative bound at full activation, without crediting any release, is::

    Q_i = q_i + e_i + f_i + b_i^old + r_i^old*(d_i + l_i).

Double-counting residual traffic is safe but conservative. Missing traffic is
unsafe. Treating residual traffic as an additive reservation also covers its
late arrival; do not subtract service from this reservation before it arrives.

The protected capacity is K_i = C_i - reserve_i. The total future burst is
B_i = b_i^bg + sum_j a_ij*b_j and future rate is
R_i = g_i + sum_j a_ij*x_j.

Release provides a strict rate-latency service curve::

    beta_i(u) = mu_i * max(u - T_i, 0).

This means every continuously backlogged interval of duration u releases at
least beta_i(u) bytes. Service must release the very resource counted in Q_i;
transmission without consumer acknowledgment does not establish that property.
If the service guarantee is unavailable, use mu_i = 0. A service curve cannot
be established from a single observed average rate.

The horizon H > 0 starts at full enforcement. Service and arrival assumptions
must hold on all relevant intervals within this horizon. A positive T_i also
accounts for any guaranteed upper bound on initial/recurrent service stalls.

Conditional queue bound
-----------------------

For every 0 <= u <= H, queue occupancy is bounded by::

    q_i(u) <= Q_i + B_i + max_{0 <= v <= u} [R_i*v - beta_i(v)].

Proof: consider the busy period containing u. If it began after activation,
arrivals during that busy period obey B_i+R_i*v and strict service releases at
least beta_i(v). If it spans activation, add initial occupancy Q_i to that
bound. Residual delayed old traffic has total volume at most its reservation
and can conservatively be added without service credit. Taking the supremum
over possible busy-period lengths yields the inequality. All terms are
nonnegative, so using the same Q_i for both cases is conservative.

The expression inside the maximum is piecewise linear, with its only change
of slope at T_i. Therefore its supremum on [0,H] is::

    G_i(R_i) = max(0,
                   R_i*min(T_i,H),
                   R_i*H - mu_i*max(H-T_i,0)).

It suffices to require Q_i+B_i+G_i(R_i) <= K_i for every queue.
This protects the entire interval, including the instantaneous burst and an
early peak during a service stall, rather than checking only the endpoint.

Closed-form rate cap
--------------------

Define headroom h_i = K_i-Q_i-B_i. If h_i < 0 there is no certificate for the
given burst envelope, even if controlled continuous rates are set to zero.
For h_i >= 0 the inequality is exactly equivalent to::

    R_i <= c_i

    c_i = (h_i + mu_i*max(H-T_i,0))/H                       if T_i = 0
    c_i = min(h_i/min(T_i,H),
              (h_i + mu_i*max(H-T_i,0))/H)                if T_i > 0.

The equivalence follows by solving each nonnegative linear peak term against
h_i. Thus the nonlinear-looking queue condition reduces to a nonnegative
linear resource constraint on publisher rates::

    sum_j a_ij*x_j <= c_i - g_i.

When mu_i=0, the formula becomes c_i=h_i/H: finite buffer headroom provides a
temporary admission budget even during a complete consumer outage.
When T_i=0 and mu_i>0, c_i=mu_i+h_i/H: finite-horizon admission may exceed
the guaranteed release rate. That excess cannot continue indefinitely.
When T_i>=H, no service credit is available within the horizon.

The inversion is exact for this sufficient bound; that does not establish
necessity for a real broker with richer state and correlated traffic.
Within the abstract model, full initial bursts and a minimal rate-latency
server can attain the bound in important cases. Independent bursts may be
more conservative than the actual publisher correlations.

From source shaping to a queue-arrival envelope
----------------------------------------------

The theorem assumes an envelope at the queue; shaping source sends alone is
not sufficient if transport can arbitrarily delay and bunch a large number
of outstanding messages. A bounded-outstanding-byte condition bridges this
gap without requiring a bound on transport latency.

Let S(t) be cumulative source-admitted payload bytes and U(t) be cumulative
payload bytes processed by the broker, including messages it rejects. Assume
causality, no unaccounted transport duplication, and 0 <= S(t)-U(t) <= W.
For every interval (s,t], of duration u,::

    U(t)-U(s) <= S(t)-S(s)+W <= B+R*u+W.

Proof: U(t)<=S(t), and U(s)>=S(s)-W. Subtract and apply the source envelope.
Messages actually retained by a queue form a subset of the processed arrivals,
so this also bounds ingress contributing to queue occupancy. A conservative
byte-expansion coefficient converts payload into accounted queue bytes.

The live REST publisher waits for every HTTP response before admitting its
next fixed-size message. With no automatic retry, W is at most one payload
message per stream: a response confirms that the preceding message was
processed. The source burst is two messages; the planner reserves three
messages per stream at the queue. The exact nanosecond token bucket ceases
admitting at expiry, while the extra W also reserves a late final message.
For multiple concurrent outstanding requests, W must increase accordingly.

This lemma is a direct conservation argument. It is useful for implementing
the assumptions of the certificate; it is not presented as a new theorem in
network calculus. Arbitrary SDK retries or duplicate delivery require a
separate bound and are absent from the live experiment.

Fanout allocation
-----------------

The planner solves weighted max-min allocation under the constraints above
and 0 <= x_j <= demand_j. It starts at zero, increases active rates at speed
weight_j, then freezes publishers at their demand limits or at a saturated
queue they use. Every iteration freezes at least one publisher, so there are
at most n iterations for n publisher classes.

Feasibility follows because each step stops at the first active constraint.
For weighted max-min fairness, consider a publisher frozen by a saturated
queue at normalized rate x_j/weight_j. All other users of that queue froze at
an earlier normalized level or freeze at that same level. Increasing x_j
requires reducing a user at an equal or lower normalized rate. A publisher
frozen at demand cannot increase within the feasible demand set. This is the
weighted max-min property. The allocation need not maximize total throughput
or weighted log utility, and it does not enforce latency or critical-traffic
minimum rates.

Exact fractions avoid rounding a computed rate above a constraint. They do
not remove uncertainty in a measured quantity or an incorrect traffic model.
The simple implementation favors reviewability over scale; rational sizes
and the dense routing matrix may become expensive on very large deployments.

Why global throttling can be arbitrarily wasteful
------------------------------------------------

Consider one publisher with demand D going to a constrained queue whose
admissible rate is epsilon*D, and m independent publishers each with demand D
going to unconstrained queues. A uniform global multiplier admits
(m+1)*epsilon*D. Routing-aware admission permits (m+epsilon)*D.
The ratio is (m+epsilon)/((m+1)*epsilon), which has no finite universal bound
as epsilon approaches zero with m >= 1 fixed. This is a simple structural
counterexample to treating all publishers as one shared rate limit; it is
not claimed as a new fairness or networking theorem.

What an observation cannot prove
-------------------------------

An instantaneous ingress measurement does not bound future arrivals. An
instantaneous egress measurement does not bound future spool release. If
future arrivals may be arbitrarily large before another observation or an
actuation completes, finite free capacity cannot guarantee safety. Choose
an allowed burst larger than the free capacity as a counterexample.

Consequently the certainty in this prototype comes from enforceable or
otherwise justified contracts, not from extrapolating telemetry. Setting
mu_i=0 removes an unjustified service assumption, but does not eliminate the
need for arrival bounds, complete routing and sufficient residual capacity.

Validation and open research
----------------------------

The tests cover boundary cases, stale observations, bursts, background traffic,
service latency, route expansion, fairness, malformed inputs and SEMP import.
Randomized checks use fixed seeds: 2,000 inverse-bound cases, 1,000 allocation
networks, and 500 independent token-bucket queue trajectories. These support
the implementation; the conditional mathematical claim rests on the proof.

experiment.py remains a synthetic zero-service outage using a topology chosen
to expose the isolation benefit. live_lab.py additionally exercises persistent
REST publication on Solace 10.26.9.13589, records actual ACK/rejection outcomes
and quota usage, and applies contract expiry in source shapers. These runs
provide no evidence of expected production gain, positive service guarantees,
end-to-end processing latency, or CPU/disk capacity under sustained load.

audit_live.py is independent of the planner and shaper implementation. It
checks every inclusive interval of each source event trace using prefix sums,
the expiry timestamp, one outstanding request per stream, raw broker counts,
and separately recomputed queue bounds. Mutation tests require that altered
rate traces, expiry times, fanout counts and queue peaks be detected. This is
an internal evidence-consistency audit; the local records are not externally
authenticated or a proof that instrumentation captured all possible clients.

Promising work beyond this prototype includes learning conservative bounds
with quantified assumption violations, correlated fanout/physical-spool
accounting, publisher-side enforcement with contract expiry, and a careful
comparison against existing admission-control and broker-monitoring systems.
A targeted literature review and live controlled experiments are prerequisites
to claiming a breakthrough.

Established foundation: Le Boudec and Thiran, Network Calculus, Springer
LNCS 2050, https://leboudec.github.io/netcal/ . The finite-horizon specialization
and its integration here are independently derived applications of that
framework, not a demonstrated extension of the theory.
