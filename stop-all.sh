#!/usr/bin/env bash

set -euo pipefail

WHAT_IF=0

if [[ "${1:-}" == "--what-if" || "${1:-}" == "-n" ]]; then
    WHAT_IF=1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_LOWER="$(echo "$ROOT" | tr '[:upper:]' '[:lower:]')"

SERVICE_PORTS=(1984 8765 8081 5000 5173)

declare -A TARGETS

add_target() {
    local pid="$1"
    local desc="$2"

    if [[ "$pid" == "$$" ]]; then
        return
    fi

    if [[ -n "$pid" ]]; then
        TARGETS["$pid"]="$desc"
    fi
}

echo "Searching matching TirednessWarning service processes..."

while IFS= read -r line; do
    pid="$(echo "$line" | awk '{print $1}')"
    cmd="$(echo "$line" | cut -d' ' -f2-)"
    cmd_lower="$(echo "$cmd" | tr '[:upper:]' '[:lower:]')"

    if [[ "$cmd_lower" != *"$ROOT_LOWER"* ]]; then
        continue
    fi

    if [[ "$cmd_lower" == *"facejavaserver/go2rtc"* && "$cmd_lower" == *"go2rtc"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"facepythonserver/websocket_server.py"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"frontpage/vue-tlias-management/src/py/eeg_0417.py"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"spring-boot:run"* && "$cmd_lower" == *"face-service"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"vue-tlias-management"* && "$cmd_lower" == *"vite"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"vue-tlias-management"* && "$cmd_lower" == *"npm run dev"* ]]; then
        add_target "$pid" "$cmd"
    elif [[ "$cmd_lower" == *"face-service/target/face-service-0.0.1-snapshot-exec.jar"* ]]; then
        add_target "$pid" "$cmd"
    fi
done < <(ps -eo pid=,args=)

for port in "${SERVICE_PORTS[@]}"; do
    if command -v lsof >/dev/null 2>&1; then
        while IFS= read -r pid; do
            [[ -z "$pid" ]] && continue
            cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            add_target "$pid" "$cmd listening on port $port"
        done < <(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)

    elif command -v ss >/dev/null 2>&1; then
        while IFS= read -r pid; do
            [[ -z "$pid" ]] && continue
            cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            add_target "$pid" "$cmd listening on port $port"
        done < <(
            ss -ltnp "sport = :$port" 2>/dev/null |
            grep -oP 'pid=\K[0-9]+' || true
        )

    elif command -v netstat >/dev/null 2>&1; then
        while IFS= read -r pid; do
            [[ -z "$pid" ]] && continue
            cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            add_target "$pid" "$cmd listening on port $port"
        done < <(
            netstat -ltnp 2>/dev/null |
            awk -v port=":$port" '$4 ~ port && $7 ~ /^[0-9]+\// {split($7,a,"/"); print a[1]}'
        )
    fi
done

if [[ "${#TARGETS[@]}" -eq 0 ]]; then
    echo "No matching TirednessWarning service processes were found."
    exit 0
fi

echo "Matched service processes:"

for pid in "${!TARGETS[@]}"; do
    echo "  PID $pid: ${TARGETS[$pid]}"
done

if [[ "$WHAT_IF" -eq 1 ]]; then
    echo "WhatIf mode enabled. No processes were stopped."
    exit 0
fi

for pid in "${!TARGETS[@]}"; do
    if kill -9 "$pid" 2>/dev/null; then
        echo "Stopped PID $pid"
    else
        echo "[WARN] Failed to stop PID $pid"
    fi
done