#!/usr/bin/env bash
# One-shot environment bootstrap for a machine WITHOUT docker/sudo.
# Everything installs into $SRE_ENV (default /var/tmp/fls/sre — pick a fast
# local disk, NOT NFS). Re-runnable: finished steps are skipped.
#
#   SRE_ENV=/path/to/local/disk bash scripts/bootstrap.sh
#
# Prereqs: curl, git, python3, and `uv` (https://docs.astral.sh/uv/):
#   curl -LsSf https://astral.sh/uv/install.sh | sh
set -euo pipefail

ENV="${SRE_ENV:-/var/tmp/fls/sre}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"

NODE_VER=v22.13.1
PROM_VER=3.5.0
LOKI_VER=3.5.3
ALLOY_VER=1.10.1

mkdir -p "$ENV"/{bin,node,mamba,pgdata} "$REPO/run/logs"
cd "$ENV"

step() { printf '\n== %s ==\n' "$*"; }

step "Node $NODE_VER"
if [ ! -x node/bin/node ]; then
  curl -fsSL "https://nodejs.org/dist/$NODE_VER/node-$NODE_VER-linux-x64.tar.xz" -o node.tar.xz
  tar xf node.tar.xz -C node --strip-components=1 && rm node.tar.xz
fi
node/bin/node --version

step "Prometheus / Loki / Alloy binaries"
if [ ! -x bin/prometheus ]; then
  curl -fsSL "https://github.com/prometheus/prometheus/releases/download/v$PROM_VER/prometheus-$PROM_VER.linux-amd64.tar.gz" | tar xz
  cp "prometheus-$PROM_VER.linux-amd64"/{prometheus,promtool} bin/ && rm -rf "prometheus-$PROM_VER.linux-amd64"
fi
if [ ! -x bin/loki ]; then
  curl -fsSL "https://github.com/grafana/loki/releases/download/v$LOKI_VER/loki-linux-amd64.zip" -o loki.zip
  (cd bin && python3 -c "import zipfile; zipfile.ZipFile('../loki.zip').extractall()" && mv loki-linux-amd64 loki && chmod +x loki) && rm loki.zip
fi
if [ ! -x bin/alloy ]; then
  curl -fsSL "https://github.com/grafana/alloy/releases/download/v$ALLOY_VER/alloy-linux-amd64.zip" -o alloy.zip
  (cd bin && python3 -c "import zipfile; zipfile.ZipFile('../alloy.zip').extractall()" && mv alloy-linux-amd64 alloy && chmod +x alloy) && rm alloy.zip
fi

step "PostgreSQL + pgvector (micromamba, no root needed)"
if [ ! -x mamba/pg/bin/postgres ]; then
  curl -fsSL https://micro.mamba.pm/api/micromamba/linux-64/latest -o mm.tar.bz2
  tar xjf mm.tar.bz2 -C mamba bin/micromamba && rm mm.tar.bz2
  MAMBA_ROOT_PREFIX="$ENV/mamba/root" mamba/bin/micromamba create -y -q \
    -p "$ENV/mamba/pg" -c conda-forge postgresql pgvector
fi
if [ ! -f pgdata/PG_VERSION ]; then
  mamba/pg/bin/initdb -D pgdata -U sre --auth=trust -E UTF8
  mamba/pg/bin/pg_ctl -D pgdata -o "-p 15432 -k $ENV" -l pg.log start
  sleep 2
  mamba/pg/bin/psql -h "$ENV" -p 15432 -U sre -d postgres -c "CREATE DATABASE sre;"
  mamba/pg/bin/psql -h "$ENV" -p 15432 -U sre -d sre \
    -c "CREATE EXTENSION vector; ALTER USER sre PASSWORD 'sre';"
fi

step "Backend venv (python 3.11)"
if [ ! -x venv/bin/python ]; then
  "$UV" venv venv --python 3.11
  "$UV" pip install -p venv/bin/python \
    fastapi 'uvicorn[standard]' sqlalchemy 'psycopg[binary]' pgvector \
    pydantic-settings prometheus-client pyyaml httpx \
    langgraph langchain langchain-openai openai \
    langgraph-checkpoint-postgres sse-starlette pytest pytest-asyncio
  # embedding deps — cu128 is required on Blackwell (sm_120) with driver 575
  "$UV" pip install -p venv/bin/python torch --index-url https://download.pytorch.org/whl/cu128
  "$UV" pip install -p venv/bin/python sentence-transformers
fi

step "vLLM venv (cu128; 0.16.0 is the newest that runs on driver 575)"
if [ ! -x vllm-venv/bin/python ]; then
  "$UV" venv vllm-venv --python 3.11
  "$UV" pip install -p vllm-venv/bin/python 'vllm==0.16.0' --torch-backend=cu128
fi

step "MinerU venv (PDF/Office knowledge extraction, optional)"
if [ ! -x mineru-venv/bin/mineru ]; then
  "$UV" venv mineru-venv --python 3.11
  "$UV" pip install -p mineru-venv/bin/python mineru
fi

step "Frontend node_modules (on local disk, symlinked into the repo)"
mkdir -p frontend_node_modules
ln -sfn "$ENV/frontend_node_modules" "$REPO/frontend/node_modules"
PATH="$ENV/node/bin:$PATH" npm --prefix "$REPO/frontend" install --no-audit --no-fund

step ".env"
[ -f "$REPO/.env" ] || cp "$REPO/.env.example" "$REPO/.env"

step "Runbook ingestion (embeds into pgvector)"
CUDA_VISIBLE_DEVICES=0 "$ENV/venv/bin/python" -m backend.rag.ingest || \
  echo "WARN: ingestion failed (no GPU? run it later: make ingest)"

cat <<EOF

Bootstrap complete. Next:
  bash scripts/stack.sh start        # all services
  bash scripts/stack.sh start vllm   # LLM (GPU, ~4 min load)
  open http://localhost:3000

If \$SRE_ENV is not /var/tmp/fls/sre, adjust ENV= at the top of scripts/stack.sh
(or export it there too).
EOF
