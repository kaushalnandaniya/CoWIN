#!/usr/bin/env python3
"""
Tests for the production-readiness features of the CoWIN Lookup Service:

- SQLite-backed center store (loading, filters, ordering, persistence,
  fallback) and byte-compatibility with the original file-backed responses
- API-key authentication on the mutating /simulate/* endpoints
- Per-client-IP token-bucket rate limiting (429s, exemptions)
- /metrics endpoint and its counters
- Tighter input validation and JSON 405s

Stdlib only. Run from the repository root with:

    python3 -m unittest discover -s service -v

or directly:

    python3 service/tests/test_production_readiness.py
"""

import json
import os
import sys
import tempfile
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

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(SERVICE_DIR, "centers_data.json")
TEST_ZONE = "test-zone-1a"
TEST_INSTANCE = "i-testinstance01"
TEST_API_KEY = "test-secret-key"

with open(DATA_FILE) as f:
    DATASET = json.load(f)


def start_test_server(**config_kwargs):
    """Start the service on an ephemeral port; returns (httpd, thread, base_url).

    A throwaway SQLite database in a temp directory is used unless the
    caller overrides db_file.
    """
    config_kwargs.setdefault("host", "127.0.0.1")
    config_kwargs.setdefault("port", 0)
    config_kwargs.setdefault("zone", TEST_ZONE)
    config_kwargs.setdefault("instance_id", TEST_INSTANCE)
    config_kwargs.setdefault("data_file", DATA_FILE)
    if "db_file" not in config_kwargs:
        tmpdir = tempfile.mkdtemp(prefix="cowin-test-db-")
        config_kwargs["db_file"] = os.path.join(tmpdir, "centers.db")
    config = app.ServiceConfig(**config_kwargs)
    httpd = app.create_server(config)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, thread, f"http://127.0.0.1:{port}"


