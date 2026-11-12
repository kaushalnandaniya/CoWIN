# Testing the Lookup Service and Benchmark

The service has a standard-library-only unit test suite in
`service/tests/test_app.py`. It starts the real service on an ephemeral
port and exercises the contract the load balancer and failover benchmark
rely on: health transitions, the centers lookup, the zone/instance
headers, error responses, malformed-input handling, behavior under
concurrent load during a forced failure, and clean shutdown.

The benchmark's failover detection logic has its own suite in
`benchmark/tests/test_failover_detection.py`. It drives `FailoverTracker`
with synthetic timestamps and covers survivor-zone convergence detection,
the failover-time vs disruption-window split, the graceful-eviction case
(zero failed requests but failover achieved) and re-balancing after
recovery.

## Running the tests

From the repository root:

```bash
make test
```

or without make:

```bash
python3 -m unittest discover -s service -v
python3 -m unittest discover -s benchmark -v
```

or directly:

```bash
python3 service/tests/test_app.py
python3 benchmark/tests/test_failover_detection.py
```

No pip install and no network access needed - everything is Python 3 stdlib.

## Verifying failover behavior end to end

```bash
make experiment   # ./benchmark/run_experiment.sh
```

This boots two service instances (Zone A + Zone B) plus the ALB simulator,
fails Zone A mid-benchmark and confirms requests converge on Zone B.
