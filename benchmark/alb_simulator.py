#!/usr/bin/env python3
"""
AWS Application Load Balancer (ALB) Local Simulator
IT457 Cloud Computing - CoWIN High Availability PoC

Emulates AWS ALB behavior:
- Round-robin proxying across registered targets in separate zones
- Background active health checking (/health)
- Target state machine: HEALTHY <-> UNHEALTHY
- Health threshold and unhealthy threshold counters
- 502 Bad Gateway when routing to a suddenly failed target prior to eviction
- Real-time diagnostics endpoint at /alb/status
"""

import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import socket
import sys
import threading
import time
from urllib.error import URLError, HTTPError
import urllib.parse
import urllib.request

# Global configuration
PORT = 8080
HEALTH_INTERVAL = 1.0  # seconds between background health probes
HEALTH_TIMEOUT = 0.8   # seconds before probe timeout
UNHEALTHY_THRESHOLD = 2
HEALTHY_THRESHOLD = 2

# Target definitions mimicking EC2 instances in AZ-A and AZ-B
TARGETS = [
    {
        "id": "i-0a1b2c3d-zone-a",
        "name": "Instance-Zone-A",
        "zone": "ap-south-1a",
        "host": "127.0.0.1",
        "port": 8081,
        "status": "healthy",
        "consecutive_success": 2,
        "consecutive_fails": 0,
        "total_requests": 0,
        "total_errors": 0,
        "last_health_check": 0,
        "last_latency_ms": 0.0
    },
    {
        "id": "i-0e5f6g7h-zone-b",
        "name": "Instance-Zone-B",
        "zone": "ap-south-1b",
        "host": "127.0.0.1",
        "port": 8082,
        "status": "healthy",
        "consecutive_success": 2,
        "consecutive_fails": 0,
        "total_requests": 0,
        "total_errors": 0,
        "last_health_check": 0,
        "last_latency_ms": 0.0
    }
]

RR_INDEX = 0
RR_LOCK = threading.Lock()
TARGETS_LOCK = threading.Lock()


def run_health_check_loop():
    """Background thread that probes /health on each target periodically, mimicking AWS ALB."""
    while True:
        for t in TARGETS:
            url = f"http://{t['host']}:{t['port']}/health"
            t0 = time.time()
            success = False
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ELB-HealthChecker/2.0"})
                with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
                    if resp.status == 200:
                        success = True
            except Exception:
                success = False
            latency = (time.time() - t0) * 1000

            with TARGETS_LOCK:
                t["last_health_check"] = time.time()
                t["last_latency_ms"] = round(latency, 2)
                prev_status = t["status"]

                if success:
                    t["consecutive_success"] += 1
                    t["consecutive_fails"] = 0
                    if t["consecutive_success"] >= HEALTHY_THRESHOLD and t["status"] != "healthy":
                        t["status"] = "healthy"
                        sys.stderr.write(
                            f"\n[ALB HEALTH] Target {t['name']} ({t['zone']}) transitioned: {prev_status} -> HEALTHY\n"
                        )
                else:
                    t["consecutive_fails"] += 1
                    t["consecutive_success"] = 0
                    if t["consecutive_fails"] >= UNHEALTHY_THRESHOLD and t["status"] != "unhealthy":
                        t["status"] = "unhealthy"
                        sys.stderr.write(
                            f"\n[ALB HEALTH] Target {t['name']} ({t['zone']}) transitioned: {prev_status} -> UNHEALTHY\n"
                        )

        time.sleep(HEALTH_INTERVAL)


class ALBProxyHandler(BaseHTTPRequestHandler):
    server_version = "awselb/2.0-simulated"

    def _send_alb_error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Server", self.server_version)
        self.end_headers()
        body = {
            "error": "Bad Gateway" if code == 502 else "Service Unavailable",
            "code": code,
            "message": message,
            "timestamp": time.time()
        }
        self.wfile.write(json.dumps(body, indent=2).encode())

    def do_GET(self):
        global RR_INDEX

        # ALB management/diagnostics endpoint
        if self.path == "/alb/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with TARGETS_LOCK:
                info = {
                    "load_balancer": "CoWIN Simulated Application Load Balancer",
                    "scheme": "internet-facing",
                    "listener_port": PORT,
                    "target_group": "cowin-lookup-tg",
                    "health_check_config": {
                        "path": "/health",
                        "interval_seconds": HEALTH_INTERVAL,
                        "timeout_seconds": HEALTH_TIMEOUT,
                        "healthy_threshold": HEALTHY_THRESHOLD,
                        "unhealthy_threshold": UNHEALTHY_THRESHOLD
                    },
                    "targets": TARGETS
                }
            self.wfile.write(json.dumps(info, indent=2).encode())
            return

        # Pick a target using round-robin among healthy targets
        target = None
        with TARGETS_LOCK:
            healthy_targets = [t for t in TARGETS if t["status"] == "healthy"]

        if not healthy_targets:
            self._send_alb_error(503, "503 Service Unavailable: No healthy targets in target group.")
            return

        with RR_LOCK:
            target = healthy_targets[RR_INDEX % len(healthy_targets)]
            RR_INDEX += 1

        # Proxy request to chosen target
        target_url = f"http://{target['host']}:{target['port']}{self.path}"
        try:
            req = urllib.request.Request(
                target_url,
                headers={k: v for k, v in self.headers.items() if k.lower() != "host"}
            )
            req.add_header("X-Forwarded-For", self.client_address[0])
            req.add_header("X-Forwarded-Proto", "http")
            req.add_header("X-Forwarded-Port", str(PORT))

            with urllib.request.urlopen(req, timeout=2.0) as resp:
                content = resp.read()
                self.send_response(resp.status)
                for header, val in resp.getheaders():
                    if header.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(header, val)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-ALB-Target", target["id"])
                self.send_header("X-ALB-Zone", target["zone"])
                self.end_headers()
                self.wfile.write(content)

                with TARGETS_LOCK:
                    target["total_requests"] += 1

        except (URLError, socket.timeout, ConnectionRefusedError) as e:
            # Backend failed before health checker evicted it -> emit 502 Bad Gateway
            with TARGETS_LOCK:
                target["total_errors"] += 1
            self._send_alb_error(502, f"502 Bad Gateway: Target {target['name']} connection failed ({str(e)})")

    def log_message(self, format, *args):
        # Mute per-request proxy logs to keep stdout clean
        pass


def run_alb_simulator(port=8080):
    global PORT
    PORT = port
    health_thread = threading.Thread(target=run_health_check_loop, daemon=True)
    health_thread.start()

    server = HTTPServer(("0.0.0.0", port), ALBProxyHandler)
    print(f"🔀 CoWIN ALB Simulator listening on http://0.0.0.0:{port}")
    print(f"   Registered Targets: {[t['name'] + ' (' + t['zone'] + ')' for t in TARGETS]}")
    print(f"   Diagnostics URL   : http://localhost:{port}/alb/status")
    print(f"   Health Check Rule : Interval={HEALTH_INTERVAL}s, UnhealthyThreshold={UNHEALTHY_THRESHOLD}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ALB simulator.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CoWIN ALB Local Simulator")
    parser.add_argument("--port", type=int, default=8080, help="ALB listener port")
    args = parser.parse_args()
    run_alb_simulator(args.port)
