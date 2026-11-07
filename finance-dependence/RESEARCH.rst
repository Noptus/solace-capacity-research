Dependence uncertainty in infrastructure and execution research
==============================================================

This is an applied mathematical companion to the Solace capacity study. It
implements a classical result from rearrangement/coupling theory and connects
it to two concrete diagnostics. It is not claimed as a new theorem, a calibrated
trading model or evidence of investment profitability.

Exact finite-marginal bounds
---------------------------

Let X and Y be nonnegative finite random variables. Their separate histograms
are known, but their dependence is not. Normalize each histogram to total
probability one. Let Q_X and Q_Y be their quantile functions. Then::

    integral_0^1 Q_X(u)*Q_Y(1-u) du
        <= E[X*Y]
        <= integral_0^1 Q_X(u)*Q_Y(u) du.

Both endpoints are attained by joint distributions with the supplied
marginals: pair the largest X values with the smallest Y values for the
minimum, and with the largest Y values for the maximum. The supplied program
merges the quantile steps in linear time after sorting and returns the actual
attaining joint distributions, using exact rational arithmetic.

For completeness, the finite exchange argument is simple. Let x1<=x2 and
y1<=y2. Moving probability mass delta from the off-diagonal pairs to the
aligned pairs preserves both marginals and changes the expected product by::

    delta * [(x1*y1+x2*y2)-(x1*y2+x2*y1)]
      = delta * (x2-x1)*(y2-y1) >= 0.

An optimal maximum can therefore be chosen without crossings; repeated
uncrossing gives the monotone quantile coupling. Reversing the order gives
the minimizing coupling. Finite step marginals avoid integrability issues.
This is the classical rearrangement bound, not a new proof of an open problem.

Application 1: broker capacity with unknown size/fanout dependence
----------------------------------------------------------------

Let X be accounted message size and Y its queue fanout. E[X*Y] is the mean
queue-copy byte demand. If both have equally weighted values 1 and 9,::

    minimum copy-byte demand = 9
    independent demand       = 25
    maximum copy-byte demand = 41.

For a hypothetical copy-byte processing budget C, the capacity implied by
this resource alone is between C/41 and C/9. An independence-based estimate
C/25 can overstate or understate that capacity substantially. The endpoints
are sharp given these marginals. A real broker also has other resource limits;
this is not a complete capacity interval for that broker.

This gives a useful alternative to pretending that missing dependence is
known: return an identified interval, or collect a joint/copy-byte counter
that shrinks it. Marginal histograms alone are not necessarily available from
SEMP; they must be measured, supplied as workload metadata, or bounded.
The accompanying broker experiments will test how much of actual service
demand is explained by copy-byte work versus other operations.

Application 2: signal magnitude and execution delay
--------------------------------------------------

Suppose, purely as a diagnostic model, A>=0 is a gross opportunity magnitude
in basis points and G in [0,1] is the fraction retained when execution occurs.
A possible model is G=exp(-kappa*L) for latency L, but neither kappa nor this
decay law is estimated in this example. With constant all-in cost c, define
the illustrative net quantity A*G-c. It omits fill uncertainty, inventory,
market impact dynamics, adverse selection and estimation error.

Take these deliberately hypothetical marginals::

    A: 0.5 or 2.0 basis points, each with probability 1/2
    G: 0.25 or 0.90, each with probability 1/2
    c: 0.60 basis points.

The exact results are::

    pessimistic coupling gross = 0.47500 bp; net = -0.12500 bp
    independence gross         = 0.71875 bp; net =  0.11875 bp
    optimistic coupling gross  = 0.96250 bp; net =  0.36250 bp.

The same separate opportunity and retained-value histograms admit either sign
for the net quantity. A positive independence estimate therefore does not
identify even its sign. For the adverse coupling, large opportunities arrive
with the smaller retention fraction, as might happen if busy market periods
coincide with larger processing delays. That explanation is a testable
mechanism, not an empirical finding from this illustrative example.

This application concerns a missing joint distribution, not an investment
recommendation or a claim that these basis-point values occur in any market.
Even complete latency measurements do not establish signal profitability.
The raw broker study measures publisher acknowledgment latency, which is not
exchange execution latency and must not be substituted for L in a trading
backtest.

An empirical finance extension needs timestamp-aligned, out-of-sample signal,
fill/cancel, latency and cost observations. It must guard against look-ahead,
selection on filled orders, clock skew, data revisions and multiple testing.
The joint model should be checked in stressed market periods as well as in
ordinary periods. Those data and an empirically calibrated trading result
are not present in the current package.

Run and inspect
---------------

Python 3.10+ is sufficient; there are no third-party dependencies::

    python3 -m unittest -v test_dependence.py
    python3 dependence.py finance-example.json
    python3 dependence.py broker-example.json

The output includes lower, independence and upper expectations, the net
versions after a constant cost, and both attaining joint distributions.
Seven tests check exact examples, witness marginals, invalid inputs, an
independent exhaustive permutation oracle and randomized interval properties.

Publication use
---------------

This can form the mathematical section of a reproducible research article
on misleading averages in market-data infrastructure. The empirical section
should use the actual Solace experiments, with a clear boundary between
measured systems behavior and the hypothetical finance diagnostic. A strong
portfolio contribution would be the validated cross-workload model, the
diagnostic software and explicit failure cases, rather than claiming novelty
for a classical inequality.

Prior art and primary research
------------------------------

* Puccetti and Wang, Extremal Dependence Concepts, Statistical Science (2015),
  authors' review of dependence uncertainty and rearrangements:
  https://arxiv.org/abs/1512.03232
  https://sas.uwaterloo.ca/~wang/papers/2015Puccetti-Wang-STS.pdf
* Lehalle and Mounjid, Limit Order Strategic Placement with Adverse Selection
  Risk and the Role of Latency. This supports the finance context, not the
  numerical parameters or decay law in the illustrative example:
  https://arxiv.org/abs/1610.00261
* The separate Solace study and recorded evidence are in ../broker-capacity.
