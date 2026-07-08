# eval-executor Docker 镜像（SCF 事件函数 / 本地 worker）
# 部署形态：腾讯云 SCF「事件函数 + Job 镜像 + 异步执行」（timeout ≤ 24h，docs/arch/09 §7.7 / 12）。
# 基于「预烘焙 Chromium 的基础镜像」（与 evaluator 同源），避免 Jenkins 构建时联网下载 Chromium。

FROM ccr.ccs.tencentyun.com/sasan/python:3.11-slim-pw

WORKDIR /app

# 安装 uv（与 evaluator CI 一致）
RUN pip install --no-cache-dir uv

# 先复制并安装评估器（path 依赖）与 executor
COPY evaluator ./evaluator
COPY executor ./executor

# 安装 agent-eval[vision]（playwright 版本与基础镜像一致 → chromium 已烘焙，无需下载）
# + eval-executor
RUN cd evaluator && uv pip install --system -e '.[vision]'
RUN cd executor && uv pip install --system -e .

# executor 工作区（下载输入、打包、评估产物）
ENV EVALEXECUTOR_WORKSPACE=/tmp/executor-workspace
# ResultSink 回传必须显式开启（per-job token 在 runner 里覆盖 api_key）
ENV AGENT_EVAL_UPLOAD=true

# 不监听端口：SCF 事件函数 + Job 镜像，事件经 SCF_CUSTOM_CONTAINER_EVENT 注入
ENTRYPOINT ["python", "-m", "eval_executor.executor.entrypoint"]
