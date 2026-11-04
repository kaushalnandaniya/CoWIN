# IT457 Cloud Computing: Team Work Division & Role Allocation

**Project:** CoWIN (Cloud Platform for COVID-19 Vaccination Scheduling at National Scale)  
**Track:** Government and Public Digital Platforms (National / Billion-Scale Cloud Infrastructure)  
**Team Size:** 3 Members  

---

## 👥 Project Team

| Member Name | Student ID | Designated Core Role | GitHub Profile |
| :--- | :---: | :--- | :--- |
| **Jeetrajsinh Gohil** | **202303017** | **Report Lead & Architecture Coordinator** | [@Jeetraj](https://github.com/kaushalnandaniya/CoWIN) |
| **Kaushal Nandaniya** | **202303049** | **AWS Cloud Infrastructure & Topology Lead** | [@kaushalnandaniya](https://github.com/kaushalnandaniya) |
| **Darshil Gandhi** | **202301056** | **Service Implementation & Benchmarking Lead** | — |

---

## 🏛️ Course Requirement & Scope Alignment

Per the course guide and instructor clarification (dated 22 October 2026):
> *The named platform (CoWIN) provides case-study context; a miniature version of the complete national platform is not expected. The Government and Public Platforms theme demonstrates high availability and disaster recovery through a national-scale architecture diagram, a working component across zones, and a failover demonstration.*

### Scope Boundary
* **National-Scale Conceptual Design:** Multi-region DNS routing, regional load balancers, and multi-zone application clusters.
* **Practical Hands-On PoC:** Two-zone deployment in an AWS region featuring an Application Load Balancer (ALB) distributing traffic to two redundant EC2 instances running a lookup API.
* **Failover Validation:** Measure service continuity, health check detection latency, and disruption window when one instance is intentionally stopped.

---

## 🎯 Member Roles & Responsibilities

### 1. Jeetrajsinh Gohil (ID: 202303017)
**Role:** Report Lead & National Architecture Coordinator
* **Week 2 (Design & Planning):**
  * Define problem statement for high availability and disaster recovery in national public platforms.
  * Research multi-region DNS failover patterns (Route 53 latency/failover routing).
  * Design the conceptual national-scale architecture diagram (LaTeX TikZ).
  * Lead coordination and compilation of the **Week 2 Progress Report**.
* **Week 3 (Implementation & Evidence):**
  * Review deployed two-zone AWS architecture and verify security group boundaries.
  * Coordinate the live failover demonstration and record transition observations.
  * Document failure detection timestamps, RTO/RPO analysis, and recovery behavior in the report.

---

### 2. Kaushal Nandaniya (ID: 202303049)
**Role:** AWS Cloud Infrastructure & Topology Lead
* **Week 2 (Design & Planning):**
  * Review Week 1 primary sources and architectural parameters.
  * Design the AWS network topology: VPC, public subnets across two Availability Zones (AZ-a and AZ-b), Internet Gateway, and route tables.
  * Select EC2 instance types (e.g., `t3.micro` / `t4g.micro` under free-tier/low-cost budget) and develop preliminary cloud cost model.
* **Week 3 (Implementation & Evidence):**
  * Provision AWS networking, EC2 instances across the two AZs, Application Load Balancer (ALB), Target Groups, and HTTP health check endpoints.
  * Capture infrastructure screenshots (VPC map, Target Group health state, ALB metrics).
  * Manage AWS resource lifecycle and cost tracking; tear down resources post-demonstration.

---

### 3. Darshil Gandhi (ID: 202301056)
**Role:** Service Implementation, Benchmarking & Evidence Lead
* **Week 2 (Design & Planning):**
  * Specify the lightweight sample lookup API (FastAPI / Express) returning vaccination center data.
  * Design the automated client-side test harness (Python / k6 script) for continuous polling during failover.
  * Define metrics collection methodology: request intervals, status codes, response latencies, and failure window estimation.
* **Week 3 (Implementation & Evidence):**
  * Package and deploy the lookup API to both EC2 instances (systemd / Docker).
  * Execute continuous load/request scripts during the instance-stop failover test.
  * Collect client-side timestamped logs, compute disruption window, plot latency graphs, and record screen evidence.

---

## 📅 Milestone Matrix Across Project Weeks

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                               WEEK-BY-WEEK WORK DISTRIBUTION                                 │
├───────────────┬───────────────────────────────┬───────────────────────────────┬──────────────┤
│ Milestone     │ Jeetrajsinh Gohil (202303017) │ Kaushal Nandaniya (202303049) │ Darshil Gandhi (202301056)
├───────────────┼───────────────────────────────┼───────────────────────────────┼──────────────┤
│ Week 1        │ Secondary literature search   │ Architecture extraction &     │ Cost data collection &       │
│ (Foundations) │ & governance review           │ 1-page summary authoring      │ metrics compilation          │
├───────────────┼───────────────────────────────┼───────────────────────────────┼──────────────┤
│ Week 2        │ Problem definition, national  │ AWS VPC/ALB topology design,  │ Lookup API design,           │
│ (Report & PoC)│ architecture TikZ & LaTeX lead│ resource selection & TCO model│ failover test plan & metrics │
├───────────────┼───────────────────────────────┼───────────────────────────────┼──────────────┤
│ Week 3        │ Failover review, RTO/RPO      │ Deploy AWS VPC, 2-AZ EC2,     │ Deploy API, run continuous   │
│ (Exec & Demo) │ analysis & observations doc   │ ALB, health checks & evidence │ load test & capture logs/vid │
├───────────────┼───────────────────────────────┼───────────────────────────────┼──────────────┤
│ Week 4        │ Final 10-page report lead,    │ Infrastructure cost audit &   │ Test result graphs, latency  │
│ (Final Subm.) │ synthesis & formatting        │ architecture section finalize │ data & appendices            │
├───────────────┼───────────────────────────────┼───────────────────────────────┼──────────────┤
│ Week 5        │ Present national architecture │ Defend cloud infrastructure,  │ Defend failover benchmarks,  │
│ (VIVA Defense)│ & high availability concepts  │ VPC networking & ALB routing  │ test data & recovery metrics │
└───────────────┴───────────────────────────────┴───────────────────────────────┴──────────────┘
```

---

## 📊 RACI Responsibility Matrix

| Project Deliverable / Component | Jeetrajsinh Gohil | Kaushal Nandaniya | Darshil Gandhi |
| :--- | :---: | :---: | :---: |
| **Week 1 Case Study Summary** | Consulted (C) | **Accountable (A)** | Responsible (R) |
| **Week 2 Progress Report (LaTeX / PDF)** | **Accountable (A)** | Responsible (R) | Responsible (R) |
| **National-Scale Conceptual Architecture** | **Accountable (A)** | Consulted (C) | Consulted (C) |
| **AWS Two-Zone Topology & Cloud Cost Model**| Consulted (C) | **Accountable (A)** | Informed (I) |
| **Lookup API & Container / Service Setup** | Informed (I) | Consulted (C) | **Accountable (A)** |
| **AWS VPC, ALB & EC2 Provisioning** | Consulted (C) | **Accountable (A)** | Responsible (R) |
| **Failover Load Test Script & Metric Logging**| Consulted (C) | Informed (I) | **Accountable (A)** |
| **Failover Video / Live Demo & Evidence** | Responsible (R) | Responsible (R) | **Accountable (A)** |
| **Final Project Report (Week 4)** | **Accountable (A)** | Responsible (R) | Responsible (R) |
| **Project VIVA Presentation (Week 5)** | **Responsible (R)** | **Responsible (R)** | **Responsible (R)** |

*(R = Responsible for execution, A = Accountable for completion & quality, C = Consulted for domain input, I = Kept informed)*

---

## 🛠️ Week 3 Hands-On PoC Architecture

```
                       [ Client / Test Polling Script ]
                           (Authored by Darshil)
                                     │
                                     ▼ HTTP Requests
                  [ Application Load Balancer (ALB) ]
                      (Configured by Kaushal)
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
       [ Availability Zone A ]         [ Availability Zone B ]
           [ EC2 Instance 1 ]              [ EC2 Instance 2 ]
             Lookup Service                  Lookup Service
       (Deploy: Kaushal / Darshil)     (Deploy: Kaushal / Darshil)
                     │                               │
         [ Stopped during test ]            [ Absorbs 100% traffic ]
```

### Failover Testing Procedure
1. Send continuous HTTP requests (e.g. 5–10 req/s) via the client script to the ALB DNS name.
2. Verify both instances in Target Group report status `healthy`.
3. Stop EC2 Instance 1 via AWS Management Console / CLI.
4. Record the timestamp of instance stop, ALB target health check transition (`healthy` $\to$ `unhealthy`), and client response status codes.
5. Measure the **service disruption window** (time from first error until all requests reliably route to Instance 2).
6. Restart Instance 1 and observe auto-recovery in the Target Group.
