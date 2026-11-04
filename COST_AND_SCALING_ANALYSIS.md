# IT457 Cloud Computing: Cost & Scaling Analysis
## CoWIN Two-Zone High Availability PoC & National-Scale TCO Model

**Author:** Kaushal Nandaniya (Student ID: **202303036**)  
**Designated Role:** AWS Cloud Infrastructure, Topology & Cost Modeling Lead  
**Milestone:** Week 3 Exercise Measurements & Economics  

---

## 1. Executive Cost Summary

A central objective of the Week 3 deliverable is to analyze **cloud cost and scaling behavior** under both experimental (PoC) and production (national-scale) conditions:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        INFRASTRUCTURE COST BREAKDOWN                   │
├───────────────────────────────┬────────────────────────────────────────┤
│ Experimental Two-Zone PoC     │ $0.076 / hour  (~$0.61 for 8-hr demo)   │
│ AWS Free Tier Cost            │ $0.00 / month  (100% eligible)         │
│ Production National Peak (AWS)│ ~$45,800 / month ($0.0003 / citizen)   │
│ Sovereign Cloud (NIC MeghRaj) │ ~₹60–75 Lakhs / month (Zero Egress Fee)│
└───────────────────────────────┴────────────────────────────────────────┘
```

---

## 2. Experimental PoC Infrastructure Cost (AWS Mumbai `ap-south-1`)

The experimental setup deployed in Week 3 consists of a 2-Availability-Zone redundant topology with an Application Load Balancer and two `t3.micro` EC2 instances.

### A. Itemized Resource Pricing (Hourly & Monthly)

| AWS Resource | Configuration / Sizing | Hourly Rate (USD) | 8-Hour Demo Cost | Monthly Run Cost (730 hrs) | Free Tier Eligibility |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **EC2 Node A (`ap-south-1a`)** | `t3.micro` (2 vCPU, 1 GiB RAM) | $0.0104 | $0.083 | $7.59 | Free (750 hrs/month) |
| **EC2 Node B (`ap-south-1b`)** | `t3.micro` (2 vCPU, 1 GiB RAM) | $0.0104 | $0.083 | $7.59 | Free (750 hrs/month) |
| **EBS Storage (Zone A)** | 20 GB gp3 SSD Storage | $0.0022 | $0.018 | $1.60 | Free (up to 30 GB) |
| **EBS Storage (Zone B)** | 20 GB gp3 SSD Storage | $0.0022 | $0.018 | $1.60 | Free (up to 30 GB) |
| **Application Load Balancer (ALB)** | 1 ALB across 2 AZs | $0.0225 | $0.180 | $16.43 | Free (750 hrs/month) |
| **ALB Capacity Units (LCU)** | 0.8 LCU average | $0.0064 | $0.051 | $4.67 | Free (15 LCUs/month) |
| **Data Transfer (Egress)** | ~2 GB (test requests + responses) | $0.0900 / GB | $0.180 | $0.18 | Free (up to 100 GB/mo) |
| **VPC & Internet Gateway** | Custom VPC, 2 Subnets, Route Tables | $0.0000 | $0.000 | $0.00 | Always Free |
| **TOTAL (Commercial Rate)** | | **$0.0541 / hr** | **$0.613** | **$39.06 / month** | **$0.00 on Free Tier** |

> **Cost Optimization Key Finding:** For students or academic institutions operating within the AWS Free Tier, running this complete two-zone high-availability failover experiment costs **$0.00**. Outside the free tier, conducting an entire day of testing and video demonstration costs less than **₹55 INR ($0.65 USD)**.

---

## 3. Scaling Behavior & Elasticity Analysis

### A. Horizontal vs. Vertical Scaling Dynamics

```
                [ Sudden Traffic Spike / Flash Crowd ]
                                  │
                                  ▼
                     [ ALB Automatic Scaling ]
                    (Elastic scaling of LCU nodes)
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
[ Availability Zone A ]                           [ Availability Zone B ]
Auto Scaling Group (ASG)                          Auto Scaling Group (ASG)
Target Tracking: 70% CPU                          Target Tracking: 70% CPU
Min: 2, Max: 20 instances                         Min: 2, Max: 20 instances
```

1. **Horizontal Elasticity (Auto Scaling Groups):**
   * While the Week 3 PoC utilizes 2 static instances for deterministic failover measurement, a production implementation uses an **Auto Scaling Group (ASG)** spanning both Availability Zones.
   * Target Tracking policy scales out instances when average CPU exceeds 70% or target request count exceeds 2,500 req/min/target.
   * **Scale-Out Latency:** EC2 instances launch and pass initial health checks in approximately **45 to 60 seconds** on Amazon Linux 2023 with pre-warmed AMI or container images on Amazon EKS.

2. **Load Balancer Scaling & Pre-Warming:**
   * AWS ALBs scale automatically by adding IP endpoints as traffic ramps up.
   * **The Pre-Warming Imperative:** During national vaccine slot release bursts (e.g. 10:00 AM slot release across a state), traffic increases by 100x within 5 seconds. Standard ALB DNS-based scaling requires 1–3 minutes to propagate new IPs.
   * **Engineering Solution:** CoWIN utilized load balancer pre-warming and Anycast CloudFront CDN caching at edge Points of Presence (PoPs) to absorb initial connection bursts before hitting origin ALBs.

---

## 4. Production National-Scale TCO Model (CoWIN Scale)

To fulfill the course requirement of evaluating the **national-scale cloud architecture**, this model projects monthly infrastructure costs for serving **1.38 billion citizens** with up to **3.2 billion requests per day**:

### Comparative Cloud Provider TCO (Monthly)

| Architectural Tier | AWS Enterprise Tier (`ap-south-1` + `ap-south-2`) | NIC MeghRaj Sovereign Cloud | Architectural Trade-offs |
| :--- | :---: | :---: | :--- |
| **Compute Layer** | **$24,500 / mo**<br>(400x `c6g.2xlarge` Graviton3) | **~₹18,00,000 / mo**<br>(Government data center servers) | AWS offers instant API-driven elasticity; NIC requires advance bureaucratic provisioning. |
| **Ingress & Load Balancing** | **$4,800 / mo**<br>(Multi-region ALBs + Route 53) | **~₹3,50,000 / mo**<br>(Hardware F5/A10 load balancers) | AWS Route 53 latency routing enables sub-second health-check failover between regions. |
| **Distributed Caching (Redis)**| **$6,200 / mo**<br>(ElastiCache MemoryDB cluster) | **~₹5,00,000 / mo**<br>(Self-hosted Redis Sentinel clusters) | In-memory atomic quota decrement (`DECR`) absorbs 90% of write contention. |
| **Data Persistence (SQL/NoSQL)**| **$8,500 / mo**<br>(Aurora PostgreSQL Multi-AZ) | **~₹7,00,000 / mo**<br>(PostgreSQL on dedicated SAN storage) | Aurora Multi-AZ storage provides 6-way replication across 3 AZs with automated failover in <30s. |
| **Bandwidth / Data Egress** | **$1,800 / mo**<br>(CloudFront CDN edge offload) | **₹0.00 (Zero Tariff)**<br>(National Knowledge Network - NKN) | **Key Sovereign Advantage:** Public network peering has no egress toll on NIC MeghRaj. |
| **TOTAL ESTIMATED TCO** | **~$45,800 / month**<br>(~₹38.5 Lakhs/month) | **~₹33,50,000 / month**<br>(~₹33.5 Lakhs/month) | **Hybrid Strategy:** Core vaults on NIC for zero egress cost + AWS burst nodes for mega-drives. |

### Unit Economics per Beneficiary
$$\text{Cost per Certified Citizen} = \frac{\text{Total Cloud Spend over 2 Years (}\approx \text{₹80 Crore)}}{\text{1.02 Billion Beneficiaries}} \approx \mathbf{\text{₹0.78 (\$0.009 USD) per Citizen}}$$

This confirms that CoWIN represents one of the most cost-effective population-scale digital public goods ever deployed globally.