def stop_test_server(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


class LiveServerTestCase(unittest.TestCase):
    """Base class: one live in-process server per test class."""

    server_kwargs = {}

    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.thread, cls.base_url = start_test_server(**cls.server_kwargs)

    @classmethod
    def tearDownClass(cls):
        stop_test_server(cls.httpd, cls.thread)

    def request(self, path, method="GET", headers=None):
        """Returns (status, headers, parsed_json_body) for any HTTP status."""
        req = urllib.request.Request(self.base_url + path, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, resp.headers, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, e.headers, json.loads(raw) if raw else None


class TestCenterStore(unittest.TestCase):
    """The SQLite store loads the dataset and answers filtered lookups."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="cowin-store-test-")
        self.db_file = os.path.join(self.tmpdir, "centers.db")

    def test_loads_dataset_and_counts_rows(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        self.assertEqual(store.backend, "sqlite")
        self.assertEqual(store.count(), len(DATASET))
        store.close()

    def test_unfiltered_query_returns_dataset_in_order(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        results = store.query()
        self.assertEqual(results, DATASET)  # same records, same order
        store.close()

    def test_pincode_filter_matches_list_semantics(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        pincode = DATASET[0]["pincode"]
        expected = [c for c in DATASET if c.get("pincode") == pincode]
        self.assertEqual(store.query(pincode=pincode), expected)
        store.close()

    def test_district_filter_is_case_insensitive_substring(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        district = DATASET[0]["district_name"]
        expected = [c for c in DATASET
                    if district.lower() in c.get("district_name", "").lower()]
        self.assertEqual(store.query(district=district.lower()), expected)
        self.assertGreater(len(expected), 0)
        store.close()

    def test_district_filter_treats_like_wildcards_literally(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        # "%" would match everything as a LIKE wildcard; as a literal
        # substring it matches nothing in the dataset.
        self.assertEqual(store.query(district="%"), [])
        store.close()

    def test_out_of_range_pincode_returns_empty(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        self.assertEqual(store.query(pincode=99999999999999999999), [])
        store.close()

    def test_database_persists_and_is_not_reloaded(self):
        store = app.CenterStore(self.db_file, DATA_FILE)
        store.close()
        # A second store on the same database keeps the rows exactly once.
        store = app.CenterStore(self.db_file, DATA_FILE)
        self.assertEqual(store.count(), len(DATASET))
        store.close()

    def test_missing_data_file_loads_fallback_record(self):
        store = app.CenterStore(self.db_file,
                                os.path.join(self.tmpdir, "missing.json"))
        self.assertEqual(store.count(), len(app.FALLBACK_CENTERS))
        self.assertEqual(store.query(), app.FALLBACK_CENTERS)
        store.close()

    def test_memory_fallback_matches_list_semantics(self):
        store = app.InMemoryCenterStore(DATA_FILE)
        self.assertEqual(store.backend, "memory")
        self.assertEqual(store.query(), DATASET)
        pincode = DATASET[0]["pincode"]
        self.assertEqual(store.query(pincode=pincode),
                         [c for c in DATASET if c.get("pincode") == pincode])
        store.close()

    def test_build_store_falls_back_when_db_unwritable(self):
        config = app.ServiceConfig(
            db_file="/nonexistent-dir-for-cowin/centers.db",
            data_file=DATA_FILE)
        store = app.build_store(config)
        self.assertEqual(store.backend, "memory")
        self.assertEqual(store.query(), DATASET)
        store.close()


class TestCentersByteCompatibility(LiveServerTestCase):
    """The HTTP responses stay identical to the file-backed version."""

    def test_unfiltered_response_matches_dataset(self):
        status, _, body = self.request("/api/v1/centers")
        self.assertEqual(status, 200)
        self.assertEqual(body["centers"], DATASET)
        self.assertEqual(body["count"], len(DATASET))

    def test_combined_filters_match_list_semantics(self):
        pincode = DATASET[0]["pincode"]
        district = DATASET[0]["district_name"]
        expected = [c for c in DATASET
                    if c.get("pincode") == pincode
                    and district.lower() in c.get("district_name", "").lower()]
        status, _, body = self.request(
            f"/api/v1/centers?pincode={pincode}&district={district}")
        self.assertEqual(status, 200)
        self.assertEqual(body["centers"], expected)
        self.assertGreater(body["count"], 0)


class TestApiKeyAuth(LiveServerTestCase):
    """The /simulate/* endpoints require X-API-Key when one is configured."""

    server_kwargs = {"api_key": TEST_API_KEY}

    def tearDown(self):
        self.request("/simulate/recover",
                     headers={app.AUTH_HEADER: TEST_API_KEY})

    def test_missing_key_returns_json_401(self):
        status, _, body = self.request("/simulate/fail")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Unauthorized")
        # The failure was not applied.
        status, _, body = self.request("/health")
        self.assertEqual(status, 200)

    def test_wrong_key_returns_json_401(self):
        status, _, body = self.request(
            "/simulate/fail", headers={app.AUTH_HEADER: "wrong-key"})
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Unauthorized")

    def test_post_without_key_returns_json_401(self):
        status, _, body = self.request("/simulate/fail", method="POST")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Unauthorized")

    def test_correct_key_allows_state_change(self):
        status, _, body = self.request(
            "/simulate/fail", headers={app.AUTH_HEADER: TEST_API_KEY})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unhealthy")
        status, _, _ = self.request("/health")
        self.assertEqual(status, 500)

    def test_read_endpoints_stay_open(self):
        for path in ("/health", "/api/v1/centers", "/metrics", "/"):
            status, _, _ = self.request(path)
            self.assertEqual(status, 200, path)

    def test_failed_attempts_are_counted(self):
        _, _, before = self.request("/metrics")
        self.request("/simulate/fail")  # 401
        self.request("/simulate/fail", headers={app.AUTH_HEADER: "nope"})  # 401
        _, _, after = self.request("/metrics")
        self.assertEqual(after["auth"]["enabled"], True)
        self.assertEqual(after["auth"]["failed_attempts"],
                         before["auth"]["failed_attempts"] + 2)


class TestDevModeAuth(LiveServerTestCase):
    """Without a configured key the simulation endpoints stay open."""

    def tearDown(self):
        self.request("/simulate/recover")

    def test_simulate_endpoints_open_without_key(self):
        status, _, _ = self.request("/simulate/fail")
        self.assertEqual(status, 200)
        status, _, _ = self.request("/simulate/recover")
        self.assertEqual(status, 200)
        _, _, body = self.request("/metrics")
        self.assertEqual(body["auth"]["enabled"], False)


class TestRateLimiting(LiveServerTestCase):
    """Token-bucket limiting returns JSON 429s and exempts health/metrics."""

    server_kwargs = {"rate_limit_rps": 5.0, "rate_limit_burst": 1.0}

    def test_burst_then_429_with_retry_after(self):
        status, _, _ = self.request("/api/v1/centers")
        self.assertEqual(status, 200)  # the single burst token
        status, headers, body = self.request("/api/v1/centers")
        self.assertEqual(status, 429)
        self.assertEqual(body["error"], "Too Many Requests")
        self.assertEqual(headers.get("Retry-After"), "1")

    def test_tokens_refill(self):
        self.request("/api/v1/centers")  # drain the bucket
        time.sleep(0.5)  # 5 rps refills ~2 tokens
        status, _, _ = self.request("/api/v1/centers")
        self.assertEqual(status, 200)

    def test_health_is_exempt(self):
        self.request("/api/v1/centers")  # drain the bucket
        for _ in range(10):
            status, _, _ = self.request("/health")
            self.assertEqual(status, 200)

    def test_metrics_is_exempt_and_counts_rejections(self):
        self.request("/api/v1/centers")
        self.request("/api/v1/centers")  # 429
        status, _, body = self.request("/metrics")
        self.assertEqual(status, 200)
        self.assertEqual(body["rate_limit"]["enabled"], True)
        self.assertGreaterEqual(body["rate_limit"]["rejected_requests"], 1)


class TestRateLimitDisabledByDefault(LiveServerTestCase):
    """With the shipped defaults nothing is ever throttled."""

    def test_many_requests_pass(self):
        for _ in range(20):
            status, _, _ = self.request("/api/v1/centers")
            self.assertEqual(status, 200)
        _, _, body = self.request("/metrics")
        self.assertEqual(body["rate_limit"]["enabled"], False)
        self.assertEqual(body["rate_limit"]["rejected_requests"], 0)


class TestMetricsEndpoint(LiveServerTestCase):
    """The /metrics snapshot reflects real traffic."""

    def test_metrics_shape(self):
        status, _, body = self.request("/metrics")
        self.assertEqual(status, 200)
        self.assertEqual(body["zone"], TEST_ZONE)
        self.assertEqual(body["instance_id"], TEST_INSTANCE)
        self.assertEqual(body["status"], "healthy")
        self.assertIn("uptime_seconds", body)
        self.assertIn("total_requests_served", body)
        self.assertEqual(body["store"]["backend"], "sqlite")
        self.assertEqual(body["store"]["centers_loaded"], len(DATASET))
        self.assertIn("requests_by_endpoint", body)
        self.assertIn("responses_by_status", body)
        self.assertIn("auth", body)
        self.assertIn("rate_limit", body)

    def test_request_counters_track_traffic(self):
        _, _, before = self.request("/metrics")
        before_centers = before["requests_by_endpoint"].get("/api/v1/centers", 0)
        self.request("/api/v1/centers")
        self.request("/api/v1/centers")
        self.request("/no-such-path")  # 404, still counted
        _, _, after = self.request("/metrics")
        self.assertEqual(
            after["requests_by_endpoint"].get("/api/v1/centers", 0),
            before_centers + 2)
        self.assertGreaterEqual(after["requests_by_endpoint"].get("/metrics", 0), 2)
        self.assertIn("404", after["responses_by_status"])
        self.assertIn("200", after["responses_by_status"])


class TestTightenedValidation(LiveServerTestCase):
    """The remaining loose inputs get consistent JSON errors."""

    def test_overlong_district_filter_returns_400(self):
        long_district = "a" * (app.MAX_DISTRICT_FILTER_LENGTH + 1)
        status, _, body = self.request(
            "/api/v1/centers?district=" + long_district)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Bad Request")

    def test_max_length_district_filter_is_accepted(self):
        status, _, _ = self.request(
            "/api/v1/centers?district=" + "a" * app.MAX_DISTRICT_FILTER_LENGTH)
        self.assertEqual(status, 200)

    def test_unsupported_methods_return_json_405(self):
        for method in ("PUT", "DELETE", "PATCH"):
            status, headers, body = self.request("/api/v1/centers", method=method)
            self.assertEqual(status, 405, method)
            self.assertEqual(body["error"], "Method Not Allowed", method)
            self.assertEqual(headers.get("Allow"), "GET, POST, OPTIONS", method)


if __name__ == "__main__":
    unittest.main(verbosity=2)
