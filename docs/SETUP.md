# Setup — reproduce on any Linux box (no docker/sudo required)

Everything runs as unprivileged user-space processes. Tested on Ubuntu with
4× RTX PRO 6000 Blackwell; any x86_64 Linux with one CUDA GPU (≥24GB for
Qwen3-8B, ≥80GB for Qwen3-32B) works.

## 1. Prerequisites

- `curl`, `git`, `python3` on PATH
- [`uv`](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **local disk** path for runtimes (venvs are unusably slow on NFS)

## 2. Bootstrap

```bash
git clone https://github.com/MillionaireChen/agentic-sre-copilot-.git
cd agentic-sre-copilot-
SRE_ENV=/path/on/local/disk bash scripts/bootstrap.sh
```

The script is idempotent (re-run after a failure; finished steps skip).
It installs: Node 22, Prometheus/Loki/Alloy static binaries,
PostgreSQL 18 + pgvector via micromamba, the backend venv
(torch cu128 + sentence-transformers), a vLLM venv, MinerU, frontend
node_modules (symlinked to local disk), then creates `.env` and embeds the
runbooks into pgvector.

## 3. Configure

Edit `.env` if needed — model, ports, URLs. Key vars:

```
LLM_MODEL=Qwen/Qwen3-32B        # or Qwen/Qwen3-8B on smaller GPUs
LLM_BASE_URL=http://localhost:8001/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
DATABASE_URL=postgresql+psycopg://sre:sre@localhost:15432/sre
AUTO_INVESTIGATE_DELAY=30       # seconds; 0 = manual Investigate only
```

GPU pinning: services use `CUDA_VISIBLE_DEVICES=0`; change in
`scripts/stack.sh` if needed.

## 4. Run

```bash
export SRE_ENV=/path/on/local/disk    # if not the default
make up          # postgres, prometheus, loki, alloy, demo-service, api, frontend
make vllm        # LLM server (first run downloads weights, then ~4 min load)
make test        # 9 unit tests (mock LLM, no GPU needed)
make eval        # full 3-scenario evaluation (needs the LLM up)
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000 · Prometheus: :9090 · Loki: :3100

Stop everything: `make down` and `bash scripts/stack.sh stop vllm`.

## 5. Known version constraints

- **Blackwell (sm_120) + driver 575** → cu128 wheels only.
  vLLM 0.16.0 is the newest release that runs (0.17+ pin CUDA-13 torch).
  On older GPUs/newer drivers the latest vLLM is fine.
- Qwen3 emits `<think>` blocks; the LLM wrapper strips them before JSON
  parsing — don't disable that.
- Full pitfall log: [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md).
