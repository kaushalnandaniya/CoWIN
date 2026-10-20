# IT457: Cloud Computing — Case Study Project Plan
## Week 1 Checkpoint Deliverable: One-Page Case Study Summary

**Topic:** CoWIN (Cloud Platform for COVID-19 Vaccination Scheduling at National Scale)  
**Category:** Government & Public Digital Infrastructure (National/Billion-Scale)  
**Milestone:** Week 1 Checkpoint — Primary Sources, Architectural Extraction, Cost & Outcome Analysis  

---

### 1. Case Study Salient Points

#### A. Problem Statement & Operational Demands
* **Planetary Scale & High Concurrency:** Manage end-to-end vaccination scheduling, dose logging, and certification for 1.38+ billion citizens across 700+ districts and 110,000+ public/private vaccination centers.
* **The "Thundering Herd" Bottleneck:** When slots opened daily at specified times, millions of concurrent citizens and automated bots sent instantaneous reservation requests, creating extreme database lock contention and connection starvation.
* **Write-Heavy Workload:** Unlike typical read-heavy web portals, CoWIN required thousands of simultaneous, guaranteed, ACID-compliant writes per second (slot locks, stock decrements, vaccinator dose confirmations).
* **Data Sovereignty & Multi-Channel Access:** Strict sovereign compliance under Indian data residency rules, requiring high availability (99.99%) across Tier-1/2/3 cities and rural centers with low-bandwidth 2G/3G connectivity.

#### B. Extracted Cloud Architecture Blueprint
* **Edge & Traffic Ingress Layer:** Anycast DNS via Amazon Route 53 and NIC DNS; Amazon CloudFront CDN at edge points of presence (PoPs) to absorb read queries (center searches, FAQs) and eliminate origin load; AWS WAF & API Setu rate limiters to block scrapers and bot traffic.
* **Compute & Container Orchestration:** Stateless microservices deployed on Kubernetes (Amazon Elastic Kubernetes Service - EKS & NIC MeghRaj Sovereign Cloud). Elastic Auto Scaling Groups (ASGs) scaling horizontally based on CPU utilization, memory pressure, and API queue latency.
* **Distributed In-Memory Caching & Locking:** Redis / Amazon ElastiCache clusters acting as the first-line concurrency buffer. District/pincode-level slot inventory is partitioned and cached; atomic Redis operations (`DECR`, Redlock distributed locks) prevent double-booking before hitting the persistent database.
* **Polyglot Persistence Layer:**
  * **Relational / ACID Engine (PostgreSQL / Managed RDS):** Handles transactional operations requiring strict consistency (slot locking, facility vaccine allocations, transaction logs).
  * **Document / NoSQL Datastore (MongoDB / DocumentDB):** Stores non-relational citizen profiles and appointment metadata for rapid schema-flexible reads.
  * **High-Throughput Columnar Analytics (ClickHouse):** Streams operational telemetries for national and state real-time administrative dashboards.
* **Asynchronous Event-Driven Messaging:** Apache Kafka and Amazon SQS pipelines decouple heavy non-blocking operations: OTP generation/dispatch via SMS telecom gateways, vaccination event auditing, and asynchronous certificate generation.
* **Verifiable Credentialing Engine (DIVOC / Sunbird RC):** Built on open-source DIVOC, issuing W3C-compliant Verifiable Credentials (JSON-LD) signed with asymmetric Ed25519 cryptographic keys. The digitally signed 2D QR code enables instant **offline verification**, eliminating millions of verification query loads on central cloud servers.

#### C. Cost Data & Infrastructure Economics
* **Development & Infrastructure CapEx/OpEx:** The core CoWIN software development and cloud operations were executed at a frugal cost estimated under **₹50–₹100 Crore (~$6.5–$13 Million USD)** over the campaign lifecycle, managed under NHA/MoHFW budgets.
* **Programme Expenditure Comparison:** India’s Union Budget allocated **₹35,000 Crore** for COVID-19 vaccine procurement and logistics in FY 2021-22 (reaching ~₹36,398 Cr total procurement). The digital cloud platform represented **less than 0.3% of the total vaccination program outlay**.
* **Global Benchmarking:** Western equivalents incurred drastically higher expenditures (e.g., UK NHS Covid App at >£300M+ / ~$380M, US CDC VAMS at ~$44M+), making CoWIN one of the most cost-effective cloud-native digital public goods globally, with an estimated digital operational cost of under **₹0.50 ($0.006 USD) per beneficiary**.
* **Cloud Hosting Trade-Off:** Leveraged a hybrid strategy: sovereign storage and core registries on government infrastructure (NIC / MeghRaj) for data residency and zero-egress public network costs, combined with MeitY-empanelled hyperscalers (AWS India) for burst compute elasticity during national mega-drives.

