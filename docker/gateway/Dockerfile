# eval-gateway Docker 镜像
# 与 web Dockerfile 风格一致：基于腾讯云 CCR node 镜像的 Python 镜像，容器内监听 9000。

FROM ccr.ccs.tencentyun.com/sasan/python:3.11-slim

WORKDIR /app

# 安装 uv（与 evaluator CI 一致）
RUN pip install --no-cache-dir uv

# 先复制并安装评估器（path 依赖）与 gateway
COPY evaluator ./evaluator
COPY gateway ./gateway

# 以 editable 方式安装 agent-eval[llm]（gateway 需 LLM Judge）+ eval-gateway，并锁定依赖
RUN cd evaluator && uv pip install --system -e '.[llm]'
RUN cd gateway && uv pip install --system -e .

# 容器内监听端口：默认 9000（腾讯云函数 SCF 要求）
ENV EVALGATEWAY_PORT=9000
EXPOSE 9000

CMD sh -c "uvicorn eval_gateway.main:app --host 0.0.0.0 --port ${EVALGATEWAY_PORT}"
