# Playwright + Chromium 基础镜像（预烘焙，供 gateway 复用）
#
# 目的：新版 Playwright 改用 Chrome-for-Testing(cft)下载路径 /builds/cft/...，国内 npmmirror
# 未同步 → Jenkins(腾讯云、无代理)构建时 playwright install 会 404/超时。
# 解法：把 chromium 一次性烘焙进本基础镜像并推到 CCR，gateway 直接 FROM 它，构建时零外网下载。
#
# 与 evaluator/pyproject.toml 的 playwright 版本必须严格一致（否则 chromium 缓存不命中）。
#
# 构建并推送（需在有外网/带 VPN 的机器执行一次，低频；升级 playwright 时重建）：
#   docker build -f docker/playwright-base/Dockerfile -t ccr.ccs.tencentyun.com/sasan/python:3.11-slim-pw .
#   docker push ccr.ccs.tencentyun.com/sasan/python:3.11-slim-pw

FROM ccr.ccs.tencentyun.com/sasan/python:3.11-slim

# 安装与 evaluator 锁定的同一版本 playwright，并下载 Chromium（含 Debian 运行库）
RUN pip install --no-cache-dir "playwright==1.60.0" \
    && playwright install --with-deps chromium
