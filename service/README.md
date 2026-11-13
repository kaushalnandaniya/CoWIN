# Vaccination Center Lookup Service
## IT457 Course Project Component

**Assigned Responsibility:** **Darshil Gandhi** (Student ID: `202301056`) — *Service Implementation Lead*  
**Integration Contact:** **Kaushal Nandaniya** (Student ID: `202303036`) — *AWS Infrastructure Lead*  

---

### Description
This directory contains the lightweight lookup microservice specified in the Week 2 Progress Report (Section 3). It runs on port `8080` on the EC2 instances provisioned by Kaushal's CloudFormation template.

It is zero-dependency (Python 3 standard library only), so it deploys on a
plain EC2 instance with no build step. Centers are served from a SQLite
database (`stdlib sqlite3`): the JSON dataset is loaded into the database
on first start and lookups run as SQL queries, with responses unchanged
from the original file-backed version.

### Integration Contract with Load Balancer:
* `GET /health`: Probed every 5 seconds by the ALB Target Group. Must return HTTP 200 when healthy.
* `GET /api/v1/centers`: Lookup endpoint returning sample vaccination center availability.
* Response Headers: `X-Served-By-Zone` and `X-Instance-Id` to verify multi-zone routing.

### Additional Endpoints
* `GET /metrics`: operational counters (uptime, zone health state, per-endpoint
  request counts, per-status response counts, store info, auth and rate-limit
  counters) as JSON.
* `GET|POST /simulate/fail`, `GET|POST /simulate/recover`: force the health
  check to fail/recover. **Protected by API key when `COWIN_API_KEY` is set.**

### Configuration (environment variables or CLI flags)

| Variable | Flag | Default | Purpose |
| --- | --- | --- | --- |
| `PORT` | `--port` | `8080` | Listen port |
| `AWS_AZ` | `--zone` | `ap-south-1a` | Zone reported in responses/headers |
| `AWS_INSTANCE_ID` | `--instance-id` | hostname-derived | Instance ID reported in responses/headers |
| `CENTERS_DATA_FILE` | `--data-file` | `centers_data.json` next to `app.py` | Dataset JSON, loaded into SQLite on first start |
| `CENTERS_DB_FILE` | `--db-file` | `<data file>` with `.db` suffix | SQLite database path (`:memory:` works) |
| `COWIN_API_KEY` | `--api-key` | unset | API key required via the `X-API-Key` header on `/simulate/*`. **Unset = dev mode**: endpoints stay open and a warning is logged at startup. |
| `RATE_LIMIT_RPS` | `--rate-limit-rps` | `0` (disabled) | Sustained requests/second allowed per client IP; excess gets a JSON `429` with `Retry-After` |
| `RATE_LIMIT_BURST` | `--rate-limit-burst` | `2 * RATE_LIMIT_RPS` | Token bucket size per client IP |
| `LOG_LEVEL` | `--log-level` | `INFO` | Logging verbosity |

`/health` and `/metrics` are exempt from rate limiting so ALB probes and
scrapers are never throttled. The shipped defaults (no API key, limiting
off) keep local demos and the 10 req/s failover benchmark working.

### Running under systemd
`cowin-lookup.service` is the reference unit; the CloudFormation UserData
installs an equivalent unit (`cowin.service`) with `Restart=always`, so the
service comes back automatically after a crash or reboot. Optional
configuration lives in `/etc/default/cowin-lookup` (created by the UserData
with commented examples).
