#!/usr/bin/env bash
# Process manager for the docker-free stack.
# Usage: scripts/stack.sh {start|stop|status|restart} [service...]
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV=/var/tmp/fls/sre
RUN="$REPO/run"
mkdir -p "$RUN/logs" "$RUN/pids"
export SRE_REPO="$REPO"
[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

PG_BIN=$ENV/mamba/pg/bin
PY=$ENV/venv/bin/python
NODE_BIN=$ENV/node/bin

ALL="postgres prometheus loki alloy demo-service agent-api frontend"

cmd_for() {
  case "$1" in
    prometheus)   echo "$ENV/bin/prometheus --config.file=$REPO/infrastructure/prometheus/prometheus.yml --storage.tsdb.path=$ENV/prom-data --web.listen-address=:9090" ;;
    loki)         echo "$ENV/bin/loki -config.file=$REPO/infrastructure/loki/loki-config.yml" ;;
    alloy)        echo "$ENV/bin/alloy run --storage.path=$ENV/alloy-data --server.http.listen-addr=127.0.0.1:12345 $REPO/infrastructure/alloy/config.alloy" ;;
    demo-service) echo "$PY -m uvicorn main:app --host 0.0.0.0 --port 9000 --app-dir $REPO/services/demo-service" ;;
    agent-api)    echo "env CUDA_VISIBLE_DEVICES=0 $PY -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --app-dir $REPO" ;;
    frontend)     echo "$NODE_BIN/npm --prefix $REPO/frontend run dev" ;;
    vllm)         echo "env CUDA_VISIBLE_DEVICES=0 $ENV/vllm-venv/bin/vllm serve ${LLM_MODEL:-Qwen/Qwen3-8B} --port 8001 --gpu-memory-utilization 0.85 --max-model-len 16384" ;;
  esac
}

start_one() {
  local s=$1
  if [ "$s" = postgres ]; then
    $PG_BIN/pg_ctl -D $ENV/pgdata -o "-p 15432 -k $ENV" -l $ENV/pg.log start >/dev/null 2>&1 || true
    echo "postgres: started (15432)"
    return
  fi
  local pidfile="$RUN/pids/$s.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$s: already running ($(cat "$pidfile"))"; return
  fi
  PATH="$NODE_BIN:$PATH" nohup $(cmd_for "$s") >"$RUN/logs/$s.out" 2>&1 &
  echo $! > "$pidfile"
  echo "$s: started ($!)"
}

stop_one() {
  local s=$1
  if [ "$s" = postgres ]; then
    $PG_BIN/pg_ctl -D $ENV/pgdata stop -m fast >/dev/null 2>&1 && echo "postgres: stopped" || echo "postgres: not running"
    return
  fi
  local pidfile="$RUN/pids/$s.pid"
  if [ -f "$pidfile" ]; then
    local pid; pid=$(cat "$pidfile")
    pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null && echo "$s: stopped" || echo "$s: not running"
    rm -f "$pidfile"
  else
    echo "$s: not running"
  fi
}

status_one() {
  local s=$1
  if [ "$s" = postgres ]; then
    $PG_BIN/pg_ctl -D $ENV/pgdata status >/dev/null 2>&1 && echo "postgres: UP" || echo "postgres: DOWN"
    return
  fi
  local pidfile="$RUN/pids/$s.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$s: UP ($(cat "$pidfile"))"
  else
    echo "$s: DOWN"
  fi
}

action=${1:-status}; shift || true
services=${*:-$ALL}
for s in $services; do
  case "$action" in
    start)   start_one "$s" ;;
    stop)    stop_one "$s" ;;
    status)  status_one "$s" ;;
    restart) stop_one "$s"; start_one "$s" ;;
  esac
done
