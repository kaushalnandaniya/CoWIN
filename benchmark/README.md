# Failover benchmarking and evidence

Darshil's service/testing contribution builds on the existing API, simulator,
benchmark and test suites. Python 3 standard library only; curl and bash are
needed by the local launcher. No AWS SDK or cloud account is needed locally.

## Local dry run

```bash
make test
RUN_DIR=/tmp/cowin-demo ./benchmark/run_experiment.sh
python3 benchmark/generate_plots.py --run-dir /tmp/cowin-demo
```

Choose a fresh `RUN_DIR` for every run. Without it, the launcher prints a new
`/tmp/cowin-run.*` directory. Override `ALB_PORT`, `ZONE_A_PORT`, and `ZONE_B_PORT`
if needed. Each node gets a separate SQLite database; logs are kept under the
run directory. Cleanup stops and waits for only processes started by this run.
The original committed result files are never overwritten.

The 32-second test samples at up to 10 requests/second, degrades Zone A's
health after 10 seconds and restores it after 22 seconds. Those are scheduled
injection targets, not promised detection times. The JSON records actual events.
`COWIN_API_KEY`, when configured, is sent to local injection endpoints without
putting the key in command-line arguments or result files.

## AWS client sampling (no resource changes)

First arrange the deployment, budget, stop/start permission, screen recording,
and target-health capture with the infrastructure lead. This client never calls
AWS APIs and automatic injection is limited to loopback simulator addresses.

```bash
# Set ALB_URL to the verified deployed ALB URL, including its port.
python3 service/verify_deployment.py --url "$ALB_URL"
python3 benchmark/failover_benchmark.py --url "$ALB_URL" \
  --environment aws --no-auto-fail --failed-zone ap-south-1a \
  --duration 90 --rps 10 --events-file /tmp/cowin-live/events.jsonl \
  --output-dir /tmp/cowin-live
```

In another terminal, immediately AFTER the authorized stop command succeeds:

```bash
python3 benchmark/record_event.py --output /tmp/cowin-live/events.jsonl \
  --event failure --note 'Zone A stop command accepted; health capture recorded separately'
```

Record `--event recovery` after the authorized start command succeeds. These
markers mean command acceptance, not proof of an EC2 state or an ALB transition.
Record those states and their timestamps separately. Never label a local run as
AWS evidence. Never run an instance-stop test without the team's authorization.

## Outputs and interpretation

- `benchmark_requests.csv`: UTC/epoch timestamps, elapsed time, HTTP status (blank
  for transport errors), success, latency, zone, instance identity and error.
- `benchmark_results.json`: environment, achieved/requested rate, latency
  percentiles, distribution, injection/observation events and limitations.
- `latency_timeline.svg`: portable latency and routing graph, with event markers
  taken from the JSON rather than invented times. Red samples mean any failed
  lookup, not only HTTP 5xx.

This is a sequential sampler, not a stress generator. Slow requests lower the
achieved rate; there are no catch-up bursts. Duration is wall-clock bounded,
though a final request/read can add up to its timeout. Latency uses a monotonic
performance clock, UTC timestamps use the system clock; keep clocks synchronized
for external event correlation.

Five consecutive successful responses from a non-failed zone estimate client
convergence only after an observed two-zone baseline. The tracker clears old
history at injection and will not infer failover after recovery already began.
Real ALB routing need not alternate, so a streak alone is not proof of target
health, complete traffic convergence, or a guaranteed RTO. Correlate with AWS
health snapshots and report the sampling/convergence-window uncertainty.

`disruption_window_seconds` is the span between first and last failed samples
after injection. A single error has a zero span, NOT zero interruption. Use the
failure count and `stable_service_resumption_seconds` alongside it. The latter
measures first error to five successful survivor samples; null means it was not
observed. No errors means zero *observed* disruption, not proof that none occurred
between samples. RPO is not measured by a read-only lookup workload.

Malformed/nonpositive settings and unsafe remote auto-injection fail before
requests are sent. Exit 2 indicates an injection error; exit 3 means an event was
recorded but a valid two-zone failover was not observed. A manual baseline run
without events can exit 0 without claiming any failover. Partial CSV rows are
flushed; a missing summary after interruption is not a completed run.
