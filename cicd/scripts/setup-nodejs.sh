#!/bin/bash
# Node.js 安装脚本（幂等）
# 用法: bash cicd/scripts/setup-nodejs.sh
# 被 Jenkinsfile.web.groovy 使用

set -euo pipefail

NPM_MIRROR="${NPM_MIRROR:-https://mirrors.cloud.tencent.com/npm/}"
NODE_VERSION="${NODE_VERSION:-20.11.0}"

# ============================
# 1. Node.js（官方 tarball 安装到 /usr/local）
# ============================
if ! command -v node >/dev/null 2>&1; then
    echo ">>> 安装 Node.js ${NODE_VERSION}..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        NODE_ARCH="arm64"
    else
        NODE_ARCH="x64"
    fi
    curl -fsSL \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
        -o /tmp/node.tar.xz \
        && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
        && rm -f /tmp/node.tar.xz
fi
echo "Node: $(node --version)  [path: $(which node)]"
echo "npm:  $(npm --version)   [path: $(which npm)]"

# ============================
# 2. npm 镜像
# ============================
npm config set registry "${NPM_MIRROR}"
echo "npm registry: $(npm config get registry)"

# ============================
# 3. 跨 shell 验证
# ============================
echo "=== 跨 shell 验证 ==="
/bin/sh -c "node --version" && echo "node 在 /bin/sh 可用" || { echo "node 在 /bin/sh 不可用"; exit 1; }
