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
"""

import argparse
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
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("cowin-lookup")

DEFAULT_PORT = 8080
DEFAULT_ZONE = "ap-south-1a"
SERVICE_VERSION = "CoWIN-LookupService/1.0"

# Mutating endpoints gated behind the X-API-Key header when COWIN_API_KEY
# is configured. Read endpoints (health, lookup, info, metrics) stay open.
AUTH_HEADER = "X-API-Key"
PROTECTED_PATHS = frozenset({"/simulate/fail", "/simulate/recover"})

# Sample record served if the centers dataset cannot be loaded.
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
                 instance_id=None, data_file=None, db_file=None, api_key=None):
        self.host = host
        self.port = port
        self.zone = zone
        self.instance_id = instance_id or f"i-{socket.gethostname()[:8]}"
        self.api_key = api_key
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
        )


class ServiceState:
    """Mutable runtime state, guarded so threaded handlers stay consistent."""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.request_count = 0
        self.force_unhealthy = False

        self.auth_failures = 0

    def record_request(self):
        with self._lock:
            self.request_count += 1
            return self.request_count

    def record_auth_failure(self):
        with self._lock:
            self.auth_failures += 1

    def auth_failure_count(self):
        with self._lock:
            return self.auth_failures

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
    """Load the centers dataset, falling back to a sample record on failure."""
    try:
        with open(data_file, "r") as f:
            centers = json.load(f)
        logger.info("Loaded %d centers from %s", len(centers), data_file)
        return centers
    except Exception as e:
        logger.warning("Could not load centers data from %s (%s); "
                       "serving fallback sample record", data_file, e)
        return FALLBACK_CENTERS


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
        centers = load_centers(data_file)
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

    def close(self):
        with self._lock:
            self._conn.close()


class InMemoryCenterStore:
    """Fallback used when the SQLite database cannot be opened (for example
    a read-only deployment directory). Same interface, previous behavior."""

    backend = "memory"

    def __init__(self, data_file):
        self._centers = load_centers(data_file)

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

    def close(self):
        pass


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

    def _set_headers(self, status_code=200, content_type="application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Served-By-Zone", self.config.zone)
        self.send_header("X-Instance-Id", self.config.instance_id)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def _write_json(self, body, status_code=200):
        self._set_headers(status_code)
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

        # Health Check Endpoint (used by AWS ALB Target Group)
        if path == "/health":
            if self.state.is_unhealthy():
                self._write_json({
                    "status": "unhealthy",
                    "reason": "Simulated failure condition active",
                    "zone": zone,
                    "instance_id": instance_id,
                    "timestamp": time.time()
                }, status_code=500)
            else:
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
        if path in PROTECTED_PATHS and not self._check_auth():
            return

        if path == "/simulate/fail":
            self._simulate_fail()
            return

        if path == "/simulate/recover":
            self._simulate_recover()
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
                    "lookup_by_district": "/api/v1/centers?district=Ahmedabad"
                }
            })
            return

        # 404 Fallback
        self._write_json({
            "error": "Not Found",
            "path": path,
            "message": "Valid endpoints are /health, /api/v1/centers, and /"
        }, status_code=404)

    def do_POST(self):
        try:
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

        # Administrative controls to test target health transitions
        if path in PROTECTED_PATHS and not self._check_auth():
            return

        if path == "/simulate/fail":
            self._simulate_fail()
            return

        if path == "/simulate/recover":
            self._simulate_recover()
            return

        self._write_json({"error": "Unknown POST action"}, status_code=404)

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
        self.state.record_auth_failure()
        logger.warning("Rejected %s %s from %s: missing or invalid API key",
                       self.command, self.path, self.client_address[0])
        self._write_json({
            "error": "Unauthorized",
            "message": f"A valid {AUTH_HEADER} header is required for this endpoint"
        }, status_code=401)
        return False

    def _simulate_fail(self):
        self.state.set_unhealthy(True)
        logger.warning("Simulated failure ENABLED - /health now returns 500")
        self._write_json({
            "message": "Health check now returning 500",
            "zone": self.config.zone,
            "status": "unhealthy"
        })

    def _simulate_recover(self):
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
    parser.add_argument("--log-level", type=str, default=os.environ.get("LOG_LEVEL", "INFO"),
                        help="Logging level (env: LOG_LEVEL)")
    args = parser.parse_args()

    config = ServiceConfig(host=args.host, port=args.port, zone=args.zone,
                           instance_id=args.instance_id, data_file=args.data_file,
                           db_file=args.db_file, api_key=args.api_key)
    serve(config, args.log_level)
