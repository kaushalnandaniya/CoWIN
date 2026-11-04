# Failover Benchmarking & Evidence Collection Suite
## IT457 Course Project Testing Harness

**Assigned Responsibility:** **Darshil Gandhi** (Student ID: `202301056`) & **Jeetrajsinh Gohil** (Student ID: `202303017`)  
**Infrastructure Target:** AWS ALB provisioned by **Kaushal Nandaniya** (Student ID: `202303036`)  

---

### Description
This directory contains the testing harness, load generator, and local ALB proxy simulator for conducting the instance-stop failover demonstration specified in the Week 2 Progress Report (Section 4).

### Test Harness Components:
* `failover_benchmark.py`: Sends continuous client requests (10 req/s) through the ALB and records response latency, zone distribution, and failure transitions.
* `alb_simulator.py`: Multi-threaded local reverse-proxy simulating AWS ALB behavior for local dry-runs prior to live AWS testing.
* `run_experiment.sh`: Automated launcher script.
* `generate_plots.py`: Generates the terminal timeline visualizer for report evidence.
