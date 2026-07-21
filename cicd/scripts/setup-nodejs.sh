#!/bin/bash
# Node.js 安装脚本（幂等 + 版本校验）
# 用法: bash cicd/scripts/setup-nodejs.sh
# 被 Jenkinsfile.web.groovy 使用
#
# 关键：不再「node 存在即跳过」——而是校验已存在 node 是否满足最低版本要求。
# web/backend 的 vitest 链路会拉入 vite 8 / rolldown，其 engine 要求
# node ^20.19.0 || >=22.12.0。若 agent 预装 node 版本漂移（曾从 v22.15.0 退回
# v20.11.0），vitest 会因 node:util 缺 styleText 导出而在启动阶段崩溃。
# 故低于门槛时强制重装 NODE_VERSION，而非信任任何已存在的 node。

set -euo pipefail

NPM_MIRROR="${NPM_MIRROR:-https://mirrors.cloud.tencent.com/npm/}"
# 22.15.0：与历史成功构建（#107/#111）的 CI Node 一致，零版本差异风险。
NODE_VERSION="${NODE_VERSION:-22.15.0}"
# 最低版本门槛（对齐 vite 8 / rolldown 的 engine 要求 >=22.12.0）
NODE_MIN_MAJOR=22
NODE_MIN_MINOR=12
# 下载源：腾讯云镜像（内网可达），可用环境变量覆盖
NODE_DIST_URL="${NODE_DIST_URL:-https://mirrors.cloud.tencent.com/nodejs-release}"

# ============================
# 1. 判定是否需要（强制）安装 Node.js
# ============================
need_install=0
if ! command -v node >/dev/null 2>&1; then
    echo ">>> 未检测到 node，需安装。"
    need_install=1
else
    current="$(node -p "process.versions.node" 2>/dev/null || echo 0.0.0)"
    cur_major="$(printf '%s' "$current" | cut -d. -f1)"
    cur_minor="$(printf '%s' "$current" | cut -d. -f2)"
    cur_major="${cur_major:-0}"
    cur_minor="${cur_minor:-0}"
    if [ "$cur_major" -lt "$NODE_MIN_MAJOR" ] \
        || { [ "$cur_major" -eq "$NODE_MIN_MAJOR" ] && [ "$cur_minor" -lt "$NODE_MIN_MINOR" ]; }; then
        echo ">>> 已存在 node v${current} 不满足最低要求 >=${NODE_MIN_MAJOR}.${NODE_MIN_MINOR}，强制重装 v${NODE_VERSION}。"
        need_install=1
    else
        echo ">>> 已存在 node v${current} 满足要求，跳过安装。"
    fi
fi

if [ "$need_install" -eq 1 ]; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        NODE_ARCH="arm64"
    else
        NODE_ARCH="x64"
    fi
    echo ">>> 安装 Node.js v${NODE_VERSION}（来源 ${NODE_DIST_URL}）..."
    curl -fsSL \
        "${NODE_DIST_URL}/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
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
