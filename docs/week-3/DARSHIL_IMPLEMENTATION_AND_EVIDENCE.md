# Service, benchmark and evidence handoff

## Scope and contribution

This work builds on the service, simulator, benchmark and hardening already on
`main` at `de03a44`. It does not claim those earlier contributions as new work.
No full CoWIN platform is required: the course PoC is a redundant lookup service
across two zones behind a load balancer.

This contribution adds safe local/manual benchmarking, timestamped operator
events, isolated run artifacts, data-driven SVG graphs, a read-only deployment
verifier, and regression tests. The existing systemd/API implementation is reused.
No AWS resources were accessed, created, stopped, started or charged in preparing
this contribution. Deployment on two real EC2 instances and live video remain
unverified, not completed by this PR.

## Reproducible local evidence

A fresh 32-second localhost simulator experiment was run on November 13, 2026
at `2026-11-13T12:56:59.266615+00:00`, using two service instances and the local
ALB simulator. These figures describe this run only:

| Metric | Observed value |
| --- | --- |
| Requests | 320 successful / 320 total |
| Failed lookups | 0 |
| Achieved sample rate | 10.000 requests/s |
| Health degradation accepted | t=10.016 s |
| Successful survivor streak observed | t=12.123 s |
| Client convergence estimate | 2.11 s |
| Observed error span | 0.0 s |
| Health restoration accepted | t=22.037 s |
| Recovered node observed again | t=24.043 s |
| Latency p50 / p95 / p99 | 2.07 / 2.67 / 3.32 ms |

Artifacts in this directory:
- `DARSHIL_LOCAL_REQUESTS.csv`: all 320 raw request samples.
- `DARSHIL_LOCAL_RESULTS.json`: metadata, metrics, actual event markers and limits.
- `DARSHIL_LOCAL_TIMELINE.svg`: latency/routing graph generated from those artifacts.

Run `make test` and follow `benchmark/README.md` to reproduce. Machine scheduling,
ports and network conditions change results. Do not copy these numbers into an
AWS-results section. Zero failed samples does not rule out a shorter disruption
between samples. The local test degrades health while lookup requests continue;
it is not a host crash or EC2 stop.

## Live AWS demonstration checklist (not yet collected here)

Coordinate these steps with Kaushal before running the test. Do not deploy or
stop resources merely because this checklist exists; obtain approval for the
specific account, budget, window and rollback owner.

- [ ] Verify the account/region, existing stack and final cost/teardown plan.
- [ ] Verify EC2 instances in two different AZs, approved service version,
      systemd health and security-group boundaries.
- [ ] Save a timestamped target-health snapshot showing both targets healthy.
- [ ] Run the read-only deployment verifier and retain its output.
- [ ] Start screen recording and continuous client sampling in manual AWS mode.
- [ ] Retain a baseline that actually shows both zones.
- [ ] Infrastructure lead issues the approved stop of the correct Zone A node.
      Record command acceptance immediately using `record_event.py`; retain the
      command output and actual EC2/ALB state transition timestamps separately.
- [ ] Keep sampling through failover. Retain unhealthy-target evidence and
      surviving-node routing, including errors rather than deleting them.
- [ ] Infrastructure lead restores the node within the agreed window; record
      the recovery marker and observe both target health and returned traffic.
- [ ] Generate graphs from this AWS run's own CSV/JSON. Label the experiment and
      units; explain sampling/streak uncertainty and any partial run.
- [ ] Save the unedited video, health snapshots and client artifacts with matching
      timestamps. Confirm restoration and teardown with the infrastructure lead.

The failure event is command acceptance, so the measured interval includes stop
latency. Client streak timing is not the same as health-check detection latency.
Compute health-check detection from the separately captured AWS state timestamps.
The read-only workload does not establish database replication RPO.

## Report appendix and viva preparation

Contribute the API contract, deployment verification, workload configuration,
raw logs, latency percentiles, routing graph and failure/recovery timeline to the
final report. Link actual evidence, distinguish measured values from architectural
claims, and state what could not be measured. The report lead owns compilation.

Be ready to explain:
- Why `/health` can fail while the lookup API still serves traffic locally.
- Why an EC2 stop can behave differently from health-only simulation.
- How ALB target-health thresholds, request timeout and sample rate affect delay.
- Why zero error span with one failed request is not zero interruption.
- Why five survivor responses are an estimate, not guaranteed complete failover.
- Why local millisecond latency cannot be used as AWS latency evidence.
- How systemd supervises the service and the role of response identity headers.
- Why RPO is not measured by this lookup benchmark.

## Remaining evidence boundary

The implementable service/testing tooling and local dry run are prepared. Live
AWS deployment verification, authorized instance-stop/restart, health snapshots,
video capture, and integration into the team's final report/viva are still tasks
for the team to confirm. This document does not claim those tasks were absent in
any other teammate's work; they were simply not verified during this contribution.
