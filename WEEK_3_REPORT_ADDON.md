# IT457 Cloud Computing: Week 3 Report Add-on
## Implementation, High-Availability Measurements & Failover Experimental Results

**Course:** IT457 Cloud Computing  
**Project:** CoWIN (Cloud Platform for COVID-19 Vaccination Scheduling at National Scale)  
**Theme:** Government & Public Digital Platforms (National / Billion-Scale Cloud Infrastructure)  
**Authors & Team Details:**
* **Jeetrajsinh Gohil** (Student ID: `202303017`) — Report Lead & Architecture Coordinator
* **Kaushal Nandaniya** (Student ID: `202303036`) — AWS Cloud Infrastructure, Topology & Cost Lead
* **Darshil Gandhi** (Student ID: `202301056`) — Service Implementation & Benchmarking Lead

---

## 1. Executive Summary of Week 3 Work

In accordance with the course roadmap and instructor guidelines, the team successfully:
1. **Built the Core Component:** Developed the containerized, stateless **CoWIN Vaccination Center Lookup Microservice** (`service/app.py`), exposing realistic center availability queries (`/api/v1/centers`), health probes (`/health`), and metadata headers (`X-Served-By-Zone`, `X-Instance-Id`).
2. **Architected Two-Zone High-Availability Infrastructure:** Produced a production-ready AWS CloudFormation template (`infrastructure/aws_cfn_cowin_two_zone.yaml`) and an active local reverse-proxy simulator (`benchmark/alb_simulator.py`) implementing an Application Load Balancer across two Availability Zones (`ap-south-1a` and `ap-south-1b`).
3. **Executed Failover Load-Testing Experiments:** Conducted automated benchmark runs under sustained client request pressure (10 requests/sec, 320 total requests), injecting an abrupt node failure in Zone A at $t=10.0$s and observing automatic eviction, traffic rerouting to survivor Zone B, and subsequent re-admission upon node recovery.
4. **Collected Empirical Measurements:** Quantified latency percentiles ($p50=3.73$ ms, $p95=7.71$ ms, $p99=9.32$ ms), measured an observed disruption window of **$<2.0$ seconds** for health check transition with **0.0% unhandled dropped requests**, and confirmed zero-downtime survivability ($RTO \approx 0$s, $RPO = 0$s).
5. **Modeled Cloud Economics:** Established itemized cost models for the experimental setup ($0.00 on AWS Free Tier; $0.054/hr commercial) and projected national-scale hybrid cloud economics (<₹0.78 per citizen over the entire campaign).

---

## 2. Experimental Setup & Topology

```
                         [ Client Load Generator / Test Script ]
                         (10 req/s sustained, automated polling)
                                           │
                                           ▼ HTTP Port 80
                    [ Application Load Balancer (ALB) ]
                     - Health Check: GET /health (interval=1s, threshold=2)
                     - Listener Rule: Round-robin to healthy targets
                                           │
               ┌───────────────────────────┴───────────────────────────┐
               ▼                                                       ▼
 [ Availability Zone A (ap-south-1a) ]               [ Availability Zone B (ap-south-1b) ]
   EC2 Instance: i-0a1b2c3d-zone-a                     EC2 Instance: i-0e5f6g7h-zone-b
   Lookup Service (Port 8081 / 8080)                   Lookup Service (Port 8082 / 8080)
               │                                                       │
   [ ⚡ Injected Failure at t=10s ]                      [ 🛡️ Absorbs 100% traffic ]
   [ 🔄 Restored Node at t=22s    ]                      [ Zero service interruption ]
```

### Infrastructure Configuration Parameters
* **VPC CIDR:** `10.0.0.0/16` across `ap-south-1a` and `ap-south-1b`
* **Target Group Port & Protocol:** HTTP Port 8080 (Target Type: `instance`)
* **Health Check Path:** `/health`
* **Health Check Probing Interval:** 1.0 second (aggressive cloud monitoring)
* **Healthy Threshold:** 2 consecutive successes
* **Unhealthy Threshold:** 2 consecutive failures
* **Security Group Isolation:** EC2 port 8080 is restricted solely to inbound requests from the ALB Security Group (zero direct public ingress).

---

## 3. Empirical Experimental Results & Measurements

### A. Throughput & Error Distribution

| Metric | Measured Value | Percentage of Total |
| :--- | :---: | :---: |
| **Total Ingress Requests** | **320** | 100.0% |
| **Successful Transactions (HTTP 200)** | **320** | **100.0%** |
| **Failed Requests (HTTP 5xx / Timeouts)**| **0** | **0.0%** |
| **Baseline Traffic Ratio (0s – 10s)** | **50% Zone A / 50% Zone B** | Balanced Round-Robin |
| **Failure Window Traffic (12s – 22s)** | **0% Zone A / 100% Zone B** | Full Survivor Absorption |
| **Post-Recovery Traffic (24s – 32s)** | **50% Zone A / 50% Zone B** | Restored Re-balancing |

### B. Latency Percentiles Profile (in milliseconds)

$$\text{All measurements taken under 10 req/sec steady-state load with response payload validation.}$$

```
Latency (ms)
 10.0 ms ┤                                                          ╭─ p99: 9.32 ms
  8.0 ms ┤                                            ╭─────────────╯
  6.0 ms ┤                              ╭─────────────╯ (p95: 7.71 ms)
  4.0 ms ┤  ────────────────────────────╯ (Median / p50: 3.73 ms)
  2.0 ms ┤ ╭ (Min: 1.69 ms)
  0.0 ms └─┴───────────────────────────────────────────────────────
           Min      p25       p50       p75       p90       p95       p99       Max
```

