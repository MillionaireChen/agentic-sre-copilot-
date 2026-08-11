# Deployment Notes (pitfalls encountered)

This project is deployed on a shared GPU server **without docker access and
without sudo** — every service runs as an unprivileged user-space process.
These are the real problems hit during setup and how they were solved,
in chronological order.

## Environment

- 4× RTX PRO 6000 Blackwell 96GB (sm_120, requires CUDA 12.8-line wheels)
- `/home` is an NFS mount (very slow IO); local disk `/` had only ~30GB free
- User is not in the `docker` group and `sudo` requires a password →
  the whole docker-compose approach was off the table

## Pitfall 1: no docker — user-space observability stack

Every container in the original design was replaced:

| Component | Replacement |
|---|---|
| PostgreSQL + pgvector | micromamba single binary → conda-forge `postgresql` + `pgvector`, `initdb` onto local disk, unprivileged port 15432 |
| Prometheus / Loki / Alloy | official static binaries run directly |
| Process management | hand-rolled `scripts/stack.sh` (pid files + nohup) instead of compose |

Note: `pg_ctl` needs `-k <dir>` to relocate the unix socket — the default
`/var/run/postgresql` is not writable without root.

## Pitfall 2: Python/node on NFS is ~100x slower

- Code lives on NFS (backup/git convenience), but **venvs, node_modules,
  pgdata and Prometheus/Loki data all live on local disk** (`/var/tmp/fls/sre/`).
- `frontend/node_modules` is a symlink to local disk:
  `ln -s /var/tmp/fls/sre/frontend_node_modules frontend/node_modules` —
  Next.js handles symlinked node_modules fine.
- Model weights go through the HF cache (NFS): read once at load time, acceptable.

## Pitfall 3: Loki queries must be URL-encoded

`curl 'http://loki:3100/loki/api/v1/query_range?query={service="x"}'` returns
a non-JSON error; you need `curl -G --data-urlencode 'query={service="x"}'`.
In code, passing params through httpx handles this automatically.

## Pitfall 4: old git has no `init -b`

The server's git predates `git init -b main`
(`unknown switch 'b'`) — use `git init && git symbolic-ref HEAD refs/heads/main`.

## Pitfall 5: PromQL rate-window pollution in verification (the important one)

Verifying recovery immediately after a rollback with `rate(...[5m])` still
includes incident-period samples in the window — p95 still read 3.6s, the
agent judged "not recovered" and re-opened the investigation.

Fix: wait 75s before verifying and shrink verification queries to `[1m]`, so
the rate window only contains post-rollback samples.
Lesson: **when judging recovery with rate/histogram_quantile, the wait time
must exceed the query window length.**

## Pitfall 6: a low-confidence diagnosis must never reach remediation

The original confidence gate would proceed to remediation "with the best
hypothesis" after 2 re-investigation rounds even below 0.65 — at one point the
agent proposed rolling back v1.7.3 to v1.8.0 (the bad version).

Fix: low confidence + exhausted rounds → write a report and hand off to a
human; never propose write actions from a low-confidence diagnosis. The
proposal node also filters out rollback deployments we performed ourselves so
a rollback is never mistaken for the offending deploy.

## Pitfall 7: strip Qwen3 `<think>` blocks

Qwen3 thinking mode emits `<think>...</think>`; `json.loads` on raw output
always fails. The LLM wrapper strips it with
`re.sub(r"<think>.*?</think>", "", text, flags=re.S)` before JSON extraction.

## Pitfall 8: torch/vllm versions for Blackwell (sm_120)

Driver 575 + Blackwell only works with cu128 wheels:
`uv pip install torch --index-url https://download.pytorch.org/whl/cu128`.
LLM and embedding are pinned to GPU0 (`CUDA_VISIBLE_DEVICES=0`).

Follow-up: the latest vllm (0.27) ships a cu130-built torch and fails on
driver 575 (CUDA 12.9) with `The NVIDIA driver on your system is too old
(found version 12090)`. Checking each release's torch pin: vllm 0.17–0.26 pin
torch 2.10/2.11 and 0.27 pins 2.13 — all CUDA 13 by default.
**vllm 0.16.0 (torch 2.9.1+cu128) is the newest release that runs on this
driver.**

## Pitfall 9: deduplicating environments across projects on one box

Another project on the same machine had built a nearly identical runtime.
Final arrangement: the 9.4GB vLLM venv is shared
(`/var/tmp/fls/vllm-venv`, py3.11 — invoke via
`python -m vllm.entrypoints.openai.api_server` to sidestep the venv's
absolute-path shebangs), while the few-hundred-MB postgres/node/app venvs stay
independent to avoid runtime coupling. GPUs are partitioned per project
(this one on GPU0). Qwen3-32B (62GB) and Qwen3-Embedding-0.6B weights live in
a shared HF cache on NFS — downloaded once.

## Pitfall 10: eval scenarios polluting each other through the deployments table

Consecutive eval scenarios saw each other's deployment rows (and our own
rollback records) and blamed the wrong deploy — e.g. the redis outage got
attributed to a leftover v1.8.0 row. Fix: demo reset deletes all
non-baseline deployment rows, and deployment records store the full
before/after config diff so a config regression is actually visible as such.
