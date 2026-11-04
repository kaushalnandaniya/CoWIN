# IT457 Cloud Computing: Week 3 Individual Contribution Report
## CoWIN Cloud Infrastructure, Multi-AZ Networking, Load Balancing & Cost Modeling

**Course:** IT457 Cloud Computing  
**Theme:** Government & Public Digital Platforms (National / Billion-Scale Cloud Infrastructure)  
**Author:** **Kaushal Nandaniya** (Student ID: `202303036`)  
**Designated Role:** AWS Cloud Infrastructure, Networking, Topology & Cost Lead  
**Milestone:** Week 3 Deliverable (Infrastructure Configuration, IaC & Cost Analysis)  

---

> ### 📌 Work Allocation & Responsibility Boundaries
> Per **Table 5** of the approved Week 2 Progress Report, the project division is strictly defined as:
> * **Kaushal Nandaniya (202303036 — Author):** *Configure instances, networking, load balancer and health checks; capture infrastructure evidence; cost analysis.*
> * **Darshil Gandhi (202301056):** *Help build the service and test it; collect logs, screenshots and demonstration evidence.*
> * **Jeetrajsinh Gohil (202303017):** *Review deployed architecture, help conduct the failover demonstration, document observations, and coordinate team reports.*
>
> This report documents **Kaushal Nandaniya's individual contributions** for Week 3. Application microservice development and client-side testing scripts belong to Darshil Gandhi, while overall report synthesis belongs to Jeetrajsinh Gohil.

---

## 1. AWS Cloud Infrastructure & Multi-AZ Networking

To satisfy the course requirement of designing a high-availability cloud architecture for CoWIN, I engineered a redundant, two-zone cloud topology in AWS Mumbai (`ap-south-1`):

```
                                [ Public Internet Clients ]
                                             │
                                             ▼ HTTP Port 80
                    [ Application Load Balancer (ALB) ]
                     - Ingress Security Group: CoWIN-ALB-SG (Port 80 open to 0.0.0.0/0)
                     - Scheme: Internet-Facing
                     - Target Group: cowin-lookup-tg (Port 8080)
                                             │
               ┌─────────────────────────────┴─────────────────────────────┐
               ▼                                                           ▼
 [ Availability Zone A: ap-south-1a ]                    [ Availability Zone B: ap-south-1b ]
   Public Subnet A (10.0.1.0/24)                           Public Subnet B (10.0.2.0/24)
   EC2 Instance: CoWIN-Lookup-ZoneA                        EC2 Instance: CoWIN-Lookup-ZoneB
   Security Group: CoWIN-Instance-SG                       Security Group: CoWIN-Instance-SG
   (Port 8080 ONLY from ALB SG)                            (Port 8080 ONLY from ALB SG)
```

### Technical Networking Specifications
* **Virtual Private Cloud (VPC):** Custom CIDR `10.0.0.0/16` (`CoWIN-PoC-VPC`) with DNS hostnames and DNS resolution enabled.
* **Dual Availability Zone Subnets:**
  * `PublicSubnetA`: CIDR `10.0.1.0/24` pinned to AZ `ap-south-1a`.
  * `PublicSubnetB`: CIDR `10.0.2.0/24` pinned to AZ `ap-south-1b`.
* **Internet Gateway & Route Tables:** Attached an Internet Gateway (`CoWIN-PoC-IGW`) and configured default route `0.0.0.0/0` targeting the IGW across both subnet route table associations.
* **Zero-Trust Defense-in-Depth Security Groups:**
  * **ALB Security Group (`CoWIN-ALB-SG`):** Inbound HTTP 80 from `0.0.0.0/0`.
  * **Instance Security Group (`CoWIN-Instance-SG`):** Inbound HTTP 8080 restricted **strictly** to source security group `CoWIN-ALB-SG`. Direct public IP access to backend compute nodes is eliminated.

---

## 2. Load Balancing & Target Group Health Probing

The Application Load Balancer acts as the primary ingress controller and automated failure detection engine:

* **Cross-Zone Load Balancing:** Enabled across `PublicSubnetA` and `PublicSubnetB`.
* **Target Group Configuration (`cowin-lookup-tg`):**
  * Target Type: `instance`
  * Protocol & Port: `HTTP:8080`
* **Active Health Probing Rules:**
  * **Path:** `/health`
  * **Probing Interval:** `5 seconds` (production standard) / `1.0 second` (fast test config)
  * **Timeout:** `2.0 seconds`
  * **Healthy Threshold Count:** `2 consecutive successes` before target is restored into the active pool.
  * **Unhealthy Threshold Count:** `2 consecutive failures` before target is evicted.
