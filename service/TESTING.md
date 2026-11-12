# Testing the Lookup Service

The service has a standard-library-only unit test suite in
`service/tests/test_app.py`. It starts the real service on an ephemeral
port and exercises the contract the load balancer and failover benchmark
rely on: health transitions, the centers lookup, the zone/instance
headers, error responses and clean shutdown.

## Running the tests

From the repository root:

```bash
make test
```

or without make:

```bash
python3 -m unittest discover -s service -v
```

or directly:

```bash
python3 service/tests/test_app.py
```

No pip install and no network access needed - everything is Python 3 stdlib.

## Verifying failover behavior end to end

```bash
make experiment   # ./benchmark/run_experiment.sh
```

This boots two service instances (Zone A + Zone B) plus the ALB simulator,
fails Zone A mid-benchmark and confirms requests converge on Zone B.
