# CoWIN: Cloud Platform for COVID-19 Vaccination Scheduling at National Scale

[![Course](https://img.shields.io/badge/Course-IT457%20Cloud%20Computing-blue.svg)](docs/team/IT457_Project_%20Doc.pdf)
[![Theme](https://img.shields.io/badge/Theme-Govt%20%26%20Public%20Platforms-orange.svg)](docs/team/TEAM_WORK_DIVISION.md)
[![AWS Multi-AZ](https://img.shields.io/badge/AWS-2--Zone%20ALB%20PoC-green.svg)](infrastructure/aws_cfn_cowin_two_zone.yaml)
[![Status](https://img.shields.io/badge/Milestone-Week%203%20Completed-brightgreen.svg)](docs/week-3/KAUSHAL_WEEK_3_INFRASTRUCTURE_REPORT.md)

> **IT457 Cloud Computing Course Project**  
> Case Study on Government & Public Digital Platforms: **CoWIN (Covid Vaccine Intelligence Network)**.

---

## 👥 Project Team & Responsibility Boundaries

Per **Table 5** of the approved Week 2 Progress Report, responsibilities are strictly partitioned to ensure individual accountability:

| Member Name | Student ID | Core Role | Assigned Technical Domain |
| :--- | :---: | :--- | :--- |
| **Kaushal Nandaniya** | **202303036** | **AWS Cloud Infrastructure, Networking & Cost Lead** | • Configure AWS instances, custom VPC, 2-AZ subnets, security groups, ALB & health checks.<br>• Author CloudFormation IaC (`infrastructure/`).<br>• Author Cost & Scaling Analysis (`docs/week-3/COST_AND_SCALING_ANALYSIS.md`).<br>• Capture infrastructure evidence & architecture specs. |
| **Darshil Gandhi** | **202301056** | **Service Implementation & Testing Lead** | • Develop lightweight lookup service (`service/`).<br>• Plan & author client test harness (`benchmark/`).<br>• Execute load testing, capture timestamps, error logs & failover screenshots. |
| **Jeetrajsinh Gohil** | **202303017** | **Report Lead & Architecture Coordinator** | • Lead report compilation (`WEEK_2_PROGRESS_REPORT`, `WEEK_4_FINAL_REPORT`).<br>• Research high availability & national-scale conceptual architecture.<br>• Document failover observations, RTO/RPO analysis & VIVA presentation. |

---

## 📁 Repository Directory Structure

```
CoWIN/
├── README.md                          # Main repository overview & directory index
├── infrastructure/                    # [Kaushal's Domain] AWS CloudFormation IaC & Deployment
│   ├── aws_cfn_cowin_two_zone.yaml    # Production CloudFormation template (VPC, 2 AZs, ALB, EC2)
│   └── deploy_aws.sh                  # Automation script for stack provisioning & failover testing
├── docs/                              # Project Documentation & Reports (Organized by Milestone)
│   ├── team/                          # Team Guidelines & Role Allocation
│   │   ├── IT457_Project_Doc.pdf      # Official course project plan & syllabus
│   │   └── TEAM_WORK_DIVISION.md      # RACI responsibility matrix & milestone commitments
│   ├── week-1/                        # Week 1: Research, Architecture Extraction & Sources
│   │   ├── WEEK_1_SUMMARY.md          # Markdown executive summary
│   │   ├── WEEK_1_SUMMARY.pdf         # 1-Page submission PDF
│   │   └── WEEK_1_SUMMARY.html        # Formatted HTML report
│   ├── week-2/                        # Week 2: Design & PoC Planning (Led by Jeetraj)
│   │   ├── WEEK_2_PROGRESS_REPORT.pdf # 5-Page progress report on HA and failover
│   │   └── WEEK_2_PROGRESS_REPORT.tex # LaTeX source with TikZ diagrams
│   └── week-3/                        # Week 3: Infrastructure, Testing & Results
│       ├── KAUSHAL_WEEK_3_INFRASTRUCTURE_REPORT.pdf # Kaushal's Week 3 report deliverable (PDF)
│       ├── KAUSHAL_WEEK_3_INFRASTRUCTURE_REPORT.tex # LaTeX source for Kaushal's report
│       ├── KAUSHAL_WEEK_3_INFRASTRUCTURE_REPORT.md  # Markdown documentation
│       └── COST_AND_SCALING_ANALYSIS.md             # Itemized AWS pricing & CoWIN TCO model
├── service/                           # [Darshil's Domain] Vaccination Center Lookup Microservice
│   ├── README.md                      # Service architecture & integration contract
│   ├── app.py                         # Python lookup service (/health, /api/v1/centers)
│   ├── centers_data.json              # Sample centers dataset
│   └── cowin-lookup.service           # Systemd daemon definition
└── benchmark/                         # [Darshil & Jeetraj's Domain] Failover Testing Suite
    ├── README.md                      # Test suite documentation & instructions
    ├── alb_simulator.py               # Local multi-threaded ALB reverse-proxy simulator
    ├── failover_benchmark.py          # Continuous polling test runner (10 req/s)
    ├── generate_plots.py              # Visual ASCII route graph generator
    └── run_experiment.sh              # 1-click test launcher
```

---

## 🏛️ Kaushal's Week 3 Infrastructure Deliverables (ID: 202303036)

### 1. Two-Zone AWS Architecture & Networking
* **Custom VPC (`10.0.0.0/16`):** Deployed across `ap-south-1a` and `ap-south-1b` in AWS Mumbai.
* **Defense-in-Depth Security Groups:** EC2 compute instances on port 8080 accept traffic **strictly** from the Application Load Balancer Security Group, eliminating direct public exposure.
* **Application Load Balancer (ALB):** Internet-facing ALB distributing requests across both subnets with round-robin forwarding.
* **Target Group & Health Probing:** Probes `/health` every 5 seconds (interval: 5s, timeout: 2s, healthy threshold: 2, unhealthy threshold: 2).
* **Automated CloudFormation IaC:** [`infrastructure/aws_cfn_cowin_two_zone.yaml`](infrastructure/aws_cfn_cowin_two_zone.yaml) provisions the entire topology automatically.

### 2. Cost Analysis & Scaling Modeling
Full documentation in [`docs/week-3/COST_AND_SCALING_ANALYSIS.md`](docs/week-3/COST_AND_SCALING_ANALYSIS.md):
* **Experimental PoC Cost:** **$0.00 / month** on AWS Free Tier; **$0.054 / hour (~$0.43 for an 8-hour test)** at commercial rates.
* **National-Scale TCO Model:** 
  * Multi-region active-active deployment on AWS (`ap-south-1` + `ap-south-2`): **~$45,800 / month**.
  * Sovereign Government Cloud (**NIC MeghRaj**): **~Rs. 33.5 Lakhs / month** with zero data egress charges.
  * Amortized unit cost: **under Rs. 0.78 ($0.009 USD) per citizen** across 1.02 billion beneficiaries.

---

## 📅 Project Milestones & Checklist

- [x] **Week 1 (Foundations):** Primary sources found, relevant information, extract architecture, cost and outcome data. Deliverable: One-page summary in [`docs/week-1/`](docs/week-1/).
- [x] **Week 2 (Design & PoC Planning):** High availability study, conceptual national-scale architecture, 2-zone AWS PoC design, and team work allocation in [`docs/week-2/`](docs/week-2/).
- [x] **Week 3 (Infrastructure & Implementation):**
  - [x] **Kaushal (202303036):** Provisioned VPC, 2-AZ subnets, ALB, Target Groups, CloudFormation IaC, and authored Cost & Scaling Report in [`docs/week-3/`](docs/week-3/).
  - [x] **Darshil (202301056):** Lookup microservice in [`service/`](service/) and testing harness in [`benchmark/`](benchmark/).
  - [x] **Jeetraj (202303017):** Failover review and observations coordination.
- [ ] **Week 4 (Final Report):** Final report consolidation, architecture verification, and submission.
- [ ] **Week 5 (Project VIVA):** Final project presentation and VIVA defense.

---

## 👥 Authors & Contact
* **Kaushal Nandaniya** ([@kaushalnandaniya](https://github.com/kaushalnandaniya)) — Student ID: `202303036`
* **Darshil Gandhi** — Student ID: `202301056`
* **Jeetrajsinh Gohil** ([@jeetrex17](https://github.com/jeetrex17)) — Student ID: `202303017`
