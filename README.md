# CoWIN Two-Zone High-Availability Proof of Concept

A case study of the CoWIN vaccination platform's availability architecture, built for
IT457 Cloud Computing. The project reproduces the core availability pattern behind a
national-scale public platform - stateless service nodes in two availability zones
behind a load balancer with aggressive health checking - as a deployable AWS
proof of concept, plus a local simulator that reproduces the same failover behavior
without an AWS account.

## Architecture

The production topology is defined as infrastructure as code in
[`infrastructure/aws_cfn_cowin_two_zone.yaml`](infrastructure/aws_cfn_cowin_two_zone.yaml)
and deploys into AWS Mumbai (`ap-south-1`):

```
                        Internet
                            │
                  Application Load Balancer
                  (internet-facing, port 8080)
                            │
                Target Group: health check
                GET /health every 5s
                (timeout 2s, thresholds 2/2)
                    │               │
            ┌───────┘               └────────┐
     ap-south-1a                      ap-south-1b
     EC2 t3.micro                     EC2 t3.micro
     lookup service :8080             lookup service :8080
```

Key properties:

- **Isolation.** Instances sit in a custom VPC (`10.0.0.0/16`) with security groups
  that accept traffic on port 8080 only from the load balancer's security group.
  Nothing else reaches the nodes.
- **Health-gated routing.** The target group probes `/health` every 5 seconds and
  removes a target after 2 consecutive failures. The service exposes a
  `/simulate/fail` switch so a zone failure can be injected deterministically.
- **Stateless nodes.** Every node serves the same dataset, so failover and recovery
  lose no state: RPO is zero by construction.

The service itself ([`service/`](service/)) is a zero-dependency Python 3 lookup
service with two endpoints, `GET /health` and `GET /api/v1/centers`, and tags every
response with `X-Served-By-Zone` and `X-Instance-Id` headers so traffic distribution
across zones is directly observable.

## Quickstart

### Local failover experiment (no AWS required)

```bash
./benchmark/run_experiment.sh
```

This starts two service nodes and a local ALB simulator, waits for every component
to report ready, injects a zone failure mid-run, and records latency, zone
distribution, and failover transitions into `benchmark/benchmark_results.json` and
`benchmark/benchmark_requests.csv`. See [`benchmark/README.md`](benchmark/README.md)
for the harness design.

### AWS deployment

```bash
./infrastructure/deploy_aws.sh deploy        # create the stack (~4 min)
./infrastructure/deploy_aws.sh status        # target group health
./infrastructure/deploy_aws.sh fail-zone-a   # stop the Zone A instance
```

Requires the AWS CLI configured for `ap-south-1`.

## Verified results (local simulator)

Latest committed run ([`benchmark/benchmark_results.json`](benchmark/benchmark_results.json)),
32 seconds at 10 requests/second with a zone failure injected at t=10s:

| Metric | Value |
| --- | --- |
| Requests | 320 / 320 successful (0 failed) |
| Failover detection and traffic shift | 2.1 s |
| Disruption window (client-visible errors) | 0.0 s |
| Recovered node re-admitted to rotation | ~2 s after recovery (t≈24.0s) |
| Latency p50 / p99 | 1.07 ms / 1.92 ms |

RTO is 2.1 seconds against a 5-second health-check interval; RPO is zero because the
service is stateless. These numbers come from the local ALB simulator, which
reproduces the target-group health-check semantics of the CloudFormation template;
they characterize the failover logic, not AWS network behavior.

## Cost and scaling

Full analysis in [`docs/week-3/COST_AND_SCALING_ANALYSIS.md`](docs/week-3/COST_AND_SCALING_ANALYSIS.md):

- The two-zone PoC runs at **$0.00/month on the AWS Free Tier**, or about
  **$0.054/hour (~$0.61 for an 8-hour demo)** at commercial rates.
- The national-scale model prices a multi-region active-active deployment on AWS at
  **~$45,800/month**, and a sovereign-cloud alternative (NIC MeghRaj) at
  **~₹60–75 lakh/month** with no egress charges.

## Repository layout

```
infrastructure/   CloudFormation template and deploy/failover automation
service/          Lookup microservice, dataset, systemd unit
benchmark/        ALB simulator, failover benchmark runner, results, plots
docs/             Weekly reports, cost analysis, team work division
```

- Week 1 research summary: [`docs/week-1/`](docs/week-1/)
- Week 2 design and progress report: [`docs/week-2/`](docs/week-2/)
- Week 3 infrastructure report and cost analysis: [`docs/week-3/`](docs/week-3/)

## Team

| Member | Student ID | Domain |
| --- | --- | --- |
| Kaushal Nandaniya ([@kaushalnandaniya](https://github.com/kaushalnandaniya)) | 202303036 | AWS infrastructure, networking, cost analysis |
| Darshil Gandhi | 202301056 | Service implementation, testing harness |
| Jeetrajsinh Gohil ([@jeetrex17](https://github.com/jeetrex17)) | 202303017 | Architecture coordination, reports, failover analysis; failover benchmark fix ([#1](https://github.com/kaushalnandaniya/CoWIN/pull/1), merged), service hardening and test suite ([#3](https://github.com/kaushalnandaniya/CoWIN/pull/3), in review) |

Responsibility boundaries and milestone commitments are documented in
[`docs/team/TEAM_WORK_DIVISION.md`](docs/team/TEAM_WORK_DIVISION.md).
