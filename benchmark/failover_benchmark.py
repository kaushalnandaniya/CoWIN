#!/usr/bin/env python3
"""
CoWIN High-Availability Failover & Latency Benchmark Suite
IT457 Cloud Computing - Week 3 Experiment Runner

Tests and measures:
- Multi-AZ load balancing distribution across Availability Zones
- HTTP response latency percentiles (min, p50, p95, p99, max)
- Exact service disruption window during instance failure
- Recovery Time Objective (RTO) and Recovery Point Objective (RPO)
- Outputs results to JSON and CSV
"""

import argparse
import collections
import math
import tempfile
import csv
import json
import os
import sys
import time
from urllib.error import URLError, HTTPError
import urllib.request


def percentile(data, p):
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(sorted_data):
        return round(sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f]), 2)
    return round(sorted_data[f], 2)


class FailoverTracker:
    """Failure/recovery state transitions observed during a benchmark run.

    Estimate convergence from five successful samples on a non-failed zone.
    Reset history at injection. This is deterministic in the local round-robin
    simulator, but is only a client observation on AWS, where traffic need not
    alternate strictly. Verify ALB target health independently.
    """

    CONVERGENCE_WINDOW = 5

    def __init__(self, failed_zone=None):
        self.failed_zone = failed_zone
        self.t_stable_resumption = None
        self._success_streak = 0
        self.t_failure_injected = None
        self.t_first_disruption = None
        self.t_last_disruption = None
        self.t_failover_completed = None
        self.t_recovery_injected = None
        self.t_rebalanced = None
        self.survivor_zone = None
        self._recent = collections.deque(maxlen=self.CONVERGENCE_WINDOW)

    def note_failure_injected(self, when):
        self.t_failure_injected = when
        self._recent.clear()

    def note_recovery_injected(self, when):
        self.t_recovery_injected = when

    def observe(self, success, zone, when):
        """Record one completed request; return events that it triggered.

        Events, in the order they should be reported: "first_disruption",
        "failover", "rebalanced".
        """
        events = []

        if self.t_failure_injected is not None and not success:
            if self.t_first_disruption is None:
                self.t_first_disruption = when
                events.append("first_disruption")
            self.t_last_disruption = when

        if self.t_failure_injected is not None and self.t_failover_completed is None and self.t_recovery_injected is None:
            window = list(self._recent)[-(self.CONVERGENCE_WINDOW - 1):]
            recent_success = [s for s, _ in window] + [success]
            recent_zones = [z for _, z in window] + [zone]
            if (len(recent_success) == self.CONVERGENCE_WINDOW and all(recent_success)
                    and len(set(recent_zones)) == 1 and recent_zones[0] not in {"unknown", self.failed_zone}):
                self.t_failover_completed = when
                self.survivor_zone = recent_zones[0]
                events.append("failover")

        if self.t_recovery_injected is not None and self.t_rebalanced is None:
            if self.survivor_zone and zone != self.survivor_zone and zone != "unknown" and success and (self.failed_zone is None or zone == self.failed_zone):
                self.t_rebalanced = when
                events.append("rebalanced")

        if self.t_first_disruption is not None:
            survivor_ok = success and zone != "unknown" and zone != self.failed_zone
            self._success_streak = self._success_streak + 1 if survivor_ok else 0
            if not survivor_ok:
                self.t_stable_resumption = None
            elif self._success_streak >= self.CONVERGENCE_WINDOW and self.t_stable_resumption is None:
                self.t_stable_resumption = when
        self._recent.append((success, zone))
        return events

    def failover_time_seconds(self):
        """Failure injection -> traffic fully converged on the survivor zone
        (health-check detection + target eviction + reroute). None if failover
        was never observed."""
        if self.t_failure_injected is not None and self.t_failover_completed is not None:
            return round(self.t_failover_completed - self.t_failure_injected, 2)
        return None

    def disruption_window_seconds(self):
        """The span in which user-facing requests actually FAILED. A graceful
        ALB eviction can legitimately be 0.0 here - the degraded node kept
        serving 200s until the health checker evicted it."""
        if self.t_first_disruption is not None and self.t_last_disruption is not None:
            return round(self.t_last_disruption - self.t_first_disruption, 2)
        return 0.0  # no request ever failed: zero-downtime failover


    def resumption_seconds(self):
        if self.t_first_disruption is None:
            return 0.0
        if self.t_stable_resumption is None:
            return None
        return round(self.t_stable_resumption - self.t_first_disruption, 3)


