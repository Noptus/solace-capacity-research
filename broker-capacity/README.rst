Solace capacity research: first probe
====================================

The current package also contains a completed twenty-case controlled study.
The initial simple models missed both held-out cases by about 29-31%; they
are not validated peak predictors. See the latest-results section in STUDY.rst
and ../research-draft.pdf. The pilot below remains separately reproducible.

Audit the new evidence without Docker::

    python3 audit_study.py matrix-evidence
    python3 audit_study.py replication-evidence
    python3 audit_study.py cache-window-evidence
    python3 fit_model.py matrix-evidence

Reproduce a new matrix from the original workspace root::

    python3 outputs/broker-capacity/run_matrix.py --output work/reproduced-matrix

The runner refuses to overwrite an existing study. It supports an explicit
additional --design-file for exploratory controls; prior declared holdouts
are preserved. Read the accounting, retry, stationarity and scope caveats in
STUDY.rst before interpreting any rate as broker capacity.

Read STUDY.rst for measured pilot results, the proposed work-vector model,
a mathematical counterexample to separate-mean predictors, the finance
application and the remaining validation requirements.

The pilot uses persistent SMF publication, a separate consumer process,
application credit limits of 1/64/255, fixed 256-byte payloads and one queue.
It verifies publisher ACKs, consumer counts, SEMP queue counter deltas and
complete drain. It does not establish broker peak capacity.

Requirements: Python 3.10+, Node.js, Docker, and the ARM64 Solace image pinned
in capacity_probe.py's imported IMAGE constant. Three localhost ports must
be available: 18080, 15555 and 15550. The broker uses a 3 GiB memory limit,
a two-CPU quota and 1 GiB shared memory. Source and consumer run on the host.

From the original workspace root, reproduce with::

    npm install --prefix work/capacity-node --ignore-scripts --no-audit --no-fund --save-exact solclientjs@10.18.3
    python3 outputs/broker-capacity/capacity_probe.py

If the image is absent, obtain the digest used by the existing live lab in
outputs/spoolguard/live_lab.py. The probe imports its Broker and Docker helpers;
retain the two sibling folders together. It does not download images itself.
Each run creates and removes a localhost-only disposable container; the image
remains cached. The SDK is installed separately and is not redistributed here.

Raw records are in pilot-evidence/probe-results.json. Legacy XML replies show
which resource queries were supported or rejected on the tested schema.
The original npm package manifest and lockfile are included for reproducibility.

Next: reconcile guaranteed-source counters, vary actual SDK windows and session
counts, then run held-out message-size/fanout and mixed-workload experiments.
No peak predictor is claimed validated at this stage.