* **Failure Eviction Behavior:** If an instance crashes or returns HTTP 500 on `/health`, the ALB detects the failure within two failed probe cycles and evicts the degraded node, immediately steering 100% of client traffic to the healthy survivor node in the second zone.

---

## 3. Infrastructure as Code (IaC) & Deployment Automation

To ensure repeatability and zero-error infrastructure provisioning, I authored automated deployment assets:

1. **Production AWS CloudFormation Template (`infrastructure/aws_cfn_cowin_two_zone.yaml`):**
   * Fully declarative YAML template provisioning VPC, subnets, route tables, security groups, ALB, Target Groups, listeners, and EC2 instances.
2. **Automated UserData Bootstrapping:**
   * Automatically queries AWS Instance Metadata Service (IMDSv2) to extract instance ID and placement availability zone dynamically.
   * Bootstraps systemd service daemon (`cowin-lookup.service`) to ensure process persistence and automated recovery upon machine restarts.
3. **Deployment CLI Helper (`infrastructure/deploy_aws.sh`):**
   * `./deploy_aws.sh deploy`: Automates CloudFormation stack creation.
   * `./deploy_aws.sh status`: Queries real-time Target Group health status via AWS CLI.
   * `./deploy_aws.sh fail-zone-a`: Issues stop signal to Zone A EC2 instance for failover demonstrations.
   * `./deploy_aws.sh recover-zone-a`: Issues start signal to restore Zone A instance.
   * `./deploy_aws.sh destroy`: Deletes all provisioned AWS resources to eliminate recurring billing.

---

## 4. Cloud Cost & Scaling Analysis

### A. Experimental PoC Infrastructure Cost (AWS Mumbai `ap-south-1`)

| AWS Resource | Configuration / Sizing | Hourly Rate (USD) | 8-Hour Demo Cost | Monthly Run Cost | Free Tier Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **EC2 Node A (`ap-south-1a`)** | `t3.micro` (2 vCPU, 1 GiB) | $0.0104 | $0.083 | $7.59 | Free (750 hrs/mo) |
| **EC2 Node B (`ap-south-1b`)** | `t3.micro` (2 vCPU, 1 GiB) | $0.0104 | $0.083 | $7.59 | Free (750 hrs/mo) |
| **EBS Storage (Zone A + B)** | 40 GB total gp3 SSD | $0.0044 | $0.035 | $3.20 | Free (up to 30 GB) |
| **Application Load Balancer** | 1 ALB across 2 AZs | $0.0225 | $0.180 | $16.43 | Free (750 hrs/mo) |
| **ALB Capacity Units (LCU)** | ~0.8 LCU average | $0.0064 | $0.051 | $4.67 | Free (15 LCUs/mo) |
| **Data Transfer (Egress)** | ~2 GB test traffic | $0.0900 / GB | $0.180 | $0.18 | Free (100 GB/mo) |
| **TOTAL** | | **$0.0541 / hr** | **$0.613** | **$39.06 / mo** | **$0.00 on Free Tier** |

### B. National-Scale TCO Model (CoWIN Scale)
Modeling CoWIN's planetary workload (1.38 billion citizens, 3.2 billion requests/day peak):
* **Commercial Hyperscaler (AWS India):** Projected at **~$45,800 / month** (400x Graviton3 `c6g.2xlarge` compute, multi-region ALBs, MemoryDB Redis clusters, and Aurora Multi-AZ database).
* **Sovereign Cloud (NIC MeghRaj):** Projected at **~Rs. 33.5 Lakhs / month**. Sovereign infrastructure offers significant financial savings due to zero-cost network peering on the National Knowledge Network (NKN).
* **Unit Economics:** Amortized platform cost was **under Rs. 0.78 ($0.009 USD) per citizen** over the entire 2-year campaign.

---

## 5. Integration Interfaces for Teammates

* **For Darshil Gandhi (202301056 — Service Implementation & Testing):**
  * Target Port: `8080` (HTTP).
  * Health contract: Service must return HTTP 200 on `/health` when healthy, and HTTP 500 when unhealthy.
  * Ingress URL: Public DNS of the ALB for executing test scripts.
* **For Jeetrajsinh Gohil (202303017 — Report Lead):**
  * The architecture diagrams, CloudFormation configuration parameters, and cost analysis tables in this report are prepared for direct inclusion into the consolidated Week 4 final report.
