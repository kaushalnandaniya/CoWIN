#!/usr/bin/env python3
"""
CoWIN Vaccination Center Lookup Microservice
Component for IT457 Cloud Computing Two-Zone Failover Proof-of-Concept.

Zero external dependencies - runs on standard Python 3.
"""

import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import socket
import sys
import time
from urllib.parse import urlparse, parse_qs

# Global runtime state
START_TIME = time.time()
REQUEST_COUNT = 0
FORCE_UNHEALTHY = False

# Metadata defaults (can be overridden via CLI args or environment variables)
ZONE = os.environ.get("AWS_AZ", "ap-south-1a")
INSTANCE_ID = os.environ.get("AWS_INSTANCE_ID", f"i-{socket.gethostname()[:8]}")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "centers_data.json")

# Load centers dataset
try:
    with open(DATA_FILE, "r") as f:
        CENTERS = json.load(f)
except Exception as e:
    CENTERS = [
        {
            "center_id": 563001,
            "name": "Civil Hospital Asarwa CVC",
            "pincode": 380016,
            "district_name": "Ahmedabad",
            "fee_type": "Free",
            "sessions": [{"vaccine": "COVISHIELD", "available_capacity": 150}]
        }
    ]


class CoWINLookupHandler(BaseHTTPRequestHandler):
    server_version = "CoWIN-LookupService/1.0"

    def _set_headers(self, status_code=200, content_type="application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Served-By-Zone", ZONE)
        self.send_header("X-Instance-Id", INSTANCE_ID)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global REQUEST_COUNT, FORCE_UNHEALTHY
        REQUEST_COUNT += 1

        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        # Health Check Endpoint (used by AWS ALB Target Group)
        if path == "/health":
            if FORCE_UNHEALTHY:
                self._set_headers(500)
                body = {
                    "status": "unhealthy",
                    "reason": "Simulated failure condition active",
                    "zone": ZONE,
                    "instance_id": INSTANCE_ID,
                    "timestamp": time.time()
                }
            else:
                self._set_headers(200)
                body = {
                    "status": "healthy",
                    "zone": ZONE,
                    "instance_id": INSTANCE_ID,
                    "uptime_seconds": round(time.time() - START_TIME, 2),
                    "total_requests_served": REQUEST_COUNT,
                    "timestamp": time.time()
                }
            self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))
            return

        # Administrative controls to test target health transitions (supports GET and POST)
        if path == "/simulate/fail":
            FORCE_UNHEALTHY = True
            self._set_headers(200)
            self.wfile.write(json.dumps({"message": "Health check now returning 500", "zone": ZONE, "status": "unhealthy"}).encode("utf-8"))
            return

        if path == "/simulate/recover":
            FORCE_UNHEALTHY = False
            self._set_headers(200)
            self.wfile.write(json.dumps({"message": "Health check restored to 200", "zone": ZONE, "status": "healthy"}).encode("utf-8"))
            return

        # Centers Lookup Endpoint
        if path in ("/api/v1/centers", "/centers"):
            results = CENTERS
            
            # Optional filter by pincode
            if "pincode" in query:
                req_pincode = int(query["pincode"][0])
                results = [c for c in results if c.get("pincode") == req_pincode]

            # Optional filter by district
            if "district" in query:
                req_district = query["district"][0].lower()
                results = [c for c in results if req_district in c.get("district_name", "").lower()]

            self._set_headers(200)
            payload = {
                "service": "CoWIN Vaccination Center Lookup",
                "served_by": {
                    "zone": ZONE,
                    "instance_id": INSTANCE_ID
                },
                "count": len(results),
                "centers": results
            }
            self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))
            return

        # Root Endpoint - Instance Info & Diagnostics
        if path in ("/", "/info"):
            self._set_headers(200)
            info = {
                "service": "CoWIN Scaled-Down Lookup Service (IT457 Week 3 PoC)",
                "theme": "Government and Public Digital Platforms",
                "status": "healthy" if not FORCE_UNHEALTHY else "unhealthy",
                "served_by": {
                    "availability_zone": ZONE,
                    "instance_id": INSTANCE_ID,
                    "hostname": socket.gethostname()
                },
                "runtime_metrics": {
                    "uptime_seconds": round(time.time() - START_TIME, 2),
                    "total_requests_served": REQUEST_COUNT
                },
                "endpoints": {
                    "health_check": "/health",
                    "lookup_centers": "/api/v1/centers",
                    "lookup_by_pincode": "/api/v1/centers?pincode=380009",
                    "lookup_by_district": "/api/v1/centers?district=Ahmedabad"
                }
            }
            self.wfile.write(json.dumps(info, indent=2).encode("utf-8"))
            return

        # 404 Fallback
        self._set_headers(404)
        error_resp = {
            "error": "Not Found",
            "path": path,
            "message": "Valid endpoints are /health, /api/v1/centers, and /"
        }
        self.wfile.write(json.dumps(error_resp, indent=2).encode("utf-8"))

    def do_POST(self):
        global FORCE_UNHEALTHY
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # Administrative controls to test target health transitions
        if path == "/simulate/fail":
            FORCE_UNHEALTHY = True
            self._set_headers(200)
            self.wfile.write(json.dumps({"message": "Health check now returning 500", "zone": ZONE}).encode("utf-8"))
            return

        if path == "/simulate/recover":
            FORCE_UNHEALTHY = False
            self._set_headers(200)
            self.wfile.write(json.dumps({"message": "Health check restored to 200", "zone": ZONE}).encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "Unknown POST action"}).encode("utf-8"))

    def log_message(self, format, *args):
        # Concise logging format
        sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{ZONE}] {format % args}\n")


def run(port=8080, zone="ap-south-1a", instance_id=None):
    global ZONE, INSTANCE_ID
    ZONE = zone
    if instance_id:
        INSTANCE_ID = instance_id

    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, CoWINLookupHandler)
    print(f"🚀 CoWIN Lookup Service running on http://0.0.0.0:{port}")
    print(f"   Availability Zone : {ZONE}")
    print(f"   Instance ID       : {INSTANCE_ID}")
    print(f"   Health Endpoint   : http://0.0.0.0:{port}/health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down lookup service.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CoWIN Lookup Service")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)), help="Port to listen on")
    parser.add_argument("--zone", type=str, default=os.environ.get("AWS_AZ", "ap-south-1a"), help="Availability zone name")
    parser.add_argument("--instance-id", type=str, default=os.environ.get("AWS_INSTANCE_ID", None), help="Custom instance identifier")
    args = parser.parse_args()
    run(port=args.port, zone=args.zone, instance_id=args.instance_id)
