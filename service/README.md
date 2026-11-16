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
  two `fail` requests without intervening recovery cannot both be accepted.
  One or both are refused. Local fail/recover/timer transitions are serialized;
  a rejected intent is rolled back before a response is written. A simulated failure
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
with peer/zone configuration and commented examples; the operator adds the key).

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
# Terminal 1: replace <ALB DNS name> with the stack LoadBalancerDNSName output.
# Two forwards over node A: ALB on 8080, node A on 8081.
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:<ALB DNS name>:80 \
  -L 127.0.0.1:8081:localhost:8080 ec2-user@<zone A public IP>
# Terminal 2: node B on 8082.
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8082:localhost:8080 ec2-user@<zone B public IP>
# Open http://localhost:8081/admin/
# Apply endpoints: ALB=http://localhost:8080 A=http://localhost:8081 B=http://localhost:8082
```

Use `-i <private-key-file>` if the EC2 key is not already in your SSH agent.
All three browser endpoints are loopback forwards. The page, node health
polls, ALB health polls and API-key control requests cross the browser-to-AWS
hop inside SSH. On AWS, the ALB forward and peer health probes use HTTP;
this is not end-to-end TLS. The API key goes only to the selected node,
not the ALB. Keep both SSH sessions running during the drill.

When `COWIN_API_KEY` is set, type the key into the panel; it is sent as
`X-API-Key` and is not persisted by the page. Endpoint addresses are saved
in localStorage and may also be set with `?alb=&a=&b=`. **Check all endpoint
fields before entering the key**: the page permits arbitrary URLs and does
not enforce loopback-only destinations. Never load the panel over public
HTTP or point a node control endpoint at a public HTTP URL. CORS allows
the loopback panel to control the other loopback node port.

With the default finite 120-second setting, an accepted failure gets one
auto-recover timer. Concurrent duplicate Stop requests on the same node
are refused and do not replace that timer. A refused peer check, including
a disconnected client, leaves no failure intent behind. A process restart
clears simulated state. These are process-local controls, not an AWS-wide
availability guarantee. Timer execution can be delayed if the process is
stalled; `0` explicitly disables auto-recovery. The panel's Stop/Recover
buttons do not stop/start EC2 instances.

## Operator runbook and limits (live deployment)

The drill key is never in the template, UserData or the repo: UserData is
readable via the console and describe-instances, so `COWIN_API_KEY` is
set by the operator over SSH after boot (`deploy_aws.sh` prints these
steps after a deploy):

```bash
# pick a 16+ char key, keep it in a password manager - never in chat
# Run on BOTH nodes. Use 16+ ASCII letters/digits/-/_ (no spaces/quotes).
# read avoids placing the key in shell history; tee output is suppressed.
sudo chmod 600 /etc/default/cowin-lookup
read -rsp 'Drill key: ' COWIN_API_KEY; printf '\n'
printf 'COWIN_API_KEY=%s\n' "$COWIN_API_KEY" | sudo tee -a /etc/default/cowin-lookup >/dev/null
unset COWIN_API_KEY
sudo systemctl restart cowin
```

Operator access itself comes from the `OperatorKeyPair` (an existing EC2
key pair) plus port 22 scoped to a single `/32` (`OperatorSshCidr`) in
the template. Explicit limits for anyone holding the key:

- Drill one zone at a time. Do not race Recover against a different zone's
  Stop; the peer-health check is not a distributed transaction.
- Each accepted failure arms `COWIN_SIM_AUTO_RECOVER_SECONDS`
  (default 120 s) and halves capacity until recovery; a repeated Stop
  while a failure is active is refused with 409, so the window cannot
  be extended by spamming the button.
- The key only ever travels inside the SSH tunnel; never paste it into
  chat, tickets or the public site.
- When the demo is done, close tunnels and stop instances as approved.
  The ALB still exists and remains billable until the stack is deleted.

### Stack updates and pinned-IP replacement

The instance bootstraps now live in two EC2 launch templates. Each instance
references its template's explicit `LatestVersionNumber`; CloudFormation
replaces the instance when that version changes. Both bootstraps include
both private-IP parameters, so changing either IP changes **both** versions
and replaces **both** nodes. Both fresh nodes run cloud-init with current
peer URLs. There is no old surviving node with a stale peer configuration.
Changing AppRepoRef or bootstrap code similarly installs a fresh artifact
through replacement instead of relying on a restart to rerun UserData.

For EBS-backed instances, a direct EC2 `UserData` update only restarts the
instance; first-boot shell scripts do not automatically rerun. That is why
this template uses launch-template-version replacement instead.

Before a replacing update (including migration from the pre-launch-template
PR template, bootstrap/AppRepoRef changes, key-pair or AMI changes):

1. Obtain authorization and schedule a maintenance window. This design does
   not guarantee a rolling or outage-free update. Do not run drills during it.
2. Choose **two fresh, free** private IPs, one in `10.0.1.0/24`, the other in
   `10.0.2.0/24`. Check EC2 network-interface allocations, including old stack
   instances. Avoid subnet-reserved addresses. Do not reuse occupied IPs.
3. Review a CloudFormation change set with **both** `ZoneAPrivateIp` and
   `ZoneBPrivateIp` set to the new values. Confirm replacement of both nodes,
   current AppRepoRef, key pair, operator /32 and unchanged ALB deny rule.
   The create-only deploy helper is not an update command. The template
   cannot verify that parameter addresses are free; this check is manual.
4. Only after separate approval, execute that change set. New nodes are
   created before old nodes are deleted. Reusing either old IP can make the
   update fail. Do not terminate existing nodes as a shortcut.
5. After completion, get both new instance IDs/public IPs. Reinstall the drill
   key on **both** nodes over SSH, verify `COWIN_ZONE_LETTER=a/b` and that each
   `COWIN_PEER_URL` uses the other's new private IP, then restart cowin.
6. Verify both /health endpoints, ALB target health, and public /simulate/*403
   before any separately approved drill. Reopen all three forwards using the
   new public IPs. If rollback occurs, inspect the actual live IPs, config and
   key setup again before resuming; do not assume the old topology survived.

Nodes start in dev mode before key provisioning. Network restrictions and
the ALB deny rule are still required; the API key is defense in depth, not a
replacement for those controls. Launch templates add no billable service,
but temporary overlapping EC2 nodes and the ALB can incur charges. This
update path is statically checked and linted, not live-AWS tested here.

References: [EC2 UserData lifecycle](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-instance.html),
[launch-template version replacement](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ec2-instance-launchtemplatespecification.html),
[first-boot scripts](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html).

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