#### D. Outcome Data & Real-World Performance
* **Total Doses Administered & Certified:** **2.20+ Billion doses** successfully tracked and verified with cryptographic digital certificates.
* **Citizen Registrations:** **1.02+ Billion unique citizens** registered on the platform.
* **Peak Single-Day Throughput:** **25.1 Million vaccinations** recorded in a single 24-hour day (September 17, 2021), sustaining ~290 writes/sec and peak bursts of **30,000+ status updates/second**.
* **Peak Registration Burst:** **13.7 Million registrations** absorbed in an 8-hour window (~476 registrations/second).
* **API Ingress Scale:** Peak daily traffic exceeding **3.2 Billion API hits/day** with average OTP delivery latencies under 15 seconds (99% success rate).
* **Uptime & Global Reusability:** Maintained **99.99% availability** during national wave peaks; open-sourced globally as a Digital Public Good (DPG) and shared with 142+ countries at the CoWIN Global Conclave.

#### E. Alignment with Week 3 Exercise Plan
* **Course Requirement:** *Design a multi-region, high-availability architecture for a national-scale service, then build a scaled-down version of one component.*
* **Proposed Implementation:** Build a **High-Concurrency Distributed Slot Reservation Engine** replicating CoWIN's slot booking pipeline: containerized microservice behind a load balancer, Redis distributed locking (`Redlock` / atomic inventory decrement), an asynchronous message queue (RabbitMQ / Kafka / SQS) to absorb burst writes, and a transactional PostgreSQL persistence store. Perform load testing with k6/Locust to measure latency and scaling behavior under simulated thundering-herd traffic.

---

### 2. Primary Sources Found

| Category | Source Title & Citation | Origin / Publisher | Key Extracted Information & Technical Insight |
| :--- | :--- | :--- | :--- |
| **Official Government & Technical Specs** | **CoWIN Portal & Open API Specifications**<br>[API Setu CoWIN Documentation](https://apisetu.gov.in) | National Health Authority (NHA) & MoHFW, Govt. of India | Open and Protected API contracts, rate-limiting schemas (100 req/5 min/IP), tokenized authentication, multi-tenant center query endpoints. |
| **Leadership & Architectural Blueprint** | **"CoWIN: Technology Behind the World's Largest Vaccination Drive"**<br>Dr. R.S. Sharma (CEO, NHA) | National Health Authority / PIB Press Releases (2021) | Technical design principles: single source of truth, decoupled architecture, stateless microservices, zero geofencing data capture for privacy. |
| **Open-Source Core Codebase** | **DIVOC: Digital Infrastructure for Verifiable Open Credentialing**<br>[GitHub: egovernments/divoc](https://github.com/egovernments/divoc) | eGovernments Foundation / Digital Public Goods Alliance | Implementation details of Keycloak IdP, Apache Kafka event pipelines, ClickHouse analytical datastore, and W3C JSON-LD credential schema. |
| **Standards & Credentialing** | **W3C Verifiable Credentials Data Model v1.1**<br>[W3C Recommendation](https://www.w3.org/TR/vc-data-model/) | World Wide Web Consortium (W3C) | Cryptographic verification specifications (Ed25519 signature suite, 2D QR format) enabling offline certificate authenticity verification. |
| **Cloud & Hardware Case Study** | **"Scaling CoWIN on AWS Cloud" & Intel Xeon Hardware Optimization**<br>[AWS Architecture / Vajiram / Intel Solution Brief] | Amazon Web Services & Intel Corporation | Autoscaling microservices on Amazon EKS, CloudFront edge caching, ElastiCache Redis write optimization, and cryptographic compute offloads. |
| **Multilateral Institutional Analysis** | **"Stacking Up the Benefits: Lessons from India's Digital Journey"**<br>IMF Working Paper WP/23/78 (2023) | International Monetary Fund (IMF) & World Bank | Public infrastructure economics, low implementation cost compared to national budget, platform interoperability with Aadhaar and DigiLocker. |
| **Academic & Systems Research** | **"Scalable, Privacy-Preserving Architecture for Population-Scale Digital Public Goods"**<br>[arXiv:2203.04873 / DPGA Repository] | Academic & Open-Source Research Community | Analysis of write-heavy transaction bottlenecks, distributed caching trade-offs, and horizontal sharding strategies for national immunization platforms. |
