#!/usr/bin/env python3
"""
CoWIN Vaccination Center Lookup Microservice
Component for IT457 Cloud Computing Two-Zone Failover Proof-of-Concept.

Zero external dependencies - runs on standard Python 3.

Hardened service shape (behavior-compatible with the original PoC service):
- Configuration via environment variables, overridable with CLI flags
- Structured logging through the logging module (level via LOG_LEVEL)
- Graceful shutdown on SIGTERM/SIGINT (systemd-friendly)
- Request error handling: unexpected errors become JSON 500s instead of
  dropped connections; a malformed pincode filter is a JSON 400
- Threaded HTTP server so ALB health probes and client traffic do not
  queue behind each other; mutable runtime state is guarded by a lock

Production-readiness additions (still zero external dependencies):
- SQLite-backed center store (stdlib sqlite3): the JSON dataset is loaded
  into a real database on first start and /api/v1/centers is served from
  it, byte-compatible with the original file-backed responses
- API-key authentication for the mutating /simulate/* endpoints via the
  X-API-Key header (COWIN_API_KEY; unset = dev mode with a startup warning)
- Per-client-IP token-bucket rate limiting (RATE_LIMIT_RPS /
  RATE_LIMIT_BURST; 0 disables) with JSON 429s; /health and /metrics exempt
- /metrics endpoint: uptime, zone health state, request/response counters,
  store info, and rate-limit counters for monitoring
- Readiness-aware /health: HTTP 200 only when the node can serve lookups
  (center store reachable, real dataset loaded). A dataset-load failure
  serves the fallback record but reports NOT READY so the ALB drains the
  node instead of clients silently getting one hardcoded center.
"""

import argparse
import pages
import hmac
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
import signal
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("cowin-lookup")

DEFAULT_PORT = 8080
DEFAULT_ZONE = "ap-south-1a"
SERVICE_VERSION = "CoWIN-LookupService/1.0"

# Exact allowlist: never map arbitrary URL paths onto the filesystem.
STATIC_FILES = {
    "/ui": ("index.html", "text/html; charset=utf-8"),
    "/ui/": ("index.html", "text/html; charset=utf-8"),
    "/ui/index.html": ("index.html", "text/html; charset=utf-8"),
    "/ui/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/admin": ("admin.html", "text/html; charset=utf-8"),
    "/admin/": ("admin.html", "text/html; charset=utf-8"),
    "/ui/admin.css": ("admin.css", "text/css; charset=utf-8"),
    "/ui/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
}
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Mutating endpoints gated behind the X-API-Key header when COWIN_API_KEY
# is configured. Read endpoints (health, lookup, info, metrics) stay open.
AUTH_HEADER = "X-API-Key"
PROTECTED_PATHS = frozenset({"/simulate/fail", "/simulate/recover"})

# Default bound on a simulated failure: the node restores its own health
# this many seconds after /simulate/fail, so a demo can never be left
# degraded by accident. 0 disables the timer. Overridable via
# COWIN_SIM_AUTO_RECOVER_SECONDS.
DEFAULT_SIM_AUTO_RECOVER_SECONDS = 120.0


def parse_simulate_path(path):
    """Parse a simulation control path.

    '/simulate/fail'              -> ('fail', None)
    '/simulate/zone-a/recover'    -> ('recover', 'a')
    anything else                 -> (None, None)

    The zone-qualified form is what the load balancer's zone-pinned
    listener rules forward; the node verifies the letter against its own
    configured zone so a misrouted command can never flip the wrong zone.
    """
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "simulate" and parts[1] in ("fail", "recover"):
        return parts[1], None
    if (len(parts) == 3 and parts[0] == "simulate"
            and parts[1] in ("zone-a", "zone-b") and parts[2] in ("fail", "recover")):
        return parts[2], parts[1][-1]
    return None, None


def is_protected_path(path):
    """True for every mutating /simulate/* path, zone-qualified or not."""
    action, _ = parse_simulate_path(path)
    return action is not None

# Paths exempt from rate limiting: ALB health probes and metrics scrapers
# must never be throttled, or failover detection would break.
RATE_LIMIT_EXEMPT_PATHS = frozenset({"/health", "/metrics"})

# Longest accepted district filter; longer values are rejected as 400.
MAX_DISTRICT_FILTER_LENGTH = 100

# Sample record served if the centers dataset cannot be loaded. Serving
# it marks the node NOT READY: /health fails so the ALB drains the node
# instead of clients silently getting one hardcoded center.
FALLBACK_CENTERS = [
    {
        "center_id": 563001,
        "name": "Civil Hospital Asarwa CVC",
        "pincode": 380016,
        "district_name": "Ahmedabad",
        "fee_type": "Free",
        "sessions": [{"vaccine": "COVISHIELD", "available_capacity": 150}]
    }
]


