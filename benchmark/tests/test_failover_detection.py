#!/usr/bin/env python3
"""
Unit tests for the failover detection logic in
benchmark/failover_benchmark.py (FailoverTracker).

Covers the measurements the Week 3 experiment report relies on:
- survivor-zone convergence detection (5 consecutive successful
  responses from a single zone after failure injection)
- the split between failover time (inject -> fully rerouted) and the
  disruption window (the span in which requests actually failed)
- the graceful-eviction case: zero failed requests, failover still
  detected, disruption window 0.0
- re-balancing detection after recovery

Stdlib only, no sockets, no sleeping - the tracker is driven with
synthetic timestamps. Run from the repository root with:

    python3 -m unittest discover -s benchmark -v

or directly:

    python3 benchmark/tests/test_failover_detection.py
"""

import os
import sys
import unittest

# Make `import failover_benchmark` work both under unittest discovery and
# when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from failover_benchmark import FailoverTracker  # noqa: E402

ZONE_A = "ap-south-1a"
ZONE_B = "ap-south-1b"


def feed(tracker, observations, t0=0.0, step=0.1):
    """Drive the tracker with (success, zone) pairs at synthetic times.

    Returns (events, times): the events of the final observation and the
    timestamp assigned to each observation.
    """
    events = []
    times = []
    for i, (success, zone) in enumerate(observations):
        t = t0 + i * step
        events = tracker.observe(success, zone, t)
        times.append(t)
    return events, times


