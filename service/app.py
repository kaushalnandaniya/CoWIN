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
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("cowin-lookup")

DEFAULT_PORT = 8080
DEFAULT_ZONE = "ap-south-1a"
SERVICE_VERSION = "CoWIN-LookupService/1.0"

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
                 instance_id=None, data_file=None):
        self.host = host
        self.port = port
        self.zone = zone
        self.instance_id = instance_id or f"i-{socket.gethostname()[:8]}"
        if data_file is None:
            data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "centers_data.json")
        self.data_file = data_file

    @classmethod
    def from_env(cls):
        """Config from environment only (used when embedding the service)."""
        return cls(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", DEFAULT_PORT)),
            zone=os.environ.get("AWS_AZ", DEFAULT_ZONE),
            instance_id=os.environ.get("AWS_INSTANCE_ID"),
            data_file=os.environ.get("CENTERS_DATA_FILE"),
        )


class ServiceState:
    """Mutable runtime state, guarded so threaded handlers stay consistent."""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.request_count = 0
        self.force_unhealthy = False

    def record_request(self):
        with self._lock:
            self.request_count += 1
            return self.request_count

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


class CoWINLookupHandler(BaseHTTPRequestHandler):
    server_version = SERVICE_VERSION

    @property
    def config(self):
        return self.server.config

    @property
    def state(self):
        return self.server.state

    @property
    def centers(self):
        return self.server.centers

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
        if path == "/simulate/fail":
            self._simulate_fail()
            return

        if path == "/simulate/recover":
            self._simulate_recover()
            return

        # Centers Lookup Endpoint
        if path in ("/api/v1/centers", "/centers"):
            results = self.centers

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
                results = [c for c in results if c.get("pincode") == req_pincode]

            # Optional filter by district
            if "district" in query:
                req_district = query["district"][0].lower()
                results = [c for c in results if req_district in c.get("district_name", "").lower()]

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
        if path == "/simulate/fail":
            self._simulate_fail()
            return

        if path == "/simulate/recover":
            self._simulate_recover()
            return

        self._write_json({"error": "Unknown POST action"}, status_code=404)

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
        self.centers = load_centers(config.data_file)
        super().__init__((config.host, config.port), CoWINLookupHandler)


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
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        logger.info("Lookup service stopped.")


def run(port=DEFAULT_PORT, zone=DEFAULT_ZONE, instance_id=None,
        host="0.0.0.0", log_level=None, data_file=None):
    """Backward-compatible programmatic entry point."""
    config = ServiceConfig(host=host, port=port, zone=zone,
                           instance_id=instance_id, data_file=data_file)
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
    parser.add_argument("--log-level", type=str, default=os.environ.get("LOG_LEVEL", "INFO"),
                        help="Logging level (env: LOG_LEVEL)")
    args = parser.parse_args()

    config = ServiceConfig(host=args.host, port=args.port, zone=args.zone,
                           instance_id=args.instance_id, data_file=args.data_file)
    serve(config, args.log_level)
