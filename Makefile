# CoWIN Two-Zone Failover PoC - common tasks
#
#   make test        Run the service unit test suite (stdlib unittest only)
#   make experiment  Run the full local two-zone failover benchmark

.PHONY: test experiment

test:
	python3 -m unittest discover -s service -v

experiment:
	./benchmark/run_experiment.sh
