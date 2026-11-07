SDKPerf crosscheck: measured results
====================================

6 integrity-accepted cases; 1,804,560 source messages and matching consumer receipts.

Requested rate is not achieved throughput. All cases request 60 seconds of
messages, but backpressured fixed-count publishers can take longer.
The measured interior SEMP statistic spans samples between 10 and 50 seconds.

* sdk-0-256-4000: target 4,000/s; measured 3,999.40/s; tracking passes; max sampled queue 0.99 MiB.
* sdk-1-256-8000: target 8,000/s; measured 5,118.57/s; tracking fails; max sampled queue 16.25 MiB.
* sdk-2-256-9500: target 9,500/s; measured 5,890.75/s; tracking fails; max sampled queue 0.39 MiB.
* sdk-3-32768-500: target 500/s; measured 499.95/s; tracking passes; max sampled queue 4.72 MiB.
* followup-0-256-8000: target 8,000/s; measured 5,887.53/s; tracking fails; max sampled queue 0.58 MiB.
* followup-1-131072-76: target 76/s; measured 76.03/s; tracking passes; max sampled queue 14.00 MiB.

Tracking requires ingress within 5% of the target and queue-byte OLS growth
no greater than 2% of offered payload bytes/s. It is an operational diagnostic,
not a statistical stationarity proof. Green/accepted never means peak.

Study terminal states
---------------------

* sdkperf-validated-evidence: stopped on a retained failure; 4 accepted cases.
* sdkperf-followup-evidence: stopped on a retained failure; 2 accepted cases.
* sdkperf-drain-evidence: stopped on a retained failure; 0 accepted cases.

The first corrected design stopped at a 32 KiB / 1000/s quota overload.
The follow-up stopped at an unresolved 128 KiB / 152/s completion tail.
The separate 60-second drain control ACKed/received all 9120 with CRC/order
checks but recorded 9344 ingress attempts. The 224-attempt surplus is
consistent with retries, not directly identified by an SDK retry counter.
It remains excluded from the zero-surplus clean-calibration set.
The earlier same-stream sequence-check setup failure is also retained.
None of those failed records is silently included as clean calibration.

Interpretation
--------------

SDKPerf independently reproduces higher-load limitations in this local setup.
It does not prove a broker-only bottleneck. Different tool versions, metadata,
rate control, ACK timeouts, quotas and end delays preclude a matched causal
comparison with the Node.js study. Standard-edition limits and one Docker
environment do not identify unrestricted Enterprise performance.

See SDKPERF-SETUP.rst for reproduction and SEMP-WORK-VECTOR.rst for the compact
traffic abstraction, SEMP v1 CPU discovery, and counter semantics under overload.

The next scientific gate remains calibrated resource/service constraints and
longer randomized stability checks across new features, sizes and fanouts.
