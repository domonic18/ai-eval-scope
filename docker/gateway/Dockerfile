# eval-gateway Docker 镜像
# 基于「预烘焙 Chromium 的基础镜像」（docker/playwright-base），避免 Jenkins(腾讯云、无代理)
# 构建时联网下载 Chromium（新版 Playwright cft 路径国内镜像未同步，会 404/超时）。

FROM ccr.ccs.tencentyun.com/sasan/python:3.11-slim-pw

WORKDIR /app

# 安装 uv（与 evaluator CI 一致）
RUN pip install --no-cache-dir uv

# 先复制并安装评估器（path 依赖）与 gateway
COPY evaluator ./evaluator
COPY gateway ./gateway

# 安装 agent-eval[vision]（playwright 版本与基础镜像一致 → chromium 已烘焙，无需下载）
# + eval-gateway
RUN cd evaluator && uv pip install --system -e '.[vision]'
RUN cd gateway && uv pip install --system -e .

# 容器内监听端口：默认 9000（腾讯云函数 SCF 要求）
ENV EVALGATEWAY_PORT=9000
EXPOSE 9000

CMD sh -c "uvicorn eval_gateway.main:app --host 0.0.0.0 --port ${EVALGATEWAY_PORT}"
