#!/usr/bin/env python3
"""
Unit tests for the CoWIN Lookup Service (service/app.py).

Covers the contract the ALB simulator and failover benchmark rely on:
- /health healthy and unhealthy transitions (200 <-> 500)
- /simulate/fail and /simulate/recover over GET and POST
- /api/v1/centers responses and pincode/district filters
- X-Served-By-Zone and X-Instance-Id response headers
- Error handling (404, malformed pincode -> 400)

Stdlib only. Run from the repository root with:

    python3 -m unittest discover -s service -v

or directly:

    python3 service/tests/test_app.py
"""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

# Make `import app` work both under unittest discovery (which puts the
# service/ directory on sys.path) and when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "centers_data.json")
TEST_ZONE = "test-zone-1a"
TEST_INSTANCE = "i-testinstance01"


def start_test_server():
    """Start the service on an ephemeral port; returns (httpd, thread, base_url)."""
    config = app.ServiceConfig(host="127.0.0.1", port=0, zone=TEST_ZONE,
                               instance_id=TEST_INSTANCE, data_file=DATA_FILE)
    httpd = app.create_server(config)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, thread, f"http://127.0.0.1:{port}"


class TestCoWINLookupService(unittest.TestCase):
    """End-to-end tests against a live in-process instance of the service."""

    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.thread, cls.base_url = start_test_server()
        with open(DATA_FILE) as f:
            cls.dataset = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def tearDown(self):
        # Never leak a simulated failure into the next test.
        self.request("/simulate/recover")

    # --- helpers -----------------------------------------------------------

    def request(self, path, method="GET"):
        """Returns (status, headers, parsed_json_body) for any HTTP status.

        Body is None when the response carries no payload (e.g. 204).
        """
        req = urllib.request.Request(self.base_url + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, resp.headers, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, e.headers, json.loads(raw) if raw else None

    # --- health endpoint ---------------------------------------------------

    def test_health_healthy(self):
        status, headers, body = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["zone"], TEST_ZONE)
        self.assertEqual(body["instance_id"], TEST_INSTANCE)
        self.assertIn("uptime_seconds", body)
        self.assertIn("total_requests_served", body)

    def test_health_unhealthy_after_simulate_fail(self):
        status, _, body = self.request("/simulate/fail")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unhealthy")

        status, _, body = self.request("/health")
        self.assertEqual(status, 500)
        self.assertEqual(body["status"], "unhealthy")
        self.assertEqual(body["zone"], TEST_ZONE)

        status, _, body = self.request("/simulate/recover")
        self.assertEqual(status, 200)
        status, _, body = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")

    def test_simulate_fail_and_recover_over_post(self):
        status, _, body = self.request("/simulate/fail", method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unhealthy")
        status, _, body = self.request("/health")
        self.assertEqual(status, 500)

        status, _, body = self.request("/simulate/recover", method="POST")
        self.assertEqual(status, 200)
        status, _, body = self.request("/health")
        self.assertEqual(status, 200)

    # --- centers endpoint --------------------------------------------------

    def test_centers_returns_full_dataset(self):
        status, headers, body = self.request("/api/v1/centers")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(self.dataset))
        self.assertEqual(len(body["centers"]), len(self.dataset))
        self.assertEqual(body["served_by"]["zone"], TEST_ZONE)
        self.assertEqual(body["served_by"]["instance_id"], TEST_INSTANCE)

    def test_centers_short_alias(self):
        status, _, body = self.request("/centers")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(self.dataset))

    def test_centers_filter_by_pincode(self):
        pincode = self.dataset[0]["pincode"]
        expected = [c for c in self.dataset if c.get("pincode") == pincode]
        status, _, body = self.request(f"/api/v1/centers?pincode={pincode}")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(expected))
        for center in body["centers"]:
            self.assertEqual(center["pincode"], pincode)

    def test_centers_filter_by_district(self):
        district = self.dataset[0]["district_name"]
        expected = [c for c in self.dataset
                    if district.lower() in c.get("district_name", "").lower()]
        status, _, body = self.request(f"/api/v1/centers?district={district}")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(expected))
        self.assertGreater(body["count"], 0)

    def test_centers_unknown_pincode_returns_empty(self):
        status, _, body = self.request("/api/v1/centers?pincode=999999")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["centers"], [])

    def test_centers_malformed_pincode_returns_400(self):
        status, _, body = self.request("/api/v1/centers?pincode=notanumber")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Bad Request")

    # --- headers required by the ALB/benchmark contract ---------------------

    def test_zone_and_instance_headers_present(self):
        for path in ("/health", "/api/v1/centers", "/", "/nope"):
            _, headers, _ = self.request(path)
            self.assertEqual(headers.get("X-Served-By-Zone"), TEST_ZONE, path)
            self.assertEqual(headers.get("X-Instance-Id"), TEST_INSTANCE, path)

    def test_cors_preflight(self):
        status, headers, _ = self.request("/api/v1/centers", method="OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    # --- root info and fallback ---------------------------------------------

    def test_root_info_endpoint(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["served_by"]["availability_zone"], TEST_ZONE)
        self.assertIn("runtime_metrics", body)
        self.assertIn("endpoints", body)

    def test_unknown_path_returns_404_json(self):
        status, _, body = self.request("/does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "Not Found")
        self.assertEqual(body["path"], "/does-not-exist")

    def test_unknown_post_returns_404_json(self):
        status, _, body = self.request("/does-not-exist", method="POST")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "Unknown POST action")


class TestServerLifecycle(unittest.TestCase):
    """The server starts, serves and shuts down cleanly (systemd contract)."""

    def test_graceful_shutdown(self):
        httpd, thread, base_url = start_test_server()
        with urllib.request.urlopen(base_url + "/health", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "serve_forever did not stop after shutdown()")

    def test_config_from_env(self):
        saved = dict(os.environ)
        try:
            os.environ["AWS_AZ"] = "env-zone-1b"
            os.environ["AWS_INSTANCE_ID"] = "i-envtest"
            os.environ["PORT"] = "19099"
            config = app.ServiceConfig.from_env()
            self.assertEqual(config.zone, "env-zone-1b")
            self.assertEqual(config.instance_id, "i-envtest")
            self.assertEqual(config.port, 19099)
        finally:
            os.environ.clear()
            os.environ.update(saved)


class TestMalformedInputs(unittest.TestCase):
    """Malformed request inputs produce clean JSON errors, never a crash."""

    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.thread, cls.base_url = start_test_server()
        with open(DATA_FILE) as f:
            cls.dataset = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, method="GET"):
        req = urllib.request.Request(self.base_url + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, resp.headers, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, e.headers, json.loads(raw) if raw else None

    def test_malformed_pincode_variants_return_400(self):
        for bad in ("abc", "380016.5", "1e5", "0x1F", "380016;380006", "%ZZ"):
            status, _, body = self.request(
                "/api/v1/centers?pincode=" + urllib.parse.quote(bad))
            self.assertEqual(status, 400, bad)
            self.assertEqual(body["error"], "Bad Request")

    def test_blank_pincode_is_ignored(self):
        # parse_qs drops blank values, so this is an unfiltered lookup.
        status, _, body = self.request("/api/v1/centers?pincode=")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(self.dataset))

    def test_unknown_query_parameters_ignored(self):
        status, _, body = self.request("/api/v1/centers?color=blue&limit=3")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(self.dataset))

    def test_out_of_range_pincode_returns_empty_not_error(self):
        status, _, body = self.request("/api/v1/centers?pincode=99999999999999999999")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["centers"], [])

    def test_unknown_district_returns_empty(self):
        status, _, body = self.request("/api/v1/centers?district=NoSuchDistrict")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["centers"], [])

    def test_trailing_slash_path_returns_json_404(self):
        status, _, body = self.request("/api/v1/centers/")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "Not Found")
        self.assertEqual(body["path"], "/api/v1/centers/")

    def test_paths_are_case_sensitive(self):
        status, _, body = self.request("/HEALTH")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "Not Found")

    def test_double_slash_path_is_normalized(self):
        # BaseHTTPRequestHandler collapses a leading "//" to "/" before
        # routing, so this is served by the health endpoint, not a 404.
        status, _, body = self.request("//health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")


