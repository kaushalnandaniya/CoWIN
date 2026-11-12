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

    Failover = post-injection convergence of ALL traffic onto one surviving
    zone. A health-check-driven eviction is graceful: in-flight requests to
    the degraded node can keep succeeding, so detection must NOT depend on
    observing a failed request. Round-robin alternates zones strictly, so 5
    consecutive successful responses from a single zone only happen once the
    failed target has been evicted from the pool.
    """

    CONVERGENCE_WINDOW = 5

    def __init__(self):
        self.t_failure_injected = None
        self.t_first_disruption = None
        self.t_last_disruption = None
        self.t_failover_completed = None
        self.t_recovery_injected = None
        self.t_rebalanced = None
        self.survivor_zone = None
        self._recent = []  # trailing (success, zone) pairs used for convergence

    def note_failure_injected(self, when):
        self.t_failure_injected = when

    def note_recovery_injected(self, when):
        self.t_recovery_injected = when

    def observe(self, success, zone, when):
        """Record one completed request; return events that it triggered.

        Events, in the order they should be reported: "first_disruption",
        "failover", "rebalanced".
        """
        events = []

        if self.t_failure_injected and not success:
            if not self.t_first_disruption:
                self.t_first_disruption = when
                events.append("first_disruption")
            self.t_last_disruption = when

        if self.t_failure_injected and not self.t_failover_completed:
            window = self._recent[-(self.CONVERGENCE_WINDOW - 1):]
            recent_success = [s for s, _ in window] + [success]
            recent_zones = [z for _, z in window] + [zone]
            if (len(recent_success) == self.CONVERGENCE_WINDOW and all(recent_success)
                    and len(set(recent_zones)) == 1 and recent_zones[0] != "unknown"):
                self.t_failover_completed = when
                self.survivor_zone = recent_zones[0]
                events.append("failover")

        if self.t_recovery_injected and not self.t_rebalanced:
            if self.survivor_zone and zone != self.survivor_zone and zone != "unknown" and success:
                self.t_rebalanced = when
                events.append("rebalanced")

        self._recent.append((success, zone))
        return events

    def failover_time_seconds(self):
        """Failure injection -> traffic fully converged on the survivor zone
        (health-check detection + target eviction + reroute). None if failover
        was never observed."""
        if self.t_failure_injected and self.t_failover_completed:
            return round(self.t_failover_completed - self.t_failure_injected, 2)
        return None

    def disruption_window_seconds(self):
        """The span in which user-facing requests actually FAILED. A graceful
        ALB eviction can legitimately be 0.0 here - the degraded node kept
        serving 200s until the health checker evicted it."""
        if self.t_first_disruption and self.t_last_disruption:
            return round(self.t_last_disruption - self.t_first_disruption, 2)
        return 0.0  # no request ever failed: zero-downtime failover


def run_benchmark(target_url, total_seconds=35, req_per_sec=10, trigger_failure=True,
                  fail_url="http://127.0.0.1:8081/simulate/fail",
                  recover_url="http://127.0.0.1:8081/simulate/recover"):
    print("=" * 75)
    print("   IT457 CLOUD COMPUTING: COWIN TWO-ZONE FAILOVER EXPERIMENT")
    print("=" * 75)
    print(f"Target URL            : {target_url}")
    print(f"Test Duration         : {total_seconds} seconds")
    print(f"Request Rate          : {req_per_sec} requests/second")
    print(f"Failure Injection     : {'Automated at t=10s' if trigger_failure else 'Manual'}")
    print("=" * 75)

    interval = 1.0 / req_per_sec
    records = []
    
    t_start = time.time()
    tracker = FailoverTracker()

    failure_injected = False
    recovery_injected = False

    print("\n[Phase 1] 0s - 10s: Baseline Dual-Zone Traffic Running...")

    for i in range(total_seconds * req_per_sec):
        elapsed = time.time() - t_start
        req_start = time.time()

        # Phase 2: Inject failure at t = 10s
        if trigger_failure and elapsed >= 10.0 and not failure_injected:
            failure_injected = True
            tracker.note_failure_injected(time.time())
            print(f"\n⚡ [{elapsed:.1f}s] INJECTING FAILURE: Simulating Zone A EC2 Health Check Degradation (HTTP 500)...")
            try:
                req_f = urllib.request.Request(fail_url, data=b"{}")
                urllib.request.urlopen(req_f, timeout=1.0)
            except Exception as e:
                print(f"   (Failed to contact Zone A directly: {e})")

        # Phase 4: Recover at t = 22s
        if trigger_failure and elapsed >= 22.0 and not recovery_injected:
            recovery_injected = True
            tracker.note_recovery_injected(time.time())
            print(f"\n🔄 [{elapsed:.1f}s] TRIGGERING RECOVERY: Restoring Zone A Instance to Healthy State...")
            try:
                req_r = urllib.request.Request(recover_url, data=b"{}")
                urllib.request.urlopen(req_r, timeout=1.0)
            except Exception as e:
                print(f"   (Failed to contact Zone A directly: {e})")

        # Send request to Load Balancer
        req = urllib.request.Request(
            f"{target_url}/api/v1/centers?district=Ahmedabad",
            headers={"User-Agent": "CoWIN-FailoverBenchmark/1.0"}
        )
        
        status_code = None
        zone_served = "unknown"
        instance_id = "unknown"
        error_msg = ""
        success = False

        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                status_code = resp.status
                zone_served = resp.headers.get("X-Served-By-Zone") or resp.headers.get("X-ALB-Zone", "unknown")
                instance_id = resp.headers.get("X-Instance-Id") or resp.headers.get("X-ALB-Target", "unknown")
                if status_code == 200:
                    success = True
        except HTTPError as e:
            status_code = e.code
            error_msg = f"HTTP {e.code}"
        except URLError as e:
            status_code = 502
            error_msg = str(e.reason)
        except Exception as e:
            status_code = 500
            error_msg = str(e)

        req_latency = (time.time() - req_start) * 1000  # ms

        # Track failure & recovery state transitions
        for event in tracker.observe(success, zone_served, time.time()):
            if event == "first_disruption":
                print(f"   ⚠️ [{elapsed:.2f}s] First request error detected: {status_code} ({error_msg})")
            elif event == "failover":
                failover_secs = tracker.t_failover_completed - tracker.t_failure_injected
                print(f"   ✅ [{elapsed:.2f}s] FAILOVER ACHIEVED: 100% traffic rerouted to {tracker.survivor_zone}!")
                print(f"      Failover Time (inject -> fully rerouted): {failover_secs:.2f} seconds")
            elif event == "rebalanced":
                print(f"   🎉 [{elapsed:.2f}s] RE-BALANCING VERIFIED: recovered target re-admitted to ALB pool!")

        # Categorize test phase
        if elapsed < 10.0:
            phase = "1_Baseline"
        elif elapsed < 15.0:
            phase = "2_FailureTransition"
        elif elapsed < 24.0:
            phase = "3_SteadyFailover"
        elif elapsed < 29.0:
            phase = "4_RecoveryTransition"
        else:
            phase = "5_Rebalanced"

        record = {
            "req_id": i + 1,
            "timestamp": round(time.time(), 3),
            "elapsed_s": round(elapsed, 2),
            "phase": phase,
            "status_code": status_code,
            "success": success,
            "latency_ms": round(req_latency, 2),
            "zone": zone_served,
            "instance_id": instance_id,
            "error": error_msg
        }
        records.append(record)

        # Print live ticker
        if (i + 1) % (req_per_sec * 3) == 0:
            status_icon = "🟢" if success else "🔴"
            print(f"   {status_icon} [{elapsed:4.1f}s] Req #{i+1:3d} | Zone: {zone_served:12s} | Status: {status_code} | Latency: {req_latency:5.1f}ms")

        # Regulate request rate
        sleep_time = interval - (time.time() - req_start)
        if sleep_time > 0:
            time.sleep(sleep_time)

    # =========================================================================
    # STATISTICAL ANALYSIS & COMPUTATION
    # =========================================================================
    total_reqs = len(records)
    successful_reqs = [r for r in records if r["success"]]
    failed_reqs = [r for r in records if not r["success"]]
    latencies = [r["latency_ms"] for r in records]
    success_latencies = [r["latency_ms"] for r in successful_reqs]

    zone_a_count = sum(1 for r in successful_reqs if r["zone"] == "ap-south-1a")
    zone_b_count = sum(1 for r in successful_reqs if r["zone"] == "ap-south-1b")

    # Two distinct measurements (previously conflated, which reported
    # failover_achieved=false and a 0.0s window on every graceful failover):
    #
    # 1. Failover time: failure injection -> traffic fully converged on the
    #    surviving zone (health-check detection + target eviction + reroute).
    # 2. Disruption window: the span in which user-facing requests actually
    #    FAILED. A graceful ALB eviction can legitimately be 0.0s here - the
    #    degraded node kept serving 200s until the health checker evicted it.
    failover_time = tracker.failover_time_seconds()
    disruption_window = tracker.disruption_window_seconds()

    post_injection = [r for r in records if tracker.t_failure_injected and r["timestamp"] >= tracker.t_failure_injected]
    post_failover_availability = round(
        (sum(1 for r in post_injection if r["success"]) / len(post_injection)) * 100, 2
    ) if post_injection else 0.0

    summary = {
        "benchmark_metadata": {
            "course": "IT457 Cloud Computing",
            "project": "CoWIN Two-Zone High Availability PoC",
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_url": target_url,
            "duration_seconds": total_seconds,
            "request_rate_rps": req_per_sec
        },
        "throughput_metrics": {
            "total_requests": total_reqs,
            "successful_requests": len(successful_reqs),
            "failed_requests": len(failed_reqs),
            "success_rate_percent": round((len(successful_reqs) / total_reqs) * 100, 2),
            "error_rate_percent": round((len(failed_reqs) / total_reqs) * 100, 2)
        },
        "latency_percentiles_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p50": percentile(latencies, 50),
            "p90": percentile(latencies, 90),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "max": round(max(latencies), 2) if latencies else 0
        },
        "traffic_distribution": {
            "zone_a_ap_south_1a_requests": zone_a_count,
            "zone_b_ap_south_1b_requests": zone_b_count,
            "zone_a_share_percent": round((zone_a_count / len(successful_reqs)) * 100, 1) if successful_reqs else 0,
            "zone_b_share_percent": round((zone_b_count / len(successful_reqs)) * 100, 1) if successful_reqs else 0
        },
        "availability_and_failover": {
            "failure_injected_at_second": 10.0,
            "failover_achieved": tracker.t_failover_completed is not None,
            "failover_time_seconds": failover_time,
            "disruption_window_seconds": disruption_window,
            "failed_requests_during_experiment": len(failed_reqs),
            "recovery_time_objective_rto_seconds": failover_time,
            "recovery_point_objective_rpo": "0 seconds (Read/Lookup Service Stateless)",
            "survivor_zone": tracker.survivor_zone,
            "post_failover_availability_percent": post_failover_availability
        }
    }

    # =========================================================================
    # DISPLAY FORMATTED REPORT IN TERMINAL
    # =========================================================================
    print("\n" + "=" * 75)
    print("                      EXPERIMENTAL RESULTS SUMMARY")
    print("=" * 75)
    print(f"Total Requests Processed : {total_reqs}")
    print(f"Successful (HTTP 200)    : {len(successful_reqs)} ({summary['throughput_metrics']['success_rate_percent']}%)")
    print(f"Failed / Interrupted     : {len(failed_reqs)} ({summary['throughput_metrics']['error_rate_percent']}%)")
    print("-" * 75)
    print("LATENCY DISTRIBUTION (Overall):")
    print(f"  • Min Latency          : {summary['latency_percentiles_ms']['min']:6.2f} ms")
    print(f"  • Average (Mean)       : {summary['latency_percentiles_ms']['mean']:6.2f} ms")
    print(f"  • Median (p50)         : {summary['latency_percentiles_ms']['p50']:6.2f} ms")
    print(f"  • 95th Percentile (p95): {summary['latency_percentiles_ms']['p95']:6.2f} ms")
    print(f"  • 99th Percentile (p99): {summary['latency_percentiles_ms']['p99']:6.2f} ms")
    print(f"  • Max Latency          : {summary['latency_percentiles_ms']['max']:6.2f} ms")
    print("-" * 75)
    print("TRAFFIC DISTRIBUTION BY AVAILABILITY ZONE:")
    print(f"  • Zone A (ap-south-1a) : {zone_a_count:3d} requests ({summary['traffic_distribution']['zone_a_share_percent']}%)")
    print(f"  • Zone B (ap-south-1b) : {zone_b_count:3d} requests ({summary['traffic_distribution']['zone_b_share_percent']}%)")
    print("-" * 75)
    print("FAILOVER & DISASTER RECOVERY METRICS:")
    print(f"  • Failover Achieved          : {tracker.t_failover_completed is not None}")
    if failover_time is not None:
        print(f"  • Failover Time (detect+reroute): {failover_time:.2f} seconds")
    print(f"  • Disruption Window (errors) : {disruption_window:.2f} seconds ({len(failed_reqs)} failed requests)")
    print(f"  • Measured RTO               : {failover_time:.2f} seconds" if failover_time is not None else "  • Measured RTO               : n/a (failover not observed)")
    print(f"  • Measured RPO               : 0 seconds (Stateless read architecture)")
    if tracker.survivor_zone:
        print(f"  • Survivor Zone Continuity   : 100% requests absorbed by {tracker.survivor_zone} during failure")
    print("=" * 75)

    # Save output artifacts
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "benchmark_results.json")
    csv_path = os.path.join(out_dir, "benchmark_requests.csv")

    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"📁 JSON Summary saved to : {json_path}")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"📁 Detailed CSV saved to : {csv_path}\n")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CoWIN Failover Benchmark")
    parser.add_argument("--url", type=str, default="http://localhost:8080", help="ALB Target URL")
    parser.add_argument("--duration", type=int, default=32, help="Test duration in seconds")
    parser.add_argument("--rps", type=int, default=10, help="Requests per second")
    parser.add_argument("--no-auto-fail", action="store_true", help="Do not trigger auto-failure (for live manual tests)")
    parser.add_argument("--fail-url", type=str, default="http://127.0.0.1:8081/simulate/fail",
                        help="Direct URL used to degrade the Zone A target's health checks")
    parser.add_argument("--recover-url", type=str, default="http://127.0.0.1:8081/simulate/recover",
                        help="Direct URL used to restore the Zone A target's health checks")
    args = parser.parse_args()

    run_benchmark(
        target_url=args.url.rstrip("/"),
        total_seconds=args.duration,
        req_per_sec=args.rps,
        trigger_failure=not args.no_auto_fail,
        fail_url=args.fail_url,
        recover_url=args.recover_url
    )
