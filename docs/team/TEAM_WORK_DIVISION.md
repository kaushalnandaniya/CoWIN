# Team Work Division

**Project:** CoWIN two-zone high-availability proof of concept (IT457 Cloud Computing)
**Theme:** Government and Public Digital Platforms
**Team size:** 3

## Team

| Member | Student ID | GitHub | Focus |
| :--- | :---: | :--- | :--- |
| Jeetrajsinh Gohil | 202303017 | [@jeetrex17](https://github.com/jeetrex17) | Backend, frontend, test tooling |
| Kaushal Nandaniya | 202303036 | [@kaushalnandaniya](https://github.com/kaushalnandaniya) | Backend observability, architecture, reports, cost and scaling |
| Darshil Gandhi | 202301056 | [@darshil-2005](https://github.com/darshil-2005) | AWS infrastructure, deployment, benchmarking, evidence |

## Scope

The course guide does not expect a miniature national platform. The project demonstrates high availability and disaster recovery through three parts:

- **National-scale design:** multi-region DNS routing, regional load balancers and multi-zone application clusters, documented as an architecture and cost model.
- **Working PoC:** an Application Load Balancer in front of two EC2 nodes in separate availability zones in `ap-south-1`, each running the lookup service.
- **Failover validation:** controlled loss of one zone, with measured detection time, client-visible errors and recovery.

## Member contributions

Each member owns one layer of the system: application, design and documentation, and infrastructure and evidence. Shared work is listed separately below.

### Jeetrajsinh Gohil

Domain: backend

- Lookup API, routing and request validation
- Persistent SQLite store and API-key protection on failure-injection endpoints
- Structured logging, graceful shutdown, threaded serving and JSON error handling
- systemd supervision and alignment of the service with the CloudFormation bootstrap

Domain: frontend

- Responsive lookup UI at `/ui/` with validation and clear sample-data disclaimers
- Route views for centers, health, metrics, info and not-found pages

Domain: test tooling

- Unit, regression and frontend smoke suites for the service, run through `make test`

### Kaushal Nandaniya

Domain: backend

- Dataset and data-access layer for vaccination centres
- Observability: `/metrics` counters, latency tracking and zone headers
- Optional request rate limiting

Domain: architecture and reports

- National-scale reference architecture, failure-domain analysis and RTO/RPO reasoning
- Weekly progress reports, final report and repository documentation
- Week 1 case-study summary and architecture extraction

Domain: cost and scaling

- Cost model for the PoC and for a multi-region national deployment
- Comparison of commercial cloud and sovereign-cloud options

### Darshil Gandhi

Domain: AWS infrastructure

- VPC, public subnets across two availability zones, security groups scoped to the load balancer, target group and 5-second `/health` checks
- CloudFormation template and deploy, status and zone-failure automation (`infrastructure/`)
- EC2 sizing and instance bootstrap for the service

Domain: deployment and operations

- Provisioning, lifecycle and teardown of the two-zone stack
- Read-only two-zone deployment verification (`service/verify_deployment.py`)

Domain: benchmarking and failover evidence

- Local ALB simulator, failover benchmark runner and event-timing correctness
- Timestamped evidence workflow, request-level logs, latency percentiles and timeline plots
- Real AWS failover run, raw samples, AWS-side timeline and evidence pack

## Shared work

- Weekly reports and the final report: Kaushal compiles them; each member supplies the sections for the layer they own.
- Real AWS failover run: Darshil provisions and operates the stack and captures the evidence, Jeetraj supplies the service build and failure-injection endpoints, Kaushal analyses the timeline for the report.
- Code review: every change is reviewed by a member other than its author.

## Milestones

| Week | Jeetrajsinh Gohil | Kaushal Nandaniya | Darshil Gandhi |
| :--- | :--- | :--- | :--- |
| 1 | Source review and governance notes | Architecture extraction and summary | Cost data and metrics compilation |
| 2 | Service design and API contract | National architecture diagram and progress report | AWS topology design and failover test plan |
| 3 | Backend hardening, frontend and tests | Metrics, rate limiting, data layer and RTO/RPO analysis | VPC, EC2, ALB deployment, benchmark and AWS failover run |
| 4 | Service and UI polish, test suites | Final report, cost audit and documentation | Infrastructure sections, result graphs and evidence pack |

## Failover test procedure

1. Send continuous HTTP requests to the ALB DNS name.
2. Confirm both targets report `healthy`.
3. Stop the Zone A instance.
4. Record the stop time, the ALB `healthy` to `unhealthy` transition and the client response codes.
5. Measure the disruption window, from the first error until requests route reliably to Zone B.
6. Start the Zone A instance and record its return to rotation.
