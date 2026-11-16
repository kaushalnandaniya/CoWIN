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
* `GET|POST /simulate/<action>` (`fail`, `recover`): force the health
  check to fail/recover. **Protected by API key when `COWIN_API_KEY` is set.**
  Operators reach the node directly - locally by its own address, on AWS
  through an SSH tunnel (the ALB denies every `/simulate/*` with 403) -
  and call the zone-pinned path `/simulate/zone-<a|b>/<action>`; the node
  checks the zone letter and answers `409` on a mismatch, so a command
  can never flip the wrong zone. A node refuses `fail` while its peer
  zone is unhealthy (peer state read from `COWIN_PEER_URL`; an
  unreachable peer also refuses). The interlock is intent-first with
  rollback: a node marks its own failure before consulting the peer, so
  two simultaneous `fail` commands can never leave both zones down - the
  loser gets a `409`, and a dead heat refuses both. A simulated failure
  auto-recovers after `COWIN_SIM_AUTO_RECOVER_SECONDS`
  (default 120) even if nobody recovers it.

### Configuration (environment variables or CLI flags)

| Variable | Flag | Default | Purpose |
| --- | --- | --- | --- |
| `PORT` | `--port` | `8080` | Listen port |
| `AWS_AZ` | `--zone` | `ap-south-1a` | Zone reported in responses/headers |
| `AWS_INSTANCE_ID` | `--instance-id` | hostname-derived | Instance ID reported in responses/headers |
| `CENTERS_DATA_FILE` | `--data-file` | `centers_data.json` next to `app.py` | Dataset JSON, loaded into SQLite on first start |
| `CENTERS_DB_FILE` | `--db-file` | `<data file>` with `.db` suffix | SQLite database path (`:memory:` works) |
| `COWIN_API_KEY` | `--api-key` | unset | API key required via the `X-API-Key` header on `/simulate/*`. **Unset = dev mode**: endpoints stay open and a warning is logged at startup. A blank value is treated as unset, so an empty key can never match a missing header while `/metrics` reports auth enabled. |
| `COWIN_ZONE_LETTER` | `--zone-letter` | trailing letter of `AWS_AZ` | Zone letter the node claims on zone-pinned `/simulate/zone-<letter>/*` calls; a mismatch answers `409` |
| `COWIN_PEER_URL` | `--peer-url` | unset | Base URL of the peer zone's node. When set, `fail` is refused (`409`) while the peer is unhealthy or unreachable |
| `COWIN_SIM_AUTO_RECOVER_SECONDS` | `--sim-auto-recover-seconds` | `120` | Seconds before a simulated failure recovers itself; `0` disables the timer |
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

Keep `/simulate/*` protected or restricted in a live deployment: the ALB
keeps its 403, operator access runs over SSH tunnels, and the node still
gates on the API key. Repeated failures cut the site's capacity in half
for up to two minutes each time. Local health
simulation and a real EC2 instance-stop are different experiments. See
`benchmark/README.md` for the manual event workflow and measurement limits.

## Admin console

**`/admin/`** (`http://localhost:8081/admin/` on a local node) is a small live
operations page for the two-zone demo: it polls each node's `/health` and the
load balancer, draws the topology with each zone's current state and the
serving path, and offers **Stop/Recover** buttons for both zones. The
commands go straight to each zone's own endpoint
(`/simulate/zone-<letter>/<action>`), so a drill can only reach the
intended zone. On the real AWS deployment the ALB denies `/simulate/*`
with 403, so the operator opens one SSH tunnel per node and loads the
panel ITSELF through a tunnel - the page code must not come over the
public HTTP path either:

```bash
ssh -L 8081:localhost:8080 ec2-user@<zone A public IP>
ssh -L 8082:localhost:8080 ec2-user@<zone B public IP>
# then open http://localhost:8081/admin/ and set endpoint B to http://localhost:8082
```

Everything the browser sends - page load, health polls, the API key -
now travels inside SSH. The endpoint A field already matches the
panel's own origin; endpoint B is cross-origin loopback, which the
node's CORS headers allow. When the node runs with `COWIN_API_KEY`, type
the key into the page; it is sent as the `X-API-Key` header and kept only
in memory. A simulated failure auto-recovers after about 2 minutes even
if Recover is never pressed (repeating Stop while a failure is active is
refused - the window cannot be extended), and while one zone is degraded
the other zone's Stop is refused with a 409. Endpoint addresses default
to the local simulator topology from `benchmark/run_experiment.sh`
(localhost 8080/8081/8082) and can be changed in the page or via
`?alb=&a=&b=` query parameters.

## Operator runbook and limits (live deployment)

The drill key is never in the template, UserData or the repo: UserData is
readable via the console and describe-instances, so `COWIN_API_KEY` is
set by the operator over SSH after boot (`deploy_aws.sh` prints these
steps after a deploy):

```bash
# pick a 16+ char key, keep it in a password manager - never in chat
echo 'COWIN_API_KEY=<the key>' | sudo tee -a /etc/default/cowin-lookup
sudo systemctl restart cowin   # on BOTH nodes
```

Operator access itself comes from the `OperatorKeyPair` (an existing EC2
key pair) plus port 22 scoped to a single `/32` (`OperatorSshCidr`) in
the template. Explicit limits for anyone holding the key:

- Drill one zone at a time; the interlock refuses a second zone anyway.
- Each accepted failure lasts at most `COWIN_SIM_AUTO_RECOVER_SECONDS`
  (default 120 s) and halves capacity for that window; a repeated Stop
  while a failure is active is refused with 409, so the window cannot
  be extended by spamming the button.
- The key only ever travels inside the SSH tunnel; never paste it into
  chat, tickets or the public site.
- When the demo is done, stop the instances; there is no ALB surface to
  unwind.

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
`app.py`, `pages.py`, `centers_data.json` and the static assets from the repository
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
