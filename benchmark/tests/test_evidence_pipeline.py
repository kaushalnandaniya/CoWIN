"""Regression coverage for non-fabricated failover evidence."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from failover_benchmark import FailoverTracker, run_benchmark
from generate_plots import render


class EvidenceTests(unittest.TestCase):
    def test_preinjection_streak_does_not_leak(self):
        t = FailoverTracker(failed_zone='a')
        for n in range(10):
            t.observe(True, 'b', n)
        t.note_failure_injected(10)
        self.assertNotIn('failover', t.observe(True, 'b', 10.1))

    def test_failed_zone_cannot_be_survivor(self):
        t = FailoverTracker(failed_zone='a')
        t.note_failure_injected(0)
        for n in range(6):
            t.observe(True, 'a', n + 0.1)
        self.assertIsNone(t.failover_time_seconds())

    def test_zero_timestamp_is_valid(self):
        t = FailoverTracker(failed_zone='a')
        t.note_failure_injected(0)
        for n in range(5):
            t.observe(True, 'b', n + 0.1)
        self.assertEqual(t.failover_time_seconds(), 4.1)

    def test_single_error_is_not_zero_resumption(self):
        t = FailoverTracker(failed_zone='a')
        t.note_failure_injected(1)
        t.observe(False, 'unknown', 2)
        self.assertEqual(t.disruption_window_seconds(), 0)
        self.assertIsNone(t.resumption_seconds())
        for n in range(5):
            t.observe(True, 'b', 3 + n / 10)
        self.assertEqual(t.resumption_seconds(), 1.4)
        t.observe(False, 'unknown', 4)
        self.assertIsNone(t.resumption_seconds())

    def test_recovery_does_not_invent_failover(self):
        t = FailoverTracker(failed_zone='a')
        t.note_failure_injected(1)
        t.note_recovery_injected(2)
        for n in range(6):
            t.observe(True, 'b', 3 + n)
        self.assertIsNone(t.failover_time_seconds())

    def test_history_is_bounded(self):
        t = FailoverTracker()
        for n in range(10000):
            t.observe(True, 'b', n)
        self.assertEqual(len(t._recent), 5)

    def test_aws_auto_injection_rejected_before_network(self):
        with patch('urllib.request.urlopen') as network, self.assertRaises(ValueError):
            run_benchmark('http://example.invalid', environment='aws')
        network.assert_not_called()

    def test_remote_auto_injection_rejected(self):
        with self.assertRaises(ValueError):
            run_benchmark('http://example.invalid')

    def test_positive_rate_required(self):
        with self.assertRaises(ValueError):
            run_benchmark('http://localhost', req_per_sec=0)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'benchmark_results.json').write_text('original')
            with self.assertRaises(ValueError):
                run_benchmark('http://localhost', output_dir=d)
            self.assertEqual(Path(d, 'benchmark_results.json').read_text(), 'original')

    def test_failed_request_has_no_fake_http_status(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            result = run_benchmark('http://127.0.0.1:1', total_seconds=0.04,
                                   req_per_sec=100, trigger_failure=False, output_dir=d)
            self.assertGreater(result['throughput_metrics']['failed_requests'], 0)
            self.assertIsNone(result['availability_and_failover']['failover_time_seconds'])
            self.assertFalse(result['availability_and_failover']['failover_achieved'])
            self.assertEqual(result['events'], [])
            path = render(d)
            svg = path.read_text()
            self.assertIn('local-simulator', svg)
            self.assertNotIn('at 10.000s', svg)

    def test_empty_plot_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'benchmark_results.json').write_text('{}')
            Path(d, 'benchmark_requests.csv').write_text('elapsed_s,latency_ms\n')
            with self.assertRaises(ValueError):
                render(d)

class ManualRunTests(unittest.TestCase):
    def test_manual_events_and_readonly_verifier(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'service'))
        from verify_deployment import check
        with tempfile.TemporaryDirectory() as d:
            events = Path(d, 'events.jsonl')
            class Handler(BaseHTTPRequestHandler):
                count = 0
                def do_GET(self):
                    Handler.count += 1
                    failed = events.exists() and 'failure' in events.read_text()
                    zone = 'b' if failed else ('a' if Handler.count % 2 else 'b')
                    self.send_response(200)
                    self.send_header('X-Served-By-Zone', zone)
                    self.send_header('X-Instance-Id', 'instance-' + zone)
                    self.end_headers()
                    self.wfile.write(json.dumps({'centers': [], 'status': 'healthy'}).encode())
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            timer = None
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                verification = check(url, samples=4, interval=0)
                self.assertTrue(verification['two_zones_observed'])
                def mark():
                    events.write_text(json.dumps({'event': 'failure', 'timestamp': time.time()}) + '\n')
                timer = threading.Timer(0.15, mark)
                timer.start()
                with contextlib.redirect_stdout(io.StringIO()):
                    result = run_benchmark(url, total_seconds=0.5, req_per_sec=80,
                        trigger_failure=False, environment='aws', events_file=events,
                        failed_zone='a', output_dir=d)
                self.assertTrue(result['availability_and_failover']['failover_achieved'])
                self.assertEqual(result['events'][0]['source'], 'operator-event-file')
                self.assertEqual(result['benchmark_metadata']['environment'], 'aws')
                svg = render(d).read_text()
                self.assertIn('failure at ', svg)
                self.assertNotIn('at 10.000s', svg)
            finally:
                if timer:
                    timer.cancel()
                    timer.join()
                server.shutdown()
                server.server_close()
                worker.join()


if __name__ == '__main__':
    unittest.main()
