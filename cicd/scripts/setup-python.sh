#!/bin/bash
# Python3 + uv 安装脚本（幂等）
# 用法: bash cicd/scripts/setup-python.sh
# 被所有 Jenkinsfile 共用

set -euo pipefail

PYPI_MIRROR="${PYPI_MIRROR:-https://mirrors.cloud.tencent.com/pypi/simple}"
PYPI_HOST="${PYPI_HOST:-mirrors.cloud.tencent.com}"

# ============================
# 1. Python3
# ============================
if ! command -v python3 >/dev/null 2>&1; then
    echo ">>> 安装 Python3..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv
fi
echo "Python3: $(python3 --version)"

# ============================
# 2. uv（venv + symlink 到 /usr/local/bin）
# ============================
if ! command -v uv >/dev/null 2>&1; then
    echo ">>> 安装 uv..."
    python3 -m venv /opt/uv-env
    /opt/uv-env/bin/pip install --no-cache-dir uv \
        -i "${PYPI_MIRROR}" --trusted-host "${PYPI_HOST}"

    # 创建符号链接到系统 PATH 目录
    ln -sf /opt/uv-env/bin/uv  /usr/local/bin/uv
    ln -sf /opt/uv-env/bin/uvx /usr/local/bin/uvx
fi
echo "uv: $(uv --version)  [path: $(which uv)]"

# ============================
# 3. 跨 shell 验证
# ============================
echo "=== 跨 shell 验证 ==="
/bin/sh -c "uv --version" && echo "uv 在 /bin/sh 可用" || { echo "uv 在 /bin/sh 不可用"; exit 1; }
