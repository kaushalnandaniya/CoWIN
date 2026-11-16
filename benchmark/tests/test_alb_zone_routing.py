#!/usr/bin/env python3
"""
Integration tests for the ALB simulator's zone-pinned routing.

The listener rules on the real load balancer forward
/simulate/zone-<a|b>/* to a single-zone target group; the simulator
mirrors that locally:

- a zone-pinned path always reaches its pinned target, even while that
  target is unhealthy (single-target groups fail open, so /recover can
  reach a drained node)
- POST is proxied (the admin console drives the controls with POST)
- a reached target's error status (401/409/...) is relayed verbatim,
  not masked as a 502
- unpinned paths still round-robin across healthy targets only

Run from the repository root with:

    python3 -m unittest discover -s benchmark -v
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alb_simulator  # noqa: E402


class StubNode:
    """Minimal backend: /health 200, /simulate/zone-*/fail answers 409,
    everything else 200 naming the node. Records the last API key seen."""

    def __init__(self, name):
        self.name = name
        self.last_api_key = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                outer.last_api_key = self.headers.get("X-API-Key")
                if self.path == "/health":
                    status, body = 200, {"status": "healthy"}
                elif self.path.startswith("/simulate/"):
                    status, body = 409, {"error": "Conflict", "node": outer.name}
                else:
                    status, body = 200, {"node": outer.name}
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _answer
            do_POST = _answer

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class AlbSimulatorTestCase(unittest.TestCase):
    """One simulator instance per class, proxies to two stub nodes."""

    node_a = None
    node_b = None
    alb = None
    alb_base = None

    @classmethod
    def setUpClass(cls):
        cls.node_a = StubNode("node-a")
        cls.node_b = StubNode("node-b")
        alb_simulator.TARGETS[0]["port"] = cls.node_a.port
        alb_simulator.TARGETS[1]["port"] = cls.node_b.port
        for target in alb_simulator.TARGETS:
            target["status"] = "healthy"
            target["consecutive_success"] = 2
            target["consecutive_fails"] = 0
        cls.alb = ThreadingHTTPServer(("127.0.0.1", 0),
                                      alb_simulator.ALBProxyHandler)
        cls.alb_base = f"http://127.0.0.1:{cls.alb.server_address[1]}"
        cls.alb_thread = threading.Thread(target=cls.alb.serve_forever,
                                          daemon=True)
        cls.alb_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.alb.shutdown()
        cls.alb.server_close()
        cls.alb_thread.join(timeout=5)
        cls.node_a.stop()
        cls.node_b.stop()

    def setUp(self):
        for target in alb_simulator.TARGETS:
            target["status"] = "healthy"

    def request(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.alb_base + path, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class TestZonePinnedRouting(AlbSimulatorTestCase):

    def test_zone_a_path_reaches_node_a(self):
        _, body = self.request("/simulate/zone-a/fail", method="POST")
        self.assertEqual(body["node"], "node-a")

    def test_zone_b_path_reaches_node_b(self):
        _, body = self.request("/simulate/zone-b/recover", method="POST")
        self.assertEqual(body["node"], "node-b")

    def test_pinned_path_fails_open_when_target_unhealthy(self):
        # Recover must reach the drained node: a single-target group has
        # no healthy fallback, so the ALB routes to it anyway.
        alb_simulator.TARGETS[0]["status"] = "unhealthy"
        status, body = self.request("/simulate/zone-a/recover", method="POST")
        self.assertEqual(body["node"], "node-a")
        self.assertEqual(status, 409)  # stub's own answer, relayed

    def test_target_error_status_is_relayed_not_masked(self):
        status, body = self.request("/simulate/zone-b/fail", method="POST")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "Conflict")

    def test_api_key_header_is_forwarded(self):
        self.request("/simulate/zone-a/fail", method="POST",
                     headers={"X-API-Key": "operator-key"})
        self.assertEqual(self.node_a.last_api_key, "operator-key")

    def test_unpinned_paths_skip_unhealthy_targets(self):
        alb_simulator.TARGETS[0]["status"] = "unhealthy"
        for _ in range(4):
            status, body = self.request("/api/v1/centers")
            self.assertEqual(status, 200)
            self.assertEqual(body["node"], "node-b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