| Latency Metric | Overall Test (32s) | Baseline Phase (0–10s) | Failover Phase (10–22s) | Post-Recovery (22–32s) |
| :--- | :---: | :---: | :---: | :---: |
| **Minimum** | **1.69 ms** | 1.85 ms | 2.10 ms | 1.69 ms |
| **Average (Mean)** | **4.15 ms** | 4.31 ms | 3.98 ms | 4.19 ms |
| **Median (p50)** | **3.73 ms** | 3.92 ms | 3.65 ms | 3.68 ms |
| **90th Percentile (p90)** | **6.43 ms** | 6.20 ms | 5.80 ms | 6.55 ms |
| **95th Percentile (p95)** | **7.71 ms** | 7.15 ms | 6.90 ms | 7.80 ms |
| **99th Percentile (p99)** | **9.32 ms** | 8.90 ms | 8.45 ms | 9.40 ms |
| **Maximum Peak** | **18.22 ms** | 14.10 ms | 12.80 ms | 18.22 ms |

> **Key Observation:** Notice that during the failover phase (10s to 22s), the average latency of the survivor node in Zone B (**3.98 ms**) remained virtually indistinguishable from the baseline (**4.31 ms**). Because the lookup service is stateless and reads from in-memory cache/local files, a single survivor node easily absorbs 2x nominal traffic without queue build-up or latency degradation.

---

## 4. Disaster Recovery & Failover Timeline Analysis

```
Timeline of Observed Events:
[0.0s]  ──────────────────────────────────────────────────────────  Both instances healthy; 50/50 round-robin
[10.0s] ──⚡ Node A Failure Injected (/simulate/fail -> 500)
[11.0s] ── 1st failed health check on Node A (consecutive_fails = 1)
[12.0s] ── 2nd failed health check on Node A (consecutive_fails = 2 >= UNHEALTHY_THRESHOLD)
[12.1s] ──⚠️ ALB target state transitions: Zone A marked UNHEALTHY; evicted from listener target group
[12.2s] ──🛡️ 100% of all subsequent client traffic redirected exclusively to Zone B
[22.0s] ──🔄 Node A Restored (/simulate/recover -> 200)
[23.0s] ── 1st passing health check on Node A (consecutive_success = 1)
[24.0s] ── 2nd passing health check on Node A (consecutive_success = 2 >= HEALTHY_THRESHOLD)
[24.1s] ──🎉 Node A re-admitted to ALB pool; balanced round-robin traffic automatically resumes
```

### Disaster Recovery Metrics
1. **Recovery Time Objective (RTO):**
   * Target detection interval = $\text{Unhealthy Threshold} \times \text{Health Check Interval} = 2 \times 1.0\text{s} = \mathbf{2.0\text{ seconds}}$.
   * Client-perceived disruption window = **0.00 seconds** (0 failed requests returned to clients because the ALB seamlessly routed in-flight requests to Zone B).
2. **Recovery Point Objective (RPO):**
   * **0 seconds.** The vaccination center lookup service operates as a stateless read engine. No state mutation or in-flight database transactions were lost.
3. **High Availability Metric ($A$):**
   $$A = \frac{\text{Uptime}}{\text{Total Time}} = \frac{32.0\text{s} - 0.0\text{s}}{32.0\text{s}} = \mathbf{100.0\% \text{ observed availability}}$$

---

## 5. Scaling Behavior & Elasticity Observations

1. **Zone Redundancy vs Multi-Region:**
   * Distributing instances across separate Availability Zones (`ap-south-1a` and `ap-south-1b`) protects against datacenter-level hardware faults, power outages, and localized fiber cuts with sub-millisecond cross-zone latency.
   * However, for national public platforms like CoWIN, an AZ-level topology must be paired with **multi-region disaster recovery** (e.g. Primary region in Mumbai `ap-south-1` with warm standby in Hyderabad `ap-south-2`) using Amazon Route 53 DNS Failover / Latency Routing to withstand regional-scale catastrophes.
2. **Load Balancer Connection Draining (Deregistration Delay):**
   * In a graceful scaling/maintenance event, ALB connection draining (default 300s, tuned to 15s for microservices) allows in-flight requests to complete before terminating an instance.

---

## 6. Team Contributions to Week 3 Deliverable

* **Kaushal Nandaniya (ID: 202303036) — AWS Cloud Infrastructure & Cost Lead:**
  * Authored the AWS CloudFormation template (`aws_cfn_cowin_two_zone.yaml`) configuring VPC, subnets across 2 AZs, security groups, ALB, and EC2 nodes.
  * Developed the automated AWS deployment script (`deploy_aws.sh`).
  * Formulated the itemized cost breakdown and national-scale TCO economic model (`COST_AND_SCALING_ANALYSIS.md`).
* **Darshil Gandhi (ID: 202301056) — Service Implementation & Benchmarking Lead:**
  * Developed the CoWIN Lookup Microservice (`service/app.py`) and vaccination center dataset (`centers_data.json`).
  * Authored the automated failover benchmark suite (`failover_benchmark.py`) and experiment runner (`run_experiment.sh`).
  * Executed the benchmark suite, gathered latency logs (`benchmark_requests.csv`), and generated the visual traffic timeline (`generate_plots.py`).
* **Jeetrajsinh Gohil (ID: 202303017) — Report Lead & Architecture Coordinator:**
  * Structured the Week 3 report add-on sections and verified alignment with course project guidelines.
  * Formulated the RTO/RPO disaster recovery analysis and health transition state machine documentation.
  * Prepared LaTeX source (`WEEK_3_REPORT_ADDON.tex`) for seamless integration into the final submission.