class ServiceConfig:
    """Static configuration resolved from environment variables and CLI args."""

    def __init__(self, host="0.0.0.0", port=DEFAULT_PORT, zone=DEFAULT_ZONE,
                 instance_id=None, data_file=None, db_file=None, api_key=None,
                 rate_limit_rps=0.0, rate_limit_burst=None, zone_letter=None,
                 peer_url=None, auto_recover_seconds=None):
        self.host = host
        self.port = port
        self.zone = zone
        self.instance_id = instance_id or f"i-{socket.gethostname()[:8]}"
        # A blank configured key must not act like a real one: normalize it
        # to "unconfigured" so the auth gate and the startup warning
        # agree. Previously an empty COWIN_API_KEY accepted a
        # missing X-API-Key header as if no key were configured.
        if api_key is not None and not str(api_key).strip():
            api_key = None
        self.api_key = api_key
        # Short letter identifying this node's zone ('a' for ap-south-1a).
        # Used to verify zone-pinned /simulate/zone-<letter>/* commands.
        # Defaults to the trailing letter of the zone name.
        if zone_letter is None:
            zone_letter = (zone or "a").rstrip()[-1:].lower() or "a"
        self.zone_letter = zone_letter
        # Base URL of the sibling zone's node (e.g. http://10.0.2.x:8080).
        # When set, /simulate/fail is refused while the peer is unhealthy,
        # so both zones can never be degraded at once.
        self.peer_url = (peer_url or "").strip().rstrip("/") or None
        if auto_recover_seconds is None:
            auto_recover_seconds = DEFAULT_SIM_AUTO_RECOVER_SECONDS
        self.auto_recover_seconds = float(auto_recover_seconds)
        self.rate_limit_rps = float(rate_limit_rps or 0.0)
        self.rate_limit_burst = (float(rate_limit_burst) if rate_limit_burst
                                 else None)
        if data_file is None:
            data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "centers_data.json")
        self.data_file = data_file
        if db_file is None:
            db_file = os.path.splitext(data_file)[0] + ".db"
        self.db_file = db_file

    @classmethod
    def from_env(cls):
        """Config from environment only (used when embedding the service)."""
        return cls(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", DEFAULT_PORT)),
            zone=os.environ.get("AWS_AZ", DEFAULT_ZONE),
            instance_id=os.environ.get("AWS_INSTANCE_ID"),
            data_file=os.environ.get("CENTERS_DATA_FILE"),
            db_file=os.environ.get("CENTERS_DB_FILE"),
            api_key=os.environ.get("COWIN_API_KEY"),
            zone_letter=os.environ.get("COWIN_ZONE_LETTER"),
            peer_url=os.environ.get("COWIN_PEER_URL"),
            auto_recover_seconds=os.environ.get("COWIN_SIM_AUTO_RECOVER_SECONDS"),
            rate_limit_rps=float(os.environ.get("RATE_LIMIT_RPS", 0.0)),
            rate_limit_burst=(float(os.environ["RATE_LIMIT_BURST"])
                              if os.environ.get("RATE_LIMIT_BURST") else None),
        )


class ServiceState:
    """Mutable runtime state, guarded so threaded handlers stay consistent."""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.request_count = 0
        self.force_unhealthy = False

        self.requests_by_endpoint = {}
        self.responses_by_status = {}

    def record_request(self):
        with self._lock:
            self.request_count += 1
            return self.request_count

    def record_response(self, path, status_code):
        with self._lock:
            self.requests_by_endpoint[path] = \
                self.requests_by_endpoint.get(path, 0) + 1
            self.responses_by_status[status_code] = \
                self.responses_by_status.get(status_code, 0) + 1

    def response_snapshot(self):
        """Consistent copies of the response counters, for /metrics."""
        with self._lock:
            return (dict(sorted(self.requests_by_endpoint.items())),
                    dict(self.responses_by_status))

    def set_unhealthy(self, flag):
        with self._lock:
            self.force_unhealthy = bool(flag)

    def is_unhealthy(self):
        with self._lock:
            return self.force_unhealthy

    def uptime(self):
        return round(time.time() - self.start_time, 2)

    def total_requests(self):
        with self._lock:
            return self.request_count


