# Vaccination Center Lookup Service
## IT457 Course Project Component

**Assigned Responsibility:** **Darshil Gandhi** (Student ID: `202301056`) — *Service Implementation Lead*  
**Integration Contact:** **Kaushal Nandaniya** (Student ID: `202303036`) — *AWS Infrastructure Lead*  

---

### Description
This directory contains the lightweight lookup microservice specified in the Week 2 Progress Report (Section 3). It runs on port `8080` on the EC2 instances provisioned by Kaushal's CloudFormation template.

### Integration Contract with Load Balancer:
* `GET /health`: Probed every 5 seconds by the ALB Target Group. Must return HTTP 200 when healthy.
* `GET /api/v1/centers`: Lookup endpoint returning sample vaccination center availability.
* Response Headers: `X-Served-By-Zone` and `X-Instance-Id` to verify multi-zone routing.
