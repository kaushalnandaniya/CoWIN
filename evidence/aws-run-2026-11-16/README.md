# Real AWS failover run, 2026-11-16 (ap-south-1)

Evidence pack for the Week 3 report's failover tables (Tables 4-5): a real
EC2 stop/start failover test against the two-zone CloudFormation deployment,
sampled through the public ALB. Zone A instance `i-01771ef8ebcfed694`
(ap-south-1a) was stopped at 10:38:28 IST and restarted at 10:39:40 IST;
the Zone B instance `i-062eaaf2092db6141` (ap-south-1b) served the survivor
window. All times IST (UTC+5:30).

## Files

| File | Contents |
| --- | --- |
| `aws-failover-requests.csv` | All 333 raw client request samples: UTC/epoch timestamps, phase, HTTP status, success flag, latency, serving zone and instance ID, error. |
| `aws-failover-results.json` | Per-phase aggregates (counts, statuses, zone split, latency percentiles), event milestones and stated limitations. |
| `aws-failover-timeline.jsonl` | Independent AWS-side timeline: EC2 state transitions and ALB target-health descriptions captured through the AWS API, plus sampling-window and stop/start acceptance markers. |
| `aws-failover-evidence.pdf` | Narrative summary with the key timestamps and original application screenshots captured during the run. |

## Headline results (from `aws-failover-results.json`)

| Phase | Requests | OK | Errors | Notes |
| --- | ---: | ---: | ---: | --- |
| Baseline | 69 | 69 | 0 | Split A 35 / B 34; p50 477.8 ms |
| Stop (Zone A stopping) | 38 | 28 | 10 | 9 HTTP 502 + 1 client timeout during convergence |
| Survivor (Zone A stopped) | 69 | 69 | 0 | 100% Zone B |
| Start (Zone A pending) | 89 | 89 | 0 | Zone B still serving |
| Final (both healthy) | 68 | 68 | 0 | Rebalanced A 33 / B 35 |
| **Total** | **333** | **323** | **10** | **96.997% successful** |

Key timings: stop accepted 10:38:28.552; first captured ALB-unhealthy for
Zone A 10:38:40.258 (~12 s, bounded by polling); first-to-last failed sample
span 9.742 s; first error to resumed successful samples 10.223 s; both ALB
targets captured healthy again at 10:40:20.304 after the 10:39:40.800 start.

This was not zero downtime: 10 client-visible errors occurred while the ALB
detected the stopped target and drained it. That is the expected behavior of
health-check-based failover, and it is what the report tables claim.

## Limitations (verbatim from the results file)

- Sampling ran in separate bounded windows; gaps between phases are not
  monitored. This is not continuous uptime evidence.
- Sequential sampler: 5 requests/second is an upper bound, not achieved
  throughput.
- 2-second timeout is a client timeout; timed-out requests might have
  completed later.
- Failover is an instance stop in one AZ, not a whole-AZ or region outage.
- Read-only sample dataset: database replication and RPO were not tested.
- Screenshots and AWS API captures are evidence; no continuous video was
  recorded by this test.
- AWS health transitions are bounded by polling, not exact internal event
  times.
