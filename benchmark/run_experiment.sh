#!/usr/bin/env bash
# =============================================================================
# IT457 Cloud Computing - Week 3 Automated Failover Experiment Launcher
# Runs the full two-zone architecture locally and executes the failover suite
#
# Ports can be overridden when the defaults are already occupied:
#   ALB_PORT=9000 ZONE_A_PORT=9001 ZONE_B_PORT=9002 ./run_experiment.sh
# =============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$DIR")"

ALB_PORT="${ALB_PORT:-8080}"
ZONE_A_PORT="${ZONE_A_PORT:-8081}"
ZONE_B_PORT="${ZONE_B_PORT:-8082}"

LOG_DIR="$(mktemp -d /tmp/cowin-experiment-logs.XXXXXX)"

echo "======================================================================="
echo "   STARTING COWIN TWO-ZONE HIGH AVAILABILITY EXPERIMENT ENVIRONMENT    "
echo "======================================================================="
echo "   ALB port: $ALB_PORT | Zone A port: $ZONE_A_PORT | Zone B port: $ZONE_B_PORT"
echo "   Service logs: $LOG_DIR"

cleanup() {
    echo -e "\n🧹 Tearing down local processes..."
    kill $PID_INST_A 2>/dev/null || true
    kill $PID_INST_B 2>/dev/null || true
    kill $PID_ALB 2>/dev/null || true
    echo "✅ Cleaned up all background services."
}

trap cleanup EXIT INT TERM

fail_with_logs() {
    echo ""
    echo "❌ EXPERIMENT SETUP FAILED: $1"
    echo "--- Zone A service log ---"; tail -n 10 "$LOG_DIR/zone_a.log" 2>/dev/null || true
    echo "--- Zone B service log ---"; tail -n 10 "$LOG_DIR/zone_b.log" 2>/dev/null || true
    echo "--- ALB simulator log  ---"; tail -n 10 "$LOG_DIR/alb.log" 2>/dev/null || true
    echo "If a port is already in use, override it, e.g.:"
    echo "   ALB_PORT=9000 ZONE_A_PORT=9001 ZONE_B_PORT=9002 $0"
    exit 1
}

# Poll until a URL responds with the expected marker, or fail loudly.
wait_for_endpoint() {
    local url="$1" marker="$2" name="$3"
    for _ in $(seq 1 50); do
        if curl -sf -m 2 "$url" 2>/dev/null | grep -q "$marker"; then
            echo "   ✅ $name is up ($url)"
            return 0
        fi
        sleep 0.2
    done
    fail_with_logs "$name did not come up at $url (expected response containing '$marker')"
}

# 1. Start Node Zone A
echo "▶️  Starting Lookup Service Node A (Zone: ap-south-1a) on port $ZONE_A_PORT..."
AWS_AZ="ap-south-1a" AWS_INSTANCE_ID="i-0a1b2c3d-zone-a" \
    python3 "$PROJECT_ROOT/service/app.py" --port "$ZONE_A_PORT" --zone ap-south-1a \
    > "$LOG_DIR/zone_a.log" 2>&1 &
PID_INST_A=$!

# 2. Start Node Zone B
echo "▶️  Starting Lookup Service Node B (Zone: ap-south-1b) on port $ZONE_B_PORT..."
AWS_AZ="ap-south-1b" AWS_INSTANCE_ID="i-0e5f6g7h-zone-b" \
    python3 "$PROJECT_ROOT/service/app.py" --port "$ZONE_B_PORT" --zone ap-south-1b \
    > "$LOG_DIR/zone_b.log" 2>&1 &
PID_INST_B=$!

# 3. Start ALB Simulator
echo "▶️  Starting Application Load Balancer Proxy on port $ALB_PORT..."
python3 "$DIR/alb_simulator.py" --port "$ALB_PORT" \
    --target-ports "$ZONE_A_PORT" "$ZONE_B_PORT" \
    > "$LOG_DIR/alb.log" 2>&1 &
PID_ALB=$!

# 4. Verify every component is actually serving before measuring anything.
#    (Silently benchmarking the wrong listener produces garbage results.)
echo "⏳ Waiting for all components to become ready..."
wait_for_endpoint "http://127.0.0.1:$ZONE_A_PORT/health" '"status": "healthy"' "Zone A instance"
wait_for_endpoint "http://127.0.0.1:$ZONE_B_PORT/health" '"status": "healthy"' "Zone B instance"
wait_for_endpoint "http://127.0.0.1:$ALB_PORT/alb/status" "CoWIN Simulated Application Load Balancer" "ALB simulator"

echo "⏳ Allowing initial ALB health checks to settle (3s)..."
sleep 3

# 5. Run Benchmark Test Suite
echo "🚀 Executing automated failover benchmark runner..."
python3 "$DIR/failover_benchmark.py" \
    --url "http://localhost:$ALB_PORT" \
    --fail-url "http://127.0.0.1:$ZONE_A_PORT/simulate/fail" \
    --recover-url "http://127.0.0.1:$ZONE_A_PORT/simulate/recover" \
    --duration 32 --rps 10

echo "✅ Experiment completed successfully!"
