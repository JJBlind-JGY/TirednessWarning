#!/usr/bin/env bash

set -euo pipefail

DRY_RUN=0

if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
    DRY_RUN=1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"

mkdir -p "$LOG_DIR"

join_root() {
    local relative_path="$1"
    echo "$ROOT/$relative_path"
}

assert_required_path() {
    local relative_path="$1"
    local full_path
    full_path="$(join_root "$relative_path")"

    if [[ ! -e "$full_path" ]]; then
        echo "[ERROR] Required file or directory is missing: $relative_path"
        exit 1
    fi

    echo "[OK] $relative_path"
}

test_port() {
    local port="$1"

    if command -v nc >/dev/null 2>&1; then
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1
        return $?
    fi

    timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$port" >/dev/null 2>&1
}

wait_port() {
    local port="$1"
    local timeout_seconds="${2:-20}"
    local elapsed=0

    while [[ "$elapsed" -lt "$timeout_seconds" ]]; do
        if test_port "$port"; then
            return 0
        fi

        sleep 0.5
        elapsed=$((elapsed + 1))
    done

    return 1
}

start_service() {
    local name="$1"
    local work_dir="$2"
    local command="$3"
    local port="$4"
    local startup_delay_seconds="${5:-2}"

    if [[ "$port" -gt 0 ]] && test_port "$port"; then
        echo "[SKIP] $name appears to be running on port $port."
        return 0
    fi

    echo "[START] $name"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "       WorkDir: $work_dir"
        echo "       Command: $command"
        return 0
    fi

    if [[ ! -d "$work_dir" ]]; then
        echo "[ERROR] WorkDir does not exist: $work_dir"
        exit 1
    fi

    local log_file="$LOG_DIR/$name.log"
    local pid_file="$LOG_DIR/$name.pid"

    (
        cd "$work_dir"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting $name"
        echo "Command: $command"
        exec bash -lc "$command"
    ) > "$log_file" 2>&1 &

    local pid=$!
    echo "$pid" > "$pid_file"

    echo "       PID: $pid"
    echo "       Log: $log_file"

    sleep "$startup_delay_seconds"

    if [[ "$port" -gt 0 ]]; then
        if wait_port "$port" 20; then
            echo "[READY] $name port $port is listening."
        else
            echo "[WARN] $name port $port is not ready yet. Check log: $log_file"
        fi
    fi
}

echo "Checking project files..."

assert_required_path "faceJavaServer/go2rtc/go2rtc"
assert_required_path "faceJavaServer/go2rtc/go2rtc.yaml"
assert_required_path "facePythonServer/models/enet_b2_7.onnx"
assert_required_path "facePythonServer/models/face_detection_yunet_2023mar.onnx"
assert_required_path "facePythonServer/websocket_server.py"
assert_required_path "faceJavaServer/pom.xml"
assert_required_path "faceJavaServer/face-service/pom.xml"
assert_required_path "frontPage/vue-tlias-management/src/py/EEG_0417.py"
assert_required_path "frontPage/vue-tlias-management/package.json"

echo ""
echo "Starting services in order..."

start_service \
    "go2rtc" \
    "$(join_root "faceJavaServer/go2rtc")" \
    "./go2rtc -config ./go2rtc.yaml" \
    1984 \
    2

start_service \
    "face-python" \
    "$(join_root "facePythonServer")" \
    "python3 ./websocket_server.py" \
    8765 \
    2

start_service \
    "face-java" \
    "$(join_root "faceJavaServer")" \
    "mvn -pl face-service -am clean package && java -jar ./face-service/target/face-service-0.0.1-SNAPSHOT-exec.jar" \
    8081 \
    6

start_service \
    "eeg-python" \
    "$ROOT" \
    "python3 ./frontPage/vue-tlias-management/src/py/EEG_0417.py" \
    5000 \
    2

start_service \
    "frontend-vite" \
    "$(join_root "frontPage/vue-tlias-management")" \
    "npm run dev -- --host 127.0.0.1" \
    5173 \
    2

echo ""

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run completed. No services were started."
else
    echo "Startup commands were issued."
    echo "Frontend: http://127.0.0.1:5173/"
    echo "go2rtc:   http://127.0.0.1:1984/"
    echo ""
    echo "Logs are saved in: $LOG_DIR"
    echo "If Vite chooses another port, check:"
    echo "  $LOG_DIR/frontend-vite.log"
fi