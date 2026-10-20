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

- [x] **Week 1 (Current Checkpoint):** Find primary sources, relevant information, extract architecture, cost and outcome data. Deliverable: One-page summary.
- [ ] **Week 2:** Detailed study, comprehensive architecture diagram, problem definition, solution analysis, 10-page report, exercise plan & team roles.
- [ ] **Week 3:** Build the core exercise (**High-Concurrency Distributed Slot Reservation Engine** with Redis distributed locks, async message buffer, and PostgreSQL), run experiments (latency, scaling behavior, cost), and test system.
- [ ] **Week 4:** Final report preparation, consolidation, and submission.
- [ ] **Week 5:** Project VIVA defense.

---

## 📚 Primary Sources & Citations

1. **National Health Authority (NHA) & MoHFW:** *CoWIN Platform Guidelines and API Specifications* ([apisetu.gov.in](https://apisetu.gov.in)).
2. **Dr. R.S. Sharma (CEO, NHA / Head, Empowered Group):** *"CoWIN: Technology Behind the World's Largest Vaccination Drive"*, CoWIN Global Conclave.
3. **eGovernments Foundation & DPGA:** *DIVOC (Digital Infrastructure for Verifiable Open Credentialing) Open-Source Stack* ([GitHub: egovernments/divoc](https://github.com/egovernments/divoc)).
4. **Amazon Web Services (AWS) & Intel Corporation:** *"Scaling CoWIN Platform on AWS Cloud"*.
5. **International Monetary Fund (IMF) & World Bank:** *"Stacking Up the Benefits: Lessons from India's Digital Journey"*, Working Paper WP/23/78.
6. **W3C:** *Verifiable Credentials Data Model v1.1* ([W3C Recommendation](https://www.w3.org/TR/vc-data-model/)).

---

## 👤 Author
* **Kaushal Nandaniya** ([@kaushalnandaniya](https://github.com/kaushalnandaniya))
