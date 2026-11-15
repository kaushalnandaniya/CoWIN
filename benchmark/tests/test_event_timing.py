"""Timestamped operator markers must agree with CSV phases and metrics."""
import contextlib
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from failover_benchmark import run_benchmark


class EventTimingTests(unittest.TestCase):
    def run_marker_scenario(self, delayed=False, recover_before_publish=False):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'events.jsonl')
            marks = {}

            class Handler(BaseHTTPRequestHandler):
                count = 0

                def do_GET(self):
                    Handler.count += 1
                    n = Handler.count
                    if n == 3:
                        marks['failure'] = time.time()
                        if not delayed:
                            path.write_text(json.dumps({'event': 'failure',
                                'timestamp': marks['failure']}) + '\n')
                        # Marker is written while this failed request is in flight.
                        time.sleep(0.03)
                        self.send_response(503)
                        self.end_headers()
                        return
                    if delayed and n == 5:
                        entries = [{'event': 'failure', 'timestamp': marks['failure']}]
                        if recover_before_publish:
                            # Exercise chronological replay, not file-line order.
                            entries.insert(0, {'event': 'recovery', 'timestamp': time.time()})
                        path.write_text(''.join(json.dumps(e) + '\n' for e in entries))
                    zone = 'a' if n == 1 else 'b'
                    self.send_response(200)
                    self.send_header('X-Served-By-Zone', zone)
                    self.end_headers()
                    self.wfile.write(b'{"centers": []}')

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = run_benchmark(f'http://127.0.0.1:{server.server_port}',
                        total_seconds=0.35, req_per_sec=100, timeout=0.2,
                        trigger_failure=False, environment='aws', events_file=path,
                        failed_zone='a', output_dir=d)
                with Path(d, 'benchmark_requests.csv').open() as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual([r['phase'] for r in rows[:3]],
                                 ['baseline', 'baseline', 'failure'])
                self.assertEqual(rows[2]['status_code'], '503')
                disruptions = [e for e in result['events'] if e['event'] == 'first_disruption']
                self.assertEqual(len(disruptions), 1)
                self.assertEqual(disruptions[0]['timestamp'], float(rows[2]['timestamp']))
                resumption = result['availability_and_failover']['stable_service_resumption_seconds']
                self.assertIsNotNone(resumption)
                self.assertGreater(resumption, 0)
                self.assertEqual(result['throughput_metrics']['failed_requests'], 1)
                self.assertTrue(result['availability_and_failover']['two_zone_baseline_observed'])
                if recover_before_publish:
                    self.assertEqual(rows[4]['phase'], 'recovery')
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_marker_during_slow_failed_request(self):
        self.run_marker_scenario()

    def test_late_marker_reconciles_already_flushed_rows(self):
        self.run_marker_scenario(delayed=True)

    def test_late_out_of_order_markers_replay_by_timestamp(self):
        self.run_marker_scenario(delayed=True, recover_before_publish=True)


if __name__ == '__main__':
    unittest.main()