def run_benchmark(target_url, total_seconds=35, req_per_sec=10, trigger_failure=True,
                  fail_url="http://127.0.0.1:8081/simulate/fail",
                  recover_url="http://127.0.0.1:8081/simulate/recover",
                  output_dir=None, environment="local-simulator", events_file=None,
                  failed_zone="ap-south-1a", timeout=1.5, fail_at=10.0,
                  recover_at=22.0):
    """Collect sequential HTTP samples; never operate AWS resources.

    Auto mode only changes loopback simulator health. For AWS, an operator
    records accepted stop/start commands in an event file. Detection is an
    observed survivor-response streak, not proof of ALB target health or RTO.
    """
    from datetime import datetime, timezone
    from pathlib import Path
    from urllib.parse import urlparse

    if any(not math.isfinite(v) or v <= 0 for v in (total_seconds, req_per_sec, timeout)):
        raise ValueError("duration, rps and timeout must be positive")
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("target must be an HTTP(S) URL without credentials")
    if environment not in {"local-simulator", "aws"}:
        raise ValueError("environment must be local-simulator or aws")
    if trigger_failure:
        if environment != "local-simulator":
            raise ValueError("AWS requires --no-auto-fail; resource actions are operator-owned")
        for url in (target_url, fail_url, recover_url):
            if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("automatic health injection is limited to loopback URLs")
        if not 0 <= fail_at < recover_at < total_seconds:
            raise ValueError("require 0 <= fail-at < recover-at < duration")
    out = Path(output_dir or tempfile.mkdtemp(prefix="cowin-benchmark-"))
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / name for name in ("benchmark_requests.csv", "benchmark_results.json")]
    if any(path.exists() for path in paths):
        raise ValueError("output already contains benchmark artifacts; choose a new directory")
    tracker = FailoverTracker(failed_zone=failed_zone)
    records, events, injection_errors = [], [], []
    start_epoch, start_clock = time.time(), time.monotonic()
    attempted = set()
    api_key = os.environ.get("COWIN_API_KEY")

    def note(event, timestamp, source, note=""):
        if event not in {"failure", "recovery"} or timestamp < start_epoch:
            return
        if event == "failure" and tracker.t_failure_injected is None:
            tracker.note_failure_injected(timestamp)
        elif event == "recovery" and tracker.t_failure_injected is not None and tracker.t_recovery_injected is None and timestamp >= tracker.t_failure_injected:
            tracker.note_recovery_injected(timestamp)
        else:
            return
        events.append({"event": event, "timestamp": timestamp,
                       "elapsed_s": round(timestamp - start_epoch, 3),
                       "source": source, "note": note})

    def read_events():
        if not events_file:
            return
        path = Path(events_file)
        if not path.exists():
            return
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("events file exceeds 1 MiB")
        # A writer can be between write() calls: ignore an incomplete last line.
        for line in path.read_text().splitlines(keepends=True):
            if not line.endswith("\n"):
                continue
            entry = json.loads(line)
            stamp = float(entry["timestamp"])
            if not math.isfinite(stamp) or stamp > time.time():
                raise ValueError("invalid/future event timestamp")
            note(entry["event"], stamp, "operator-event-file", entry.get("note", ""))

    print(f"Environment: {environment}; target: {target_url}; output: {out}")
    fields = ["req_id", "timestamp", "timestamp_utc", "elapsed_s", "phase",
              "status_code", "success", "latency_ms", "zone", "instance_id", "error"]
    # Flush each row so partial evidence survives interruption.
    with paths[0].open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        while time.monotonic() - start_clock < total_seconds:
            elapsed = time.monotonic() - start_clock
            if trigger_failure:
                for kind, at, url in (("failure", fail_at, fail_url),
                                      ("recovery", recover_at, recover_url)):
                    if elapsed >= at and kind not in attempted:
                        attempted.add(kind)
                        headers = {"X-API-Key": api_key} if api_key else {}
                        try:
                            with urllib.request.urlopen(urllib.request.Request(
                                    url, data=b"{}", headers=headers), timeout=timeout) as resp:
                                if resp.status != 200:
                                    raise ValueError(f"HTTP {resp.status}")
                            note(kind, time.time(), "local-health-simulation")
                        except Exception as exc:
                            injection_errors.append({"event": kind, "error": str(exc)})
            read_events()
            request_start = time.perf_counter()
            status, zone, instance, error = None, "unknown", "unknown", ""
            success = False
            req = urllib.request.Request(
                target_url.rstrip("/") + "/api/v1/centers?district=Ahmedabad",
                headers={"User-Agent": "CoWIN-FailoverBenchmark/2.0"})
            try:
                remaining = max(0.001, total_seconds - (time.monotonic() - start_clock))
                with urllib.request.urlopen(req, timeout=min(timeout, remaining)) as resp:
                    status = resp.status
                    zone = resp.headers.get("X-Served-By-Zone", "unknown")
                    instance = resp.headers.get("X-Instance-Id", "unknown")
                    body = json.loads(resp.read())
                    success = status == 200 and isinstance(body, dict) and isinstance(body.get("centers"), list)
                    if not success:
                        error = "response did not match lookup contract"
            except HTTPError as exc:
                status, error = exc.code, f"HTTP {exc.code}"
            except Exception as exc:
                error = str(exc)
            latency = (time.perf_counter() - request_start) * 1000
            stamp = time.time()
            observed = tracker.observe(success, zone, stamp)
            for event in observed:
                events.append({"event": event, "timestamp": stamp,
                               "elapsed_s": round(stamp - start_epoch, 3),
                               "source": "client-observation"})
            phase = ("recovery" if tracker.t_recovery_injected is not None else
                     "failure" if tracker.t_failure_injected is not None else "baseline")
            row = dict(zip(fields, [len(records) + 1, stamp,
                datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                round(stamp - start_epoch, 3), phase, status, success,
                round(latency, 3), zone, instance, error]))
            records.append(row)
            writer.writerow(row)
            handle.flush()
            # No catch-up bursts: this is a sequential sampler, not a stress generator.
            delay = min(1 / req_per_sec - (time.perf_counter() - request_start),
                        total_seconds - (time.monotonic() - start_clock))
            if delay > 0:
                time.sleep(delay)
    elapsed = time.monotonic() - start_clock
    ok = [r for r in records if r["success"]]
    latencies = [r["latency_ms"] for r in records]
    zones = collections.Counter(r["zone"] for r in ok)
    baseline_zones = {r["zone"] for r in ok if r["phase"] == "baseline"} - {"unknown"}
    # A single baseline node cannot demonstrate a two-zone failover.
    valid_baseline = failed_zone in baseline_zones and len(baseline_zones) >= 2
    observed_failover = tracker.t_failover_completed is not None and valid_baseline
    summary = {
        "benchmark_metadata": {
            "schema_version": 2, "environment": environment,
            "started_at_utc": datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(),
            "target_url": target_url, "requested_duration_seconds": total_seconds,
            "actual_duration_seconds": round(elapsed, 3), "request_rate_rps": req_per_sec,
            "achieved_rps": round(len(records) / elapsed, 3),
            "sampler": "sequential; target rate is an upper bound",
            "failure_mode": "health-degradation" if trigger_failure else "operator-recorded",
            "failed_zone": failed_zone, "convergence_window": tracker.CONVERGENCE_WINDOW,
        },
        "throughput_metrics": {"total_requests": len(records),
            "successful_requests": len(ok), "failed_requests": len(records) - len(ok),
            "success_rate_percent": round(100 * len(ok) / len(records), 3) if records else None},
        "latency_percentiles_ms": {**{f"p{p}": percentile(latencies, p) for p in (50, 90, 95, 99)},
            "min": min(latencies, default=None), "max": max(latencies, default=None),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None},
        "traffic_distribution": dict(zones),
        "availability_and_failover": {
            "two_zone_baseline_observed": valid_baseline,
            "failover_achieved": observed_failover,
            "failover_time_seconds": tracker.failover_time_seconds() if observed_failover else None,
            "disruption_window_seconds": tracker.disruption_window_seconds(),
            "stable_service_resumption_seconds": tracker.resumption_seconds(),
            "recovery_observed": tracker.t_rebalanced is not None,
            "survivor_zone": tracker.survivor_zone,
            "rpo": "not measured; this read-only test does not validate database replication",
            "measurement_note": "Survivor streak is a client estimate, not ALB health detection or guaranteed RTO. Disruption span is first-to-last failed sample, which can be zero for one error. Stable resumption measures first error to a successful survivor streak. Absence of samples cannot prove availability."
        },
        "events": events, "injection_errors": injection_errors,
        "limitations": ["No AWS health snapshots or video collected by this client.",
                         "Local simulation changes health only; it does not stop an EC2 instance.",
                         "Sequential sampling can miss short disruptions and cannot guarantee offered load."]
    }
    paths[1].write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Timestamped CoWIN failover sampler")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--duration", type=float, default=32)
    parser.add_argument("--rps", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument("--environment", choices=["local-simulator", "aws"], default="local-simulator")
    parser.add_argument("--no-auto-fail", action="store_true")
    parser.add_argument("--events-file", help="JSONL operator event log for manual runs")
    parser.add_argument("--output-dir", help="New run directory; existing results are never overwritten")
    parser.add_argument("--failed-zone", default="ap-south-1a")
    parser.add_argument("--fail-at", type=float, default=10)
    parser.add_argument("--recover-at", type=float, default=22)
    parser.add_argument("--fail-url", default="http://127.0.0.1:8081/simulate/fail")
    parser.add_argument("--recover-url", default="http://127.0.0.1:8081/simulate/recover")
    args = parser.parse_args()
    try:
        result = run_benchmark(args.url, args.duration, args.rps, not args.no_auto_fail,
            args.fail_url, args.recover_url, args.output_dir, args.environment,
            args.events_file, args.failed_zone, args.timeout, args.fail_at, args.recover_at)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if result["injection_errors"]:
        return 2
    if result["events"] and not result["availability_and_failover"]["failover_achieved"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
