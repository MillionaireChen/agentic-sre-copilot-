# 部署笔记 / Deployment Notes（踩坑记录）

本项目在一台**没有 docker 权限、没有 sudo** 的共享 GPU 服务器上以纯用户态进程方式部署。
以下是部署过程中实际遇到的问题与解决办法，按时间顺序记录。

## 环境背景

- 4× RTX PRO 6000 Blackwell 96GB（sm_120，只能用 CUDA 12.8 系 wheel）
- `/home` 是 NFS 挂载（IO 极慢），本地盘 `/` 只剩 ~30GB
- 用户不在 `docker` 组，`sudo` 需要密码 → 整套 docker-compose 方案不可用

## 坑 1：没有 docker，观测栈全部用户态部署

docker compose 里的 postgres / prometheus / loki / grafana-alloy 全部替换为：

| 组件 | 方案 |
|---|---|
| PostgreSQL + pgvector | micromamba 单二进制 → conda-forge 装 `postgresql` + `pgvector`，`initdb` 到本地盘，非特权端口 15432 |
| Prometheus / Loki / Alloy | 官方静态二进制直接运行 |
| 进程管理 | 自写 `scripts/stack.sh`（pid 文件 + nohup），替代 compose |

注意 `pg_ctl` 要加 `-k <dir>` 指定 unix socket 目录，否则默认写 `/var/run/postgresql` 没有权限。

## 坑 2：NFS 上跑 Python/node 会慢 100 倍

- 代码放 NFS（方便备份/git），但 **venv、node_modules、pgdata、Prometheus/Loki 数据全部放本地盘** `/var/tmp/fls/sre/`。
- `frontend/node_modules` 用软链接指到本地盘：`ln -s /var/tmp/fls/sre/frontend_node_modules frontend/node_modules`，Next.js 对软链 node_modules 兼容良好。
- 模型权重走 HF cache（NFS），只在加载时读一次，可接受。

## 坑 3：Loki 查询必须 URL-encode

`curl 'http://loki:3100/loki/api/v1/query_range?query={service="x"}'` 会直接返回非 JSON 错误，
必须 `curl -G --data-urlencode 'query={service="x"}'`。代码里用 httpx 的 params 传参即可自动处理。

## 坑 4：旧版 git 没有 `init -b`

服务器 git 版本较老，`git init -b main` 报 `unknown switch 'b'`，
需要 `git init && git symbolic-ref HEAD refs/heads/main`。

## 坑 5：验证阶段的 PromQL 时间窗口污染（最重要的一个）

回滚后立即用 `rate(...[5m])` 验证恢复，窗口里仍然包含故障期样本，
p95 依然显示 3.6s，Agent 误判"未恢复"并重新进入调查循环。

修复：验证前等待 75s，并把验证查询窗口缩小到 `[1m]`，保证 rate 窗口内只有回滚后的样本。
教训：**基于 rate/histogram_quantile 做恢复判定时，等待时间必须大于查询窗口长度**。

## 坑 6：低置信度诊断不能进入行动提议

最初的 confidence gate 在重查 2 轮仍 <0.65 时会"带着最佳假设"进入 remediation，
结果出现过 Agent 提议把 v1.7.3 回滚到 v1.8.0（坏版本）的危险行为。

修复：低置信度 + 重查轮次耗尽 → 直接生成报告交给人工，永远不基于低置信度诊断提议写操作。
同时提议节点会过滤掉我们自己执行的 rollback 部署记录，避免把回滚当成"肇事部署"。

## 坑 7：Qwen3 系输出要剥 `<think>` 块

Qwen3 默认思考模式输出 `<think>...</think>`，直接 `json.loads` 必炸。
LLM 封装里先 `re.sub(r"<think>.*?</think>", "", text, flags=re.S)` 再抽取 JSON。

## 坑 8：Blackwell (sm_120) 的 torch/vllm 版本

驱动 575 + Blackwell 只能用 cu128 wheel：
`uv pip install torch --index-url https://download.pytorch.org/whl/cu128`。
vLLM 需要较新版本（含 sm_120 kernel），LLM 与 embedding 统一固定在 GPU0（`CUDA_VISIBLE_DEVICES=0`）。

追加：最新 vllm 0.27 自带 cu130 编译的 torch，在驱动 575（CUDA 12.9）上启动直接报
`The NVIDIA driver on your system is too old (found version 12090)`。
排查结论（对各 release 的 torch pin 逐一核对）：vllm 0.17–0.26 pin torch 2.10/2.11、
0.27 pin 2.13，全是 CUDA 13 默认，均无法在该驱动上跑；**0.16.0（torch 2.9.1+cu128）
是能在驱动 575 上运行的最新版本**。

## 坑 9：同机多项目环境去重

同机另一个项目也建了一套几乎相同的环境。最终约定：9.4GB 的 vLLM venv 共享
（`/var/tmp/fls/vllm-venv`，py3.11，用 `python -m vllm.entrypoints.openai.api_server`
方式调用以避开 venv 内绝对路径 shebang），几百 MB 的 postgres/node/应用 venv 各自独立
（避免运行时互相耦合）。GPU 也做了分配：本项目 GPU0，另一项目 GPU3。
Qwen3-32B（62GB）与 Qwen3-Embedding-0.6B 权重放 NFS 的 HF cache 共享，只下载一次。