class TestConvergenceDetection(unittest.TestCase):
    """Failover fires exactly when traffic converges on one surviving zone."""

    def test_no_failover_before_injection(self):
        tracker = FailoverTracker()
        # A long healthy run on one zone is not a failover.
        events, _ = feed(tracker, [(True, ZONE_B)] * 10)
        self.assertEqual(events, [])
        self.assertIsNone(tracker.t_failover_completed)
        self.assertIsNone(tracker.failover_time_seconds())

    def test_convergence_fires_on_fifth_consecutive_success(self):
        tracker = FailoverTracker()
        # Pre-injection history: strict round-robin alternation, ending on
        # Zone A so it cannot leak into the convergence window.
        feed(tracker, [(True, ZONE_A), (True, ZONE_B)] * 3 + [(True, ZONE_A)])
        tracker.note_failure_injected(100.0)

        # First four converged responses: no event yet.
        events, _ = feed(tracker, [(True, ZONE_B)] * 4, t0=100.1)
        self.assertEqual(events, [])
        self.assertIsNone(tracker.t_failover_completed)

        # Fifth consecutive success from the survivor zone: failover.
        events, times = feed(tracker, [(True, ZONE_B)], t0=100.5)
        self.assertEqual(events, ["failover"])
        self.assertEqual(tracker.survivor_zone, ZONE_B)
        self.assertEqual(tracker.t_failover_completed, 100.5)
        self.assertEqual(tracker.failover_time_seconds(), 0.5)

    def test_alternating_zones_never_converge(self):
        # Before eviction, round-robin keeps alternating between the
        # healthy target and the degraded one (which can still answer).
        tracker = FailoverTracker()
        tracker.note_failure_injected(100.0)
        events, _ = feed(tracker, [(True, ZONE_A), (True, ZONE_B)] * 6, t0=100.1)
        self.assertEqual(events, [])
        self.assertIsNone(tracker.t_failover_completed)

    def test_unknown_zone_responses_do_not_count(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(100.0)
        events, _ = feed(tracker, [(True, "unknown")] * 8, t0=100.1)
        self.assertEqual(events, [])
        self.assertIsNone(tracker.t_failover_completed)

    def test_failover_fires_only_once(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(100.0)
        feed(tracker, [(True, ZONE_B)] * 5, t0=100.1)
        events, _ = feed(tracker, [(True, ZONE_B)] * 5, t0=100.6)
        self.assertEqual(events, [])


class TestDisruptionWindow(unittest.TestCase):
    """The disruption window spans first to last failed request only."""

    def test_failures_before_injection_are_not_counted(self):
        tracker = FailoverTracker()
        feed(tracker, [(False, ZONE_A), (False, ZONE_B)], t0=1.0)
        tracker.note_failure_injected(100.0)
        self.assertEqual(tracker.disruption_window_seconds(), 0.0)
        self.assertIsNone(tracker.t_first_disruption)

    def test_window_spans_first_to_last_failure(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        events, _ = feed(tracker, [(False, ZONE_A)], t0=10.5)
        self.assertEqual(events, ["first_disruption"])
        feed(tracker, [(True, ZONE_A), (False, ZONE_A), (True, ZONE_B)], t0=10.6)
        feed(tracker, [(False, ZONE_A)], t0=11.4)
        self.assertEqual(tracker.t_first_disruption, 10.5)
        self.assertEqual(tracker.t_last_disruption, 11.4)
        self.assertEqual(tracker.disruption_window_seconds(), 0.9)

    def test_single_failed_request_has_zero_window(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        feed(tracker, [(False, ZONE_A)], t0=10.5)
        self.assertEqual(tracker.disruption_window_seconds(), 0.0)
        self.assertIsNotNone(tracker.t_first_disruption)


class TestGracefulEviction(unittest.TestCase):
    """A health-check-driven eviction can fail over with zero failed requests."""

    def test_zero_failures_but_failover_achieved(self):
        tracker = FailoverTracker()
        feed(tracker, [(True, ZONE_A), (True, ZONE_B)] * 2)
        tracker.note_failure_injected(10.0)

        # Graceful eviction: the degraded node keeps serving 200s while the
        # health checker evicts it, then traffic converges on Zone B.
        events, _ = feed(tracker,
                         [(True, ZONE_A), (True, ZONE_B), (True, ZONE_A)]
                         + [(True, ZONE_B)] * 5,
                         t0=10.1)

        self.assertEqual(events, ["failover"])
        self.assertEqual(tracker.survivor_zone, ZONE_B)
        # Failover time is measured even though nothing ever failed.
        self.assertEqual(tracker.failover_time_seconds(), 0.8)
        # The disruption window stays 0.0 - zero-downtime failover.
        self.assertEqual(tracker.disruption_window_seconds(), 0.0)
        self.assertIsNone(tracker.t_first_disruption)

    def test_failover_time_and_disruption_window_are_independent(self):
        # The split the benchmark report relies on: a failed request during
        # the transition does not change the failover time, and convergence
        # does not change the disruption window.
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        feed(tracker,
             [(False, ZONE_A), (True, ZONE_B), (False, ZONE_A)]  # disruption
             + [(True, ZONE_B)] * 5,                              # convergence
             t0=10.2)
        self.assertEqual(tracker.failover_time_seconds(), 0.9)
        self.assertEqual(tracker.disruption_window_seconds(), 0.2)


class TestRebalancing(unittest.TestCase):
    """Re-balancing is detected only after recovery is injected."""

    def test_no_rebalance_before_recovery_injected(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        feed(tracker, [(True, ZONE_B)] * 5, t0=10.1)
        # Zone A answering again before we triggered recovery: no event.
        events, _ = feed(tracker, [(True, ZONE_A)], t0=11.0)
        self.assertEqual(events, [])
        self.assertIsNone(tracker.t_rebalanced)

    def test_rebalance_after_recovery(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        feed(tracker, [(True, ZONE_B)] * 5, t0=10.1)
        tracker.note_recovery_injected(22.0)
        events, _ = feed(tracker, [(True, ZONE_B), (True, ZONE_A)], t0=22.1)
        self.assertEqual(events, ["rebalanced"])
        self.assertAlmostEqual(tracker.t_rebalanced, 22.2, places=9)


class TestFailoverTimeSummary(unittest.TestCase):
    def test_failover_time_none_when_never_converged(self):
        tracker = FailoverTracker()
        tracker.note_failure_injected(10.0)
        feed(tracker, [(True, ZONE_A), (True, ZONE_B)] * 3, t0=10.1)
        self.assertIsNone(tracker.failover_time_seconds())

    def test_failover_time_none_without_injection(self):
        tracker = FailoverTracker()
        feed(tracker, [(True, ZONE_B)] * 8)
        self.assertIsNone(tracker.failover_time_seconds())


if __name__ == "__main__":
    unittest.main(verbosity=2)
