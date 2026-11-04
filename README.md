# CoWIN: Cloud Platform for COVID-19 Vaccination Scheduling at National Scale

[![Course](https://img.shields.io/badge/Course-IT457%20Cloud%20Computing-blue.svg)](IT457_Project_%20Doc.pdf)
[![Milestone](https://img.shields.io/badge/Milestone-Week%201%20Checkpoint-green.svg)](WEEK_1_SUMMARY.md)
[![Scale](https://img.shields.io/badge/Scale-1.38B%20Citizens%20%7C%202.2B%20Doses-orange.svg)](WEEK_1_SUMMARY.md)
[![PDF Deliverable](https://img.shields.io/badge/Deliverable-1--Page%20PDF-red.svg)](WEEK_1_SUMMARY.pdf)

> **IT457 Cloud Computing Course Project**  
> Case Study on Government & Public Digital Platforms: **CoWIN (Covid Vaccine Intelligence Network)**.

---

## 📌 Deliverables

| Deliverable | Description | Link |
| :--- | :--- | :--- |
| **Week 3 Report Add-on (Markdown)** | Full experimental report: Two-zone PoC results, failover metrics, latency percentiles, and disaster recovery analysis. | [WEEK_3_REPORT_ADDON.md](WEEK_3_REPORT_ADDON.md) |
| **Week 3 Report Add-on (LaTeX)** | LaTeX source with measurement tables for integration into the final report. | [WEEK_3_REPORT_ADDON.tex](WEEK_3_REPORT_ADDON.tex) |
| **Cost & Scaling Analysis** | Itemized AWS Mumbai pricing for PoC + National-Scale TCO comparative model (AWS vs NIC MeghRaj). | [COST_AND_SCALING_ANALYSIS.md](COST_AND_SCALING_ANALYSIS.md) |
| **AWS CloudFormation Template** | Automated IaC template for VPC, 2-AZ subnets, security groups, ALB, and EC2 instances. | [infrastructure/aws_cfn_cowin_two_zone.yaml](infrastructure/aws_cfn_cowin_two_zone.yaml) |
| **Vaccination Center Lookup Service** | Lightweight microservice (`/health`, `/api/v1/centers`) with zero external dependencies. | [service/app.py](service/app.py) |
| **Automated Failover Benchmark** | Test harness, ALB proxy simulator, and 1-click experiment runner with latency logging. | [benchmark/run_experiment.sh](benchmark/run_experiment.sh) |
| **Week 2 Progress Report (PDF)** | High availability and failover: high-level architecture, PoC plan & team work distribution. | [WEEK_2_PROGRESS_REPORT.pdf](WEEK_2_PROGRESS_REPORT.pdf) |
| **Week 2 Progress Report (LaTeX)** | LaTeX source with TikZ national-scale architecture and 2-zone PoC diagram. | [WEEK_2_PROGRESS_REPORT.tex](WEEK_2_PROGRESS_REPORT.tex) |
| **Team Work Division (3 Members)** | Comprehensive role allocation, RACI matrix, week-by-week tasks, and PoC ownership. | [TEAM_WORK_DIVISION.md](TEAM_WORK_DIVISION.md) |
| **Week 1 Checkpoint Summary (Markdown)** | Full executive summary covering primary sources found, architecture, cost data, and outcomes. | [WEEK_1_SUMMARY.md](WEEK_1_SUMMARY.md) |
| **Week 1 Checkpoint Summary (1-Page PDF)** | Exact 1-page submission-ready executive summary report. | [WEEK_1_SUMMARY.pdf](WEEK_1_SUMMARY.pdf) |
| **Week 1 HTML Version** | Clean, styled HTML document with print CSS layout. | [WEEK_1_SUMMARY.html](WEEK_1_SUMMARY.html) |
| **Project Guidelines** | Official course project plan and deliverables specification. | [IT457_Project_ Doc.pdf](IT457_Project_%20Doc.pdf) |

---

## 🚀 Key Operational Metrics Extracted

* **Total Vaccinations Certified:** **2.20+ Billion doses** issued with tamper-proof cryptographic QR codes.
* **Citizen Registrations:** **1.02+ Billion unique citizens** onboarded across 700+ districts.
* **Single-Day Peak Throughput:** **25.1 Million doses** administered on September 17, 2021 (~290 writes/sec sustained, peak bursts > 30,000 updates/sec).
* **API Ingress:** Peak traffic exceeding **3.2+ Billion API hits/day** with 99.99% platform availability.
* **Frugal Platform Economics:** Platform software and cloud infrastructure spend was estimated under **₹50–₹100 Crore (~$7–$13M USD)**, representing **less than 0.3%** of India's ₹35,000 Crore vaccination procurement outlay (under ₹0.50 / $0.006 USD per beneficiary).

---

## 🏛️ Extracted Cloud Architecture Blueprint

```
[ Citizens / Healthcare Workers / 3rd-Party Portals ]
                         │
                         ▼
             [ Amazon Route 53 (DNS) ]
                         │
                         ▼
           [ Amazon CloudFront (CDN Edge) ]
                         │
                         ▼
        [ AWS WAF & API Setu Rate Limiters ]
                         │
                         ▼
        [ Elastic Load Balancer (ALB / Ingress) ]
                         │
     ┌───────────────────┼───────────────────┐
     ▼                   ▼                   ▼
[ Auth & OTP ]  [ Slot Reservation ]  [ Vaccination Exec ]
(Microservice)    (Microservice)       (Microservice)
                         │                   │
                         ▼                   │
             [ Distributed Redis Cache ]     │
             (Atomic DECR & Redlock)        │
                         │                   │
                         ▼                   ▼
             [ PostgreSQL / Managed RDS (ACID Transactions) ]
                         │
                         ▼
     [ Apache Kafka / SQS Event Streaming Backbone ]
         ┌───────────────┴───────────────┐
         ▼                               ▼
[ DIVOC Verification Engine ]    [ ClickHouse Analytics ]
(Ed25519 Signed QR / W3C VCs)     (Real-Time National Dashboards)
```

---

## 📅 Project Plan & Milestones

- [x] **Week 1 (Foundations):** Primary sources found, relevant information, extract architecture, cost and outcome data. Deliverable: One-page summary.
- [x] **Week 2 (Design & PoC Planning):** High availability & failover study, conceptual multi-region architecture (TikZ), 2-zone AWS PoC design, and team work allocation.
- [x] **Week 3 (Implementation & Experiments):** Built vaccination center lookup microservice, architected 2-zone AWS CloudFormation IaC, ran automated failover benchmark, measured latency percentiles ($p50=3.73$ms, $p99=9.32$ms), verified 100% availability ($RTO \approx 0$s), and authored Week 3 report add-on.
- [ ] **Week 4:** Final report consolidation, architecture verification, and submission.
- [ ] **Week 5:** Project VIVA presentation and defense.

---

## 🔬 Week 3 Experimental Benchmark Results

### Two-Zone Failover Test (10 req/s, 320 Total Requests)
* **Overall Availability:** **100.0%** (320/320 successful HTTP 200 responses, 0 errors).
* **Observed Disruption Window:** **0.00 seconds** (ALB redirected all requests to survivor Zone B without unhandled failures).
* **Recovery Time Objective (RTO):** **< 2.0 seconds** (Health check detection time: $2 \times 1\text{s}$).
* **Recovery Point Objective (RPO):** **0 seconds** (Stateless lookup microservice architecture).
* **Latency Profile:** Min: **1.69 ms** | Median ($p50$): **3.73 ms** | $p95$: **7.71 ms** | $p99$: **9.32 ms** | Max: **18.22 ms**.
* **Traffic Route Timeline:**
  * **$t = 0\text{s} - 10\text{s}$ (Baseline):** 50% Zone A (`ap-south-1a`) / 50% Zone B (`ap-south-1b`).
  * **$t = 10\text{s}$:** Abrupt health degradation injected into Node A.
  * **$t = 12\text{s} - 22\text{s}$ (Failover):** 100% of traffic absorbed by survivor Node B (`ap-south-1b`).
  * **$t = 22\text{s}$:** Node A restored; health checks pass at $t = 24\text{s}$ and balanced round-robin resumes.

```
Time(s) | Traffic Route Visualizer                                    | Avg Latency
------- | ----------------------------------------------------------- | -----------
 0s- 9s | 🔵🔵🔵🔵🔵🟢🟢🟢🟢🟢 (50% Zone A / 50% Zone B Balanced)          |   4.1 ms
 10s    | 🔵🔵🔵🔵🔵🟢🟢🟢🟢🟢 ⚡ [Zone A Failure Injected]                 |   4.2 ms
 12s-21s| 🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢 🛡️ [100% Absorbed by Zone B Survivor]       |   3.9 ms
 22s    | 🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢 🔄 [Zone A Restored]                         |   4.6 ms
 24s-32s| 🔵🔵🔵🔵🔵🟢🟢🟢🟢🟢 🎉 [ALB Re-admits Zone A - Rebalanced]      |   4.2 ms
Legend: 🔵 = Zone A (ap-south-1a)  |  🟢 = Zone B (ap-south-1b)
```

---

## 📚 Primary Sources & Citations

1. **National Health Authority (NHA) & MoHFW:** *CoWIN Platform Guidelines and API Specifications* ([apisetu.gov.in](https://apisetu.gov.in)).
2. **Dr. R.S. Sharma (CEO, NHA / Head, Empowered Group):** *"CoWIN: Technology Behind the World's Largest Vaccination Drive"*, CoWIN Global Conclave.
3. **eGovernments Foundation & DPGA:** *DIVOC (Digital Infrastructure for Verifiable Open Credentialing) Open-Source Stack* ([GitHub: egovernments/divoc](https://github.com/egovernments/divoc)).
4. **Amazon Web Services (AWS) & Intel Corporation:** *"Scaling CoWIN Platform on AWS Cloud"*.
5. **International Monetary Fund (IMF) & World Bank:** *"Stacking Up the Benefits: Lessons from India's Digital Journey"*, Working Paper WP/23/78.
6. **W3C:** *Verifiable Credentials Data Model v1.1* ([W3C Recommendation](https://www.w3.org/TR/vc-data-model/)).

---

## 👥 Team Members & Role Allocation (3 Members)

See detailed breakdown, milestone matrix, and RACI ownership in [**TEAM_WORK_DIVISION.md**](TEAM_WORK_DIVISION.md).

| Student Name | Student ID | Designated Core Role | Primary Responsibilities |
| :--- | :---: | :--- | :--- |
| **Jeetrajsinh Gohil** | **202303017** | **Report Lead & Architecture Coordinator** | Problem definition, HA research, national-scale architecture diagram, failover review, and report coordination. |
| **Kaushal Nandaniya** | **202303036** | **AWS Cloud Infrastructure & Topology Lead** | AWS VPC/subnet design across 2 AZs, ALB & EC2 provisioning, health checks configuration, and cost modeling. |
| **Darshil Gandhi** | **202301056** | **Service Implementation & Benchmarking Lead** | Lightweight lookup API, client polling test harness, continuous failover stress scripts, disruption window metric logging, and screen evidence. |
