# CoWIN Two-Zone Failover PoC - common tasks
#
#   make test        Run all unit test suites (stdlib unittest only):
#                    service tests + benchmark failover-detection tests
#   make experiment  Run the full local two-zone failover benchmark

.PHONY: test experiment

test:
	python3 -m unittest discover -s service -v
	python3 -m unittest discover -s benchmark -v

experiment:
	./benchmark/run_experiment.sh
