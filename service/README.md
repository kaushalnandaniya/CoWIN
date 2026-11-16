# Vaccination Center Lookup Service
## IT457 Course Project Component

**Owner:** **Jeetrajsinh Gohil** (Student ID: `202303017`) - backend and frontend  
**Observability and data layer:** **Kaushal Nandaniya** (Student ID: `202303036`)  
**Deployment contact:** **Darshil Gandhi** (Student ID: `202301056`) - AWS infrastructure  

---

### Description
This directory contains the lightweight lookup microservice specified in the Week 2 Progress Report (Section 3). It runs on port `8080` on the EC2 instances provisioned by the CloudFormation template.

It is zero-dependency (Python 3 standard library only), so it deploys on a
plain EC2 instance with no build step. Centers are served from a SQLite
database (`stdlib sqlite3`): the JSON dataset is loaded into the database
on first start and lookups run as SQL queries, with responses unchanged
from the original file-backed version.

### Integration Contract with Load Balancer:
* `GET /health`: Probed every 5 seconds by the ALB Target Group. Returns HTTP 200 only when the node can serve lookups: the center store is reachable and the real dataset is loaded. A dataset-load failure serves the fallback record but reports HTTP 500 (not ready), so the ALB drains the node instead of clients silently getting one hardcoded sample center.
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
| `COWIN_API_KEY` | `--api-key` | unset | API key required via the `X-API-Key` header on `/simulate/*`. **Unset = dev mode**: endpoints stay open and a warning is logged at startup. A blank value is treated as unset, so an empty key can never match a missing header while `/metrics` reports auth enabled. |
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
configuration lives in `/etc/default/cowin-lookup` (created by the bootstrap
with the required `COWIN_API_KEY` and commented examples).

## Read-only deployment verification

On each EC2 node, the existing service package needs `app.py`,
`centers_data.json`, Python 3 and the systemd unit. Use the CloudFormation
UserData in `infrastructure/` rather than installing a competing
second unit. Configuration and the SQLite database path must be writable by the
service user. Inspect `systemctl status cowin` and `journalctl -u cowin` on that
node; the standalone reference unit uses the name `cowin-lookup` instead.

From a client that can reach the ALB:

```bash
python3 service/verify_deployment.py --url "$ALB_URL"
```

This checks `/health`, lookup JSON and zone/instance response headers with 20
read requests, then prints a timestamped summary. Exit 0 means at least two
zones were observed, exit 1 means only one was observed in those samples, and
exit 2 is a contract/connection failure. A one-zone sample does not prove the
other node is down. Verify both ALB targets, their EC2 Availability Zones and
security groups separately. The verifier never provisions or stops anything.

Keep `/simulate/*` protected or restricted in a live deployment. Local health
simulation and a real EC2 instance-stop are different experiments. See
`benchmark/README.md` for the manual event workflow and measurement limits.

## Lookup frontend

The service also serves a small, dependency-free frontend at **`/ui/`**
(`http://localhost:8080/ui/` when running locally). Start the service normally:

```bash
python3 service/app.py
```

The page requests the same origin's `/api/v1/centers`, with optional `district`
and `pincode` query parameters. Both filters can be combined. It shows sample
sessions, the serving zone and instance from that lookup response, and explicit
loading, empty and retryable error states. Requests time out after 10 seconds.
There is no background polling, external CDN, build step or JavaScript package.
All dataset strings are inserted as text, not interpreted as HTML.

This is a course demo, not the official CoWIN portal or a booking service.
Dates and capacity values come directly from the static sample dataset and
must not be presented as live availability. A successful lookup does not prove
both zones are healthy or that a failover test passed. No failure controls or
API keys are exposed by the frontend.

### Deployment

Copy the entire `service/static/` directory alongside `app.py` on **both**
servers. With the supplied systemd layout this is `/opt/cowin/static/`.
Restart the service after installing the updated `app.py`. Allow `/ui/` and its
assets through the ALB listener to the same target group as the API. The public
frontend URL is the ALB address followed by `/ui/`.

The CloudFormation template embeds no application copies: each node fetches
`app.py`, `centers_data.json` and the three static assets from the repository
at the `AppRepoRef` parameter (a commit SHA, pinned by `deploy_aws.sh` to the
checked-out HEAD) at first boot. Deploying an updated frontend or service is
therefore a fresh stack deploy at the new ref; running stacks do not pick up
repository changes on their own.

`/` and `/info` remain JSON for compatibility. Only the explicitly allowlisted
`/ui`, `/ui/`, `/ui/index.html`, `/ui/styles.css` and `/ui/app.js` routes serve
files. Other paths keep the API's JSON 404 response. Missing assets return a
JSON 503, rather than exposing files outside that directory.

### Browser views and API responses

Browser requests that explicitly accept `text/html` get styled views at `/`
(or `/info`), `/health`, `/api/v1/centers` (or `/centers`), `/metrics`, and the
404 fallback. Requests without that media type keep the JSON contract.
Explicit JSON preferences and `text/html;q=0` also keep JSON. Both variants
send `Vary: Accept`, and HTML errors preserve their HTTP error status.

Deploy `pages.py` alongside `app.py`, plus the complete `static/` directory.
The browser views share `/ui/styles.css`; no new runtime packages are needed.