def load_centers(data_file):
    """Load the centers dataset as (centers, used_fallback).

    A load failure is loud: it logs at ERROR and marks the store degraded
    so readiness checks fail instead of silently serving the fallback
    sample record.
    """
    try:
        with open(data_file, "r") as f:
            centers = json.load(f)
        logger.info("Loaded %d centers from %s", len(centers), data_file)
        return centers, False
    except Exception as e:
        logger.error("Could not load centers data from %s (%s); "
                     "serving fallback sample record and reporting not ready",
                     data_file, e)
        return FALLBACK_CENTERS, True


def _store_health(count, used_fallback):
    """Readiness decision shared by both store backends."""
    if used_fallback:
        return {"ok": False,
                "detail": "centers dataset failed to load; "
                          "serving the fallback sample record",
                "centers": count}
    if count == 0:
        return {"ok": False, "detail": "no centers loaded", "centers": 0}
    return {"ok": True, "detail": "ok", "centers": count}


def _escape_like(value):
    """Escape LIKE wildcards so filters keep plain substring semantics."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CenterStore:
    """SQLite-backed store for the centers dataset.

    The JSON dataset is loaded into a real database the first time the
    service starts; afterwards the database is the source of truth and is
    only re-populated when it is empty. Lookups run as SQL queries and
    return the same records, in dataset order, as the original
    file-backed version.
    """

    backend = "sqlite"

    def __init__(self, db_file, data_file):
        self._db_file = db_file
        self._lock = threading.Lock()
        self._used_fallback = False
        self._conn = sqlite3.connect(db_file, check_same_thread=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS centers (
                    center_id     INTEGER PRIMARY KEY,
                    position      INTEGER NOT NULL,
                    pincode       INTEGER,
                    district_name TEXT,
                    payload       TEXT NOT NULL
                )
                """
            )
        if self.count() == 0:
            self._load(data_file)

    def _load(self, data_file):
        centers, self._used_fallback = load_centers(data_file)
        rows = [
            (c.get("center_id"), position, c.get("pincode"),
             c.get("district_name"), json.dumps(c))
            for position, c in enumerate(centers)
        ]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO centers "
                "(center_id, position, pincode, district_name, payload) "
                "VALUES (?, ?, ?, ?, ?)", rows)
        logger.info("Loaded %d centers into SQLite store %s",
                    len(rows), self._db_file)

    def count(self):
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM centers").fetchone()
        return row[0]

    def query(self, pincode=None, district=None):
        """Filtered lookup; district is a case-insensitive substring match."""
        sql = "SELECT payload FROM centers"
        clauses, params = [], []
        if pincode is not None:
            clauses.append("pincode = ?")
            params.append(pincode)
        if district is not None:
            clauses.append("LOWER(district_name) LIKE ? ESCAPE '\\'")
            params.append("%" + _escape_like(district) + "%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY position"
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except OverflowError:
                # A pincode outside the SQLite integer range can match
                # nothing; keep the empty-200 behavior of the list filter.
                return []
        return [json.loads(row[0]) for row in rows]

    def health(self):
        """Readiness for /health: DB reachable and real centers loaded."""
        try:
            count = self.count()
        except Exception as e:
            return {"ok": False, "detail": f"center store unreachable: {e}",
                    "centers": 0}
        return _store_health(count, self._used_fallback)

    def close(self):
        with self._lock:
            self._conn.close()


class InMemoryCenterStore:
    """Fallback used when the SQLite database cannot be opened (for example
    a read-only deployment directory). Same interface, previous behavior."""

    backend = "memory"

    def __init__(self, data_file):
        self._centers, self._used_fallback = load_centers(data_file)

    def count(self):
        return len(self._centers)

    def query(self, pincode=None, district=None):
        results = self._centers
        if pincode is not None:
            results = [c for c in results if c.get("pincode") == pincode]
        if district is not None:
            results = [c for c in results
                       if district in c.get("district_name", "").lower()]
        return results

    def health(self):
        """Readiness for /health: real centers loaded in memory."""
        return _store_health(self.count(), self._used_fallback)

    def close(self):
        pass


class RateLimiter:
    """Simple per-client-IP token bucket (stdlib only).

    Disabled when the configured rate is 0, which is also the default so
    local demos and the 10 req/s failover benchmark are never throttled.
    /health and /metrics are exempted at the routing layer so ALB probes
    and metric scrapers are never limited.
    """

    def __init__(self, requests_per_second=0.0, burst=None):
        self.rps = float(requests_per_second or 0.0)
        self.burst = float(burst) if burst else max(1.0, self.rps * 2)
        self.enabled = self.rps > 0
        self._buckets = {}  # client IP -> (tokens, last refill time)
        self._lock = threading.Lock()
        self.rejected_total = 0

    def allow(self, client_ip):
        if not self.enabled:
            return True
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(client_ip, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rps)
            if tokens >= 1.0:
                self._buckets[client_ip] = (tokens - 1.0, now)
                return True
            self._buckets[client_ip] = (tokens, now)
            self.rejected_total += 1
            return False


def build_store(config):
    """Create the center store, preferring SQLite with an in-memory fallback."""
    try:
        return CenterStore(config.db_file, config.data_file)
    except Exception as e:
        logger.warning("Could not initialize SQLite store at %s (%s); "
                       "falling back to the in-memory dataset",
                       config.db_file, e)
        return InMemoryCenterStore(config.data_file)


class CoWINLookupHandler(BaseHTTPRequestHandler):
    server_version = SERVICE_VERSION

    @property
    def config(self):
        return self.server.config

    @property
    def state(self):
        return self.server.state

    @property
    def store(self):
        return self.server.store

    def _set_headers(self, status_code=200, content_type="application/json",
                     extra_headers=None):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Served-By-Zone", self.config.zone)
        self.send_header("X-Instance-Id", self.config.instance_id)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers",
                         "X-Served-By-Zone, X-Instance-Id")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()

    def _write_json(self, body, status_code=200, extra_headers=None):
        path = urlparse(self.path).path
        headers = dict(extra_headers or {})
        navigable = (self.command == "GET" and path not in PROTECTED_PATHS)
        if navigable:
            headers["Vary"] = "Accept"
        if navigable and self._wants_html():
            if status_code >= 400:
                markup = (pages.not_found_page(path) if status_code == 404 else
                          pages.error_page(body, status_code))
                if path == "/health":
                    markup = pages.health_page(body, status_code)
            elif path in ("/", "/info"):
                markup = pages.info_page(body)
            elif path == "/health":
                markup = pages.health_page(body, status_code)
            elif path in ("/api/v1/centers", "/centers"):
                query = parse_qs(urlparse(self.path).query)
                filters = {key: values[0] for key, values in query.items()}
                markup = pages.centers_page(body, filters)
            elif path == "/metrics":
                markup = pages.metrics_page(body)
            else:
                markup = pages.error_page(body, status_code)
            payload = markup.encode("utf-8")
            headers.update({
                "Content-Length": str(len(payload)),
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'",
            })
            self.state.record_response(path, status_code)
            self._set_headers(status_code, "text/html; charset=utf-8", headers)
            self.wfile.write(payload)
            return
        self.state.record_response(path, status_code)
        self._set_headers(status_code, extra_headers=headers)
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def _wants_html(self):
        """Require explicit text/html; wildcards preserve the JSON default."""
        qualities = {}
        for item in self.headers.get("Accept", "").lower().split(","):
            media, *parameters = item.strip().split(";")
            quality = 1.0
            for parameter in parameters:
                key, sep, value = parameter.strip().partition("=")
                if sep and key == "q":
                    try:
                        quality = float(value)
                    except ValueError:
                        quality = 0.0
            qualities[media] = quality if 0 <= quality <= 1 else 0.0
        return (qualities.get("text/html", 0) > 0 and
                qualities.get("text/html", 0) >= qualities.get("application/json", 0))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()

    def do_GET(self):
        try:
            self.state.record_request()
            self._route_get()
        except BrokenPipeError:
            # Client hung up mid-response; nothing sensible left to send.
            logger.debug("Client closed connection during GET %s", self.path)
        except Exception:
            logger.exception("Unhandled error while serving GET %s", self.path)
            try:
                self._write_json({
                    "error": "Internal Server Error",
                    "message": "Unexpected error while processing the request"
                }, status_code=500)
            except Exception:
                logger.exception("Failed to send 500 response for GET %s", self.path)

    def _route_get(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        zone = self.config.zone
        instance_id = self.config.instance_id

        if not self._check_rate_limit(path):
            return

        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            try:
                with open(os.path.join(STATIC_DIR, filename), "rb") as asset:
                    body = asset.read()
            except OSError:
                self._write_json({"error": "Frontend not installed",
                                  "message": "Deploy service/static alongside app.py"},
                                 status_code=503)
                return
            self.state.record_response(path, 200)
            csp = ("default-src 'self'; base-uri 'none'; "
                   "frame-ancestors 'none'; form-action 'self'")
            if filename == "admin.html":
                # The console polls the configured load balancer and node
                # addresses, which are not same-origin with the serving node.
                csp += "; connect-src 'self' http: https:"
            self._set_headers(content_type=content_type, extra_headers={
                "Content-Length": str(len(body)),
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": csp,
            })
            self.wfile.write(body)
            return

        # Health Check Endpoint (used by AWS ALB Target Group). It is a
        # readiness check: HTTP 200 only when the node can actually serve
        # lookups (center store reachable, real dataset loaded).
        if path == "/health":
            if self.state.is_unhealthy():
                self._write_json({
                    "status": "unhealthy",
                    "reason": "Simulated failure condition active",
                    "zone": zone,
                    "instance_id": instance_id,
                    "timestamp": time.time()
                }, status_code=500)
                return
            store_health = self.store.health()
            if not store_health["ok"]:
                logger.error("Readiness check failing: %s",
                             store_health["detail"])
                self._write_json({
                    "status": "unhealthy",
                    "reason": f"Lookup not ready: {store_health['detail']}",
                    "zone": zone,
                    "instance_id": instance_id,
                    "timestamp": time.time()
                }, status_code=500)
                return
            self._write_json({
                "status": "healthy",
                "zone": zone,
                "instance_id": instance_id,
                "uptime_seconds": self.state.uptime(),
                "total_requests_served": self.state.total_requests(),
                "timestamp": time.time()
            })
            return

        # Administrative controls to test target health transitions (supports GET and POST)
        if is_protected_path(path) and not self._check_auth():
            return

        sim_action, sim_zone = parse_simulate_path(path)
        if sim_action:
            self._run_simulate(sim_action, sim_zone)
            return

        # Centers Lookup Endpoint
        if path in ("/api/v1/centers", "/centers"):
            req_pincode = None
            req_district = None

            # Optional filter by pincode
            if "pincode" in query:
                try:
                    req_pincode = int(query["pincode"][0])
                except ValueError:
                    self._write_json({
                        "error": "Bad Request",
                        "message": "pincode must be an integer, got "
                                   f"'{query['pincode'][0]}'"
                    }, status_code=400)
                    return

            # Optional filter by district
            if "district" in query:
                req_district = query["district"][0].lower()
                if len(req_district) > MAX_DISTRICT_FILTER_LENGTH:
                    self._write_json({
                        "error": "Bad Request",
                        "message": "district filter is too long "
                                   f"(max {MAX_DISTRICT_FILTER_LENGTH} characters)"
                    }, status_code=400)
                    return

            results = self.store.query(pincode=req_pincode,
                                       district=req_district)

            self._write_json({
                "service": "CoWIN Vaccination Center Lookup",
                "served_by": {
                    "zone": zone,
                    "instance_id": instance_id
                },
                "count": len(results),
                "centers": results
            })
            return

        # Metrics Endpoint - operational counters for monitoring
        if path == "/metrics":
            self._metrics()
            return

        # Root Endpoint - Instance Info & Diagnostics
        if path in ("/", "/info"):
            self._write_json({
                "service": "CoWIN Scaled-Down Lookup Service (IT457 Week 3 PoC)",
                "theme": "Government and Public Digital Platforms",
                "status": "unhealthy" if self.state.is_unhealthy() else "healthy",
                "served_by": {
                    "availability_zone": zone,
                    "instance_id": instance_id,
                    "hostname": socket.gethostname()
                },
                "runtime_metrics": {
                    "uptime_seconds": self.state.uptime(),
                    "total_requests_served": self.state.total_requests()
                },
                "endpoints": {
                    "health_check": "/health",
                    "lookup_centers": "/api/v1/centers",
                    "lookup_by_pincode": "/api/v1/centers?pincode=380009",
                    "lookup_by_district": "/api/v1/centers?district=Ahmedabad",
                    "metrics": "/metrics"
                }
            })
            return

        # 404 Fallback
        self._write_json({
            "error": "Not Found",
            "path": path,
            "message": "Valid endpoints are /health, /api/v1/centers, /metrics, and /"
        }, status_code=404)

    def do_POST(self):
        try:
            self.state.record_request()
            self._route_post()
        except BrokenPipeError:
            logger.debug("Client closed connection during POST %s", self.path)
        except Exception:
            logger.exception("Unhandled error while serving POST %s", self.path)
            try:
                self._write_json({
                    "error": "Internal Server Error",
                    "message": "Unexpected error while processing the request"
                }, status_code=500)
            except Exception:
                logger.exception("Failed to send 500 response for POST %s", self.path)

    def _route_post(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if not self._check_rate_limit(path):
            return

        # Administrative controls to test target health transitions
        if is_protected_path(path) and not self._check_auth():
            return

        sim_action, sim_zone = parse_simulate_path(path)
        if sim_action:
            self._run_simulate(sim_action, sim_zone)
            return

        self._write_json({"error": "Unknown POST action"}, status_code=404)

    def _method_not_allowed(self):
        """JSON 405 for unsupported methods instead of the default HTML 501."""
        self._write_json({
            "error": "Method Not Allowed",
            "message": "This service supports GET, POST and OPTIONS only"
        }, status_code=405, extra_headers={"Allow": "GET, POST, OPTIONS"})

    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed

    def _client_ip(self):
        """Client identity for per-client limits: the first X-Forwarded-For
        hop when the header is present (the real client when the service
        sits behind a load balancer), otherwise the direct peer. Keying on
        the peer alone would give every user one shared bucket at the ALB."""
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        return self.client_address[0]

    def _check_rate_limit(self, path):
        """Return True when the request may proceed under the rate limit;
        otherwise write the JSON 429 and return False."""
        if path in RATE_LIMIT_EXEMPT_PATHS:
            return True
        client_ip = self._client_ip()
        if self.server.rate_limiter.allow(client_ip):
            return True
        logger.warning("Rate limited %s %s from %s",
                       self.command, path, client_ip)
        self._write_json({
            "error": "Too Many Requests",
            "message": "Rate limit exceeded - slow down and retry"
        }, status_code=429, extra_headers={"Retry-After": "1"})
        return False

    def _check_auth(self):
        """Gate mutating endpoints behind the configured API key.

        Returns True when the request may proceed; otherwise writes the
        JSON 401 and returns False. With no COWIN_API_KEY configured the
        service runs in dev mode and every request is allowed (a warning
        is logged at startup).
        """
        if self.config.api_key is None:
            return True
        supplied = self.headers.get(AUTH_HEADER, "")
        if hmac.compare_digest(supplied, self.config.api_key):
            return True
        logger.warning("Rejected %s %s from %s: missing or invalid API key",
                       self.command, self.path, self.client_address[0])
        self._write_json({
            "error": "Unauthorized",
            "message": f"A valid {AUTH_HEADER} header is required for this endpoint"
        }, status_code=401)
        return False

    def _metrics(self):
        """Operational counters snapshot for monitoring and the demo."""
        by_endpoint, by_status = self.state.response_snapshot()
        limiter = self.server.rate_limiter
        store_health = self.store.health()
        self._write_json({
            "service": "CoWIN Vaccination Center Lookup",
            "zone": self.config.zone,
            "instance_id": self.config.instance_id,
            "status": "unhealthy" if self.state.is_unhealthy() else "healthy",
            "uptime_seconds": self.state.uptime(),
            "total_requests_served": self.state.total_requests(),
            "requests_by_endpoint": by_endpoint,
            "responses_by_status": {str(code): count for code, count in
                                    sorted(by_status.items())},
            "store": {
                "backend": self.store.backend,
                "centers_loaded": store_health["centers"],
                "ready": store_health["ok"],
                "detail": store_health["detail"],
            },
            "rate_limit": {
                "enabled": limiter.enabled,
                "requests_per_second": limiter.rps,
                "burst": limiter.burst,
                "rejected_requests": limiter.rejected_total,
            },
        })

    def _run_simulate(self, action, zone_letter):
        """Run a verified /simulate command.

        A zone-qualified command only runs on the node whose configured
        zone letter matches; a misrouted one gets a 409 so it can never
        flip the wrong zone.
        """
        if zone_letter and zone_letter != self.config.zone_letter:
            logger.warning(
                "Rejected /simulate/zone-%s/%s: this node is zone '%s' (%s)",
                zone_letter, action, self.config.zone_letter, self.config.zone)
            self._write_json({
                "error": "Conflict",
                "message": (f"This node is zone '{self.config.zone_letter}' "
                            f"({self.config.zone}); the command targeted "
                            f"zone '{zone_letter}'."),
                "zone": self.config.zone
            }, status_code=409)
            return
        if action == "fail":
            self._simulate_fail()
        else:
            self._simulate_recover()

    def _peer_allows_failure(self):
        """Safety interlock: refuse to fail while the peer zone is down.

        Returns True when the simulated failure may proceed; otherwise
        writes the JSON 409 and returns False. With no COWIN_PEER_URL
        configured (single-node dev setups) the check is skipped. An
        unreachable peer counts as unhealthy: never degrade the second
        zone while the first may already be down for real. Called from
        _simulate_fail while holding the node's simulate_lock, after
        the intent mark, so a racing peer sees this node failing.
        """
        peer = self.config.peer_url
        if not peer:
            return True
        try:
            req = urllib.request.Request(peer + "/health",
                                         headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                peer_healthy = resp.status == 200
        except urllib.error.HTTPError:
            peer_healthy = False  # answering, but failing health checks
        except Exception:
            peer_healthy = False  # unreachable: real outage or stopped
        if peer_healthy:
            return True
        logger.warning(
            "Refused simulated failure: peer zone at %s is not healthy", peer)
        self._write_json({
            "error": "Conflict",
            "message": ("The other zone is not healthy; refusing to "
                        "degrade a second zone."),
            "zone": self.config.zone
        }, status_code=409)
        return False

    def _schedule_auto_recover(self):
        """Bound the disruption: restore health automatically after the
        configured delay, even if nobody calls /simulate/recover."""
        seconds = self.config.auto_recover_seconds
        if seconds <= 0:
            return
        self._cancel_auto_recover()

        def _auto_recover():
            self.state.set_unhealthy(False)
            logger.info("Simulated failure auto-recovered after %.0fs - "
                        "/health restored to 200", seconds)

        timer = threading.Timer(seconds, _auto_recover)
        timer.daemon = True
        timer.start()
        self.server.auto_recover_timer = timer

    def _cancel_auto_recover(self):
        timer = getattr(self.server, "auto_recover_timer", None)
        if timer is not None:
            timer.cancel()
            self.server.auto_recover_timer = None

    def _simulate_fail(self):
        if self.state.is_unhealthy():
            # Already in simulated failure. Refuse rather than re-arm:
            # re-arming the auto-recover timer on every fail would let a
            # key holder extend the degradation indefinitely. One accepted
            # fail = one bounded window, ended by the timer or Recover.
            logger.warning("Refused simulated failure: already active on "
                           "this node (no timer re-arm)")
            self._write_json({
                "error": "Conflict",
                "message": ("A simulated failure is already active on this "
                            "node; it ends at the auto-recover deadline or "
                            "via /simulate/recover."),
                "zone": self.config.zone,
                "status": "unhealthy"
            }, status_code=409)
            return
        # Intent-first check-and-set, safe against simultaneous
        # fail commands on both nodes: mark our own failure BEFORE
        # consulting the peer. A peer whose health read observed us
        # healthy finished that read before our mark, so its own
        # read of us happens after our mark (program order) and
        # must see us failing - it backs off with a 409. If we are
        # the one who sees the peer failing, we roll back our
        # intent and refuse. At most one node stays failed; in the
        # worst interleaving both refuse and neither goes down.
        with self.server.simulate_lock:
            self.state.set_unhealthy(True)
            if not self._peer_allows_failure():
                self.state.set_unhealthy(False)  # lost the race: undo
                return
            self._schedule_auto_recover()
        logger.warning("Simulated failure ENABLED - /health now returns 500")
        self._write_json({
            "message": "Health check now returning 500",
            "zone": self.config.zone,
            "status": "unhealthy",
            "auto_recover_in_seconds": (self.config.auto_recover_seconds
                                        if self.config.auto_recover_seconds > 0
                                        else None)
        })

    def _simulate_recover(self):
        self._cancel_auto_recover()
        self.state.set_unhealthy(False)
        logger.info("Simulated failure cleared - /health restored to 200")
        self._write_json({
            "message": "Health check restored to 200",
            "zone": self.config.zone,
            "status": "healthy"
        })

    def log_message(self, format, *args):
        logger.info("[%s] %s", self.config.zone, format % args)


class CoWINHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying the service config, state and dataset."""

    daemon_threads = True

    def __init__(self, config):
        self.config = config
        self.state = ServiceState()
        self.store = build_store(config)
        self.rate_limiter = RateLimiter(config.rate_limit_rps,
                                        config.rate_limit_burst)
        self.auto_recover_timer = None
        # Serializes simulated fail/recover on this node so the
        # intent-then-verify sequence in _simulate_fail is atomic
        # against local concurrent requests.
        self.simulate_lock = threading.Lock()
        super().__init__((config.host, config.port), CoWINLookupHandler)

    def server_close(self):
        super().server_close()
        self.store.close()


def create_server(config):
    """Build (but do not start) the HTTP server. Entry point for tests/embeds."""
    return CoWINHTTPServer(config)


def _install_signal_handlers(httpd):
    """Shut down cleanly on SIGTERM/SIGINT so systemd and Ctrl-C both work."""
    def _handle(signum, frame):
        logger.info("Received signal %d - shutting down gracefully", signum)
        # shutdown() must run outside the serve_forever thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def configure_logging(level_name):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def serve(config, log_level="INFO"):
    """Configure logging, install signal handlers and serve until shutdown."""
    configure_logging(log_level)
    httpd = create_server(config)
    _install_signal_handlers(httpd)

    logger.info("CoWIN Lookup Service running on http://%s:%d", config.host, config.port)
    logger.info("  Availability Zone : %s", config.zone)
    logger.info("  Instance ID       : %s", config.instance_id)
    logger.info("  Health Endpoint   : http://%s:%d/health", config.host, config.port)
    if config.api_key is None:
        logger.warning("COWIN_API_KEY is not set - /simulate/* endpoints are "
                       "UNAUTHENTICATED (dev mode; set COWIN_API_KEY to require "
                       "an API key)")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        logger.info("Lookup service stopped.")


def run(port=DEFAULT_PORT, zone=DEFAULT_ZONE, instance_id=None,
        host="0.0.0.0", log_level=None, data_file=None, db_file=None,
        api_key=None):
    """Backward-compatible programmatic entry point."""
    config = ServiceConfig(host=host, port=port, zone=zone,
                           instance_id=instance_id, data_file=data_file,
                           db_file=db_file, api_key=api_key)
    serve(config, log_level or os.environ.get("LOG_LEVEL", "INFO"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CoWIN Lookup Service")
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "0.0.0.0"),
                        help="Interface to bind (env: HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)),
                        help="Port to listen on (env: PORT)")
    parser.add_argument("--zone", type=str, default=os.environ.get("AWS_AZ", DEFAULT_ZONE),
                        help="Availability zone name (env: AWS_AZ)")
    parser.add_argument("--instance-id", type=str, default=os.environ.get("AWS_INSTANCE_ID", None),
                        help="Custom instance identifier (env: AWS_INSTANCE_ID)")
    parser.add_argument("--data-file", type=str, default=os.environ.get("CENTERS_DATA_FILE", None),
                        help="Path to centers dataset JSON (env: CENTERS_DATA_FILE)")
    parser.add_argument("--db-file", type=str, default=os.environ.get("CENTERS_DB_FILE", None),
                        help="Path to the centers SQLite database (env: CENTERS_DB_FILE)")
    parser.add_argument("--api-key", type=str, default=os.environ.get("COWIN_API_KEY", None),
                        help="API key required on mutating endpoints (env: COWIN_API_KEY)")
    parser.add_argument("--zone-letter", type=str, default=os.environ.get("COWIN_ZONE_LETTER", None),
                        help="Short zone letter ('a'/'b') used to verify zone-pinned "
                             "/simulate/zone-<letter>/* commands; defaults to the "
                             "trailing letter of --zone (env: COWIN_ZONE_LETTER)")
    parser.add_argument("--peer-url", type=str, default=os.environ.get("COWIN_PEER_URL", None),
                        help="Base URL of the sibling zone's node; while the peer is "
                             "unhealthy /simulate/fail is refused (env: COWIN_PEER_URL)")
    parser.add_argument("--sim-auto-recover-seconds", type=float,
                        default=float(os.environ.get("COWIN_SIM_AUTO_RECOVER_SECONDS",
                                      DEFAULT_SIM_AUTO_RECOVER_SECONDS)),
                        help="Seconds after which a simulated failure auto-recovers; "
                             "0 disables (env: COWIN_SIM_AUTO_RECOVER_SECONDS)")
    parser.add_argument("--rate-limit-rps", type=float,
                        default=float(os.environ.get("RATE_LIMIT_RPS", 0.0)),
                        help="Sustained requests/second allowed per client IP; "
                             "0 disables limiting (env: RATE_LIMIT_RPS)")
    parser.add_argument("--rate-limit-burst", type=float,
                        default=(float(os.environ["RATE_LIMIT_BURST"])
                                 if os.environ.get("RATE_LIMIT_BURST") else None),
                        help="Token bucket size per client IP (env: RATE_LIMIT_BURST)")
    parser.add_argument("--log-level", type=str, default=os.environ.get("LOG_LEVEL", "INFO"),
                        help="Logging level (env: LOG_LEVEL)")
    args = parser.parse_args()

    config = ServiceConfig(host=args.host, port=args.port, zone=args.zone,
                           instance_id=args.instance_id, data_file=args.data_file,
                           db_file=args.db_file, api_key=args.api_key,
                           zone_letter=args.zone_letter, peer_url=args.peer_url,
                           auto_recover_seconds=args.sim_auto_recover_seconds,
                           rate_limit_rps=args.rate_limit_rps,
                           rate_limit_burst=args.rate_limit_burst)
    serve(config, args.log_level)
