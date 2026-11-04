#!/usr/bin/env python3
"""
Visualize benchmark data from benchmark_requests.csv:
Generates an ASCII chart and timeline of the failover event,
zone distribution, and latency profile.
"""

import csv
import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(DIR, "benchmark_requests.csv")
JSON_FILE = os.path.join(DIR, "benchmark_results.json")

if not os.path.exists(CSV_FILE) or not os.path.exists(JSON_FILE):
    print("Benchmark results files not found. Run failover_benchmark.py first.")
    sys.exit(1)

with open(JSON_FILE) as f:
    summary = json.load(f)

rows = []
with open(CSV_FILE) as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print("\n" + "=" * 78)
print("       COWIN HIGH AVAILABILITY: VISUAL FAILOVER & TRAFFIC TIMELINE")
print("=" * 78)

# Group into 1-second buckets
buckets = {}
for r in rows:
    sec = int(float(r["elapsed_s"]))
    if sec not in buckets:
        buckets[sec] = {"zone_a": 0, "zone_b": 0, "errors": 0, "latencies": []}
    if r["success"] == "True":
        if "1a" in r["zone"]:
            buckets[sec]["zone_a"] += 1
        elif "1b" in r["zone"]:
            buckets[sec]["zone_b"] += 1
    else:
        buckets[sec]["errors"] += 1
    buckets[sec]["latencies"].append(float(r["latency_ms"]))

print("Time(s) | Traffic Route Visualizer                                    | Avg Latency")
print("------- | ----------------------------------------------------------- | -----------")
for sec in sorted(buckets.keys()):
    b = buckets[sec]
    bar_a = "🔵" * b["zone_a"]
    bar_b = "🟢" * b["zone_b"]
    bar_err = "🔴" * b["errors"]
    avg_lat = sum(b["latencies"]) / len(b["latencies"]) if b["latencies"] else 0.0

    note = ""
    if sec == 10:
        note = " ⚡ [Zone A Failure Injected]"
    elif sec == 12:
        note = " ⚠️ [ALB Detects & Evicts Zone A]"
    elif sec == 22:
        note = " 🔄 [Zone A Restored]"
    elif sec == 24:
        note = " 🎉 [ALB Re-admits Zone A]"

    line = f"{sec:2d}s     | {bar_a}{bar_b}{bar_err:<12} {note:<32} | {avg_lat:5.1f} ms"
    print(line)

print("-" * 78)
print("Legend: 🔵 = Zone A (ap-south-1a)  |  🟢 = Zone B (ap-south-1b)  |  🔴 = Error (HTTP 5xx)")
print("=" * 78 + "\n")

