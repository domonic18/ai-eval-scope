#!/bin/bash
# Node.js 安装脚本（幂等 + npm 健康检查）
# 用法: bash cicd/scripts/setup-nodejs.sh
# 被 Jenkinsfile.web.groovy 使用
#
# 不再「node 存在即跳过」——校验三件事：node 版本 == 目标、npm 真正可用，否则清理重装。
# - 版本校验：agent 可能漂移到过低版本（如健康的 20.11），仅查 npm 会放行 → NODE_VERSION 被忽略（#118 根因）。
# - npm 健康：tar 覆盖会让新旧 npm 文件混合，npm ci 崩溃（Class extends），而 npm -v 仍通过。
# 任一不符 → 先彻底清理 /usr/local 下旧 node 安装再干净重装，从根上避免覆盖残留。

set -euo pipefail

NPM_MIRROR="${NPM_MIRROR:-https://mirrors.cloud.tencent.com/npm/}"
# 22.15.0：backend vitest 4 依赖 std-env 4（ESM-only），而 backend 为 CommonJS，
# require(ESM) 需 Node 22.12+；Node 20.x 会 ERR_REQUIRE_ESM 崩溃。配合下方的 npm
# 健康检查 + 清理重装，可干净安装到此版本（不会像裸 tar 覆盖那样损坏 npm）。
NODE_VERSION="${NODE_VERSION:-22.15.0}"
NODE_DIST_URL="${NODE_DIST_URL:-https://mirrors.cloud.tencent.com/nodejs-release}"

# ============================
# 1. 判定是否需要（重新）安装 Node.js
# ============================
need_install=0
if ! command -v node >/dev/null 2>&1; then
    echo ">>> 未检测到 node，需安装。"
    need_install=1
elif [ "$(node -v 2>/dev/null | sed 's/^v//')" != "${NODE_VERSION}" ]; then
    # node 存在但版本与目标不符（agent 漂移，如健康的 20.11 vs 目标 22.15）：
    # 仅查 npm 健康会放行版本错的 node，导致 NODE_VERSION 被静默忽略（#118 根因）
    echo ">>> node $(node -v) 与目标 v${NODE_VERSION} 不符，清理重装。"
    need_install=1
elif ! npm ci --help >/dev/null 2>&1; then
    # npm --version 能过、但真实命令路径（ci）崩溃 → 安装已损坏（多为 tar 覆盖残留）
    echo ">>> 检测到 npm 异常（npm ci --help 失败），清理重装。"
    need_install=1
else
    echo ">>> node $(node -v) 与 npm 健康，跳过安装。"
fi

if [ "$need_install" -eq 1 ]; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        NODE_ARCH="arm64"
    else
        NODE_ARCH="x64"
    fi
    # 先彻底清理旧 node 安装（bin / 全局模块 / headers），避免 tar 覆盖残留损坏 npm
    echo ">>> 清理旧 node 安装..."
    rm -rf /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
           /usr/local/lib/node_modules /usr/local/include/node
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
