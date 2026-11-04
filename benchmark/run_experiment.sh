#!/usr/bin/env bash
# =============================================================================
# IT457 Cloud Computing - Week 3 Automated Failover Experiment Launcher
# Runs the full two-zone architecture locally and executes the failover suite
# =============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$DIR")"

echo "======================================================================="
echo "   STARTING COWIN TWO-ZONE HIGH AVAILABILITY EXPERIMENT ENVIRONMENT    "
echo "======================================================================="

cleanup() {
    echo -e "\n🧹 Tearing down local processes..."
    kill $PID_INST_A 2>/dev/null || true
    kill $PID_INST_B 2>/dev/null || true
    kill $PID_ALB 2>/dev/null || true
    echo "✅ Cleaned up all background services."
}

trap cleanup EXIT INT TERM

# 1. Start Node Zone A
echo "▶️  Starting Lookup Service Node A (Zone: ap-south-1a) on port 8081..."
AWS_AZ="ap-south-1a" AWS_INSTANCE_ID="i-0a1b2c3d-zone-a" \
    python3 "$PROJECT_ROOT/service/app.py" --port 8081 --zone ap-south-1a > /dev/null 2>&1 &
PID_INST_A=$!

# 2. Start Node Zone B
echo "▶️  Starting Lookup Service Node B (Zone: ap-south-1b) on port 8082..."
AWS_AZ="ap-south-1b" AWS_INSTANCE_ID="i-0e5f6g7h-zone-b" \
    python3 "$PROJECT_ROOT/service/app.py" --port 8082 --zone ap-south-1b > /dev/null 2>&1 &
PID_INST_B=$!

# 3. Start ALB Simulator
echo "▶️  Starting Application Load Balancer Proxy on port 8080..."
python3 "$DIR/alb_simulator.py" --port 8080 > /dev/null 2>&1 &
PID_ALB=$!

echo "⏳ Waiting for initial ALB health checks to mark targets healthy (3s)..."
sleep 3

# 4. Run Benchmark Test Suite
echo "🚀 Executing automated failover benchmark runner..."
python3 "$DIR/failover_benchmark.py" --url "http://localhost:8080" --duration 32 --rps 10

echo "✅ Experiment completed successfully!"