class TestServiceUnderLoad(unittest.TestCase):
    """The threaded server keeps answering well-formed responses while a
    failure is forced in the middle of concurrent traffic."""

    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.thread, cls.base_url = start_test_server()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_concurrent_requests_during_forced_failure(self):
        results = []  # (status_code, raw_body) for every completed response
        errors = []   # transport-level failures: none are acceptable
        stop = threading.Event()

        def worker(paths):
            while not stop.is_set():
                for path in paths:
                    if stop.is_set():
                        break
                    req = urllib.request.Request(self.base_url + path)
                    try:
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            results.append((resp.status, resp.read()))
                    except urllib.error.HTTPError as e:
                        results.append((e.code, e.read()))
                    except Exception as e:  # connection reset, timeout, ...
                        errors.append(f"{type(e).__name__}: {e}")

        paths = ["/health", "/api/v1/centers", "/api/v1/centers?pincode=380016", "/"]
        workers = []
        for i in range(8):
            rotated = paths[i % len(paths):] + paths[:i % len(paths)]
            w = threading.Thread(target=worker, args=(rotated,), daemon=True)
            w.start()
            workers.append(w)

        time.sleep(0.5)  # warm concurrent traffic
        urllib.request.urlopen(self.base_url + "/simulate/fail", timeout=5).read()
        time.sleep(1.0)  # traffic against the forced failure
        urllib.request.urlopen(self.base_url + "/simulate/recover", timeout=5).read()
        time.sleep(0.5)  # traffic after recovery
        stop.set()
        for w in workers:
            w.join(timeout=10)

        self.assertEqual(errors, "transport errors during load: %s" % errors[:5]
                         if errors else [])
        self.assertGreater(len(results), 50)
        codes = {code for code, _ in results}
        self.assertTrue(codes <= {200, 500}, f"unexpected status codes: {codes}")
        self.assertIn(500, codes)  # the forced failure was actually observed
        self.assertIn(200, codes)
        for code, raw in results:
            json.loads(raw)  # every response, including 500s, is valid JSON

        with urllib.request.urlopen(self.base_url + "/health", timeout=5) as resp:
            self.assertEqual(resp.status, 200)  # healthy again after recover


if __name__ == "__main__":
    unittest.main(verbosity=2)
