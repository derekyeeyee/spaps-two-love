#!/usr/bin/env bash
# Clean, ASCII-only; works on macOS and Linux.

set -euo pipefail

CIPHER_IMAGE="ghcr.io/kikkia/yt-cipher:master"
LAVA_JAR="lavalink/Lavalink.jar"

# Allow overriding ports:  LAVA_PORT=2334 CIPHER_PORT=18001 ./start.sh
LAVA_PORT="${LAVA_PORT:-2333}"
CIPHER_PORT="${CIPHER_PORT:-8001}"

# Predeclare to keep set -u happy in trap
CIPHER_CID=""
LAVA_PID=""

# --- helpers ---
kill_port() {
  # Kill any process using a TCP port (macOS/Linux)
  local the_port="$1"
  local pids
  pids="$(lsof -t -i tcp:"$the_port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Killing processes on port $the_port: $pids"
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}

wait_for_port() {
  # Wait until host:port starts accepting TCP connections
  local host="$1"
  local the_port="$2"
  local timeout="${3:-30}"
  local delay="${4:-1}"

  local start
  start="$(date +%s)"
  while true; do
    if nc -z "$host" "$the_port" >/dev/null 2>&1; then
      return 0
    fi
    local now
    now="$(date +%s)"
    if (( now - start >= timeout )); then
      echo "Timeout waiting for $host:$the_port" >&2
      return 1
    fi
    sleep "$delay"
  done
}

cleanup() {
  echo "Shutting down..."
  if [[ -n "$LAVA_PID" ]]; then kill "$LAVA_PID" 2>/dev/null || true; fi
  if [[ -n "$CIPHER_CID" ]]; then docker stop "$CIPHER_CID" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

echo "== Cleaning ports =="
kill_port "$CIPHER_PORT"
kill_port "$LAVA_PORT"
echo "Ports are clear."

echo "== Starting yt-cipher on :$CIPHER_PORT =="
CIPHER_CID="$(docker run -d -p "${CIPHER_PORT}:8001" "$CIPHER_IMAGE")"
echo "Container: $CIPHER_CID"
wait_for_port "localhost" "$CIPHER_PORT" 30
# Try a lightweight HTTP check (don’t fail if it’s missing)
curl -fsS "http://localhost:${CIPHER_PORT}/health" >/dev/null 2>&1 || true
echo "yt-cipher is up."

echo "== Starting Lavalink on :$LAVA_PORT =="
# Double-check no one grabbed the port in the meantime
kill_port "$LAVA_PORT"

# run Lavalink *from inside* the lavalink directory so it finds application.yml and plugins
pushd lavalink >/dev/null
nohup java -jar Lavalink.jar > ../lavalink.out 2>&1 &
LAVA_PID=$!
popd >/dev/null

# Wait for port to open, but also bail early if the process dies
start_ts=$(date +%s)
while ! nc -z localhost "$LAVA_PORT" >/dev/null 2>&1; do
  # if java exited, show logs and fail
  if ! ps -p "$LAVA_PID" >/dev/null 2>&1; then
    echo "❌ Lavalink exited during startup. Last 80 log lines:"
    tail -n 80 lavalink.out || true
    exit 1
  fi
  now_ts=$(date +%s)
  if (( now_ts - start_ts > 60 )); then
    echo "❌ Timeout waiting for Lavalink on :$LAVA_PORT. Last 80 log lines:"
    tail -n 80 lavalink.out || true
    exit 1
  fi
  sleep 1
done
echo "✅ Lavalink is up."


echo "== Starting Discord bot =="
if [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi
export LAVALINK_URI="http://localhost:${LAVA_PORT}"
python bot.py
