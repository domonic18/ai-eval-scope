#!/usr/bin/env bash
# 腾讯工蜂合并请求操作脚本
# 通过工蜂 REST API 创建 MR、查询项目成员
# Token 通过环境变量 TENCENT_GIT_TOKEN 传入
# 配置方式：在 .claude/settings.local.json 的 env 字段中设置
set -euo pipefail

API_BASE_URL="https://git.code.tencent.com/api/v3"

# ---------- Token ----------

resolve_token() {
  if [[ -n "${TENCENT_GIT_TOKEN:-}" ]]; then
    echo "$TENCENT_GIT_TOKEN"
    return
  fi
  if [[ -n "${CODING_TOKEN:-}" ]]; then
    echo "$CODING_TOKEN"
    return
  fi
  echo "错误：未配置工蜂 API Token。" >&2
  echo "" >&2
  echo "请在 .claude/settings.local.json 中添加 env 配置：" >&2
  echo '  "env": { "TENCENT_GIT_TOKEN": "your-token" }' >&2
  exit 1
}

TOKEN=$(resolve_token)

# ---------- 工具函数 ----------

# 从 git remote URL 解析 owner/repo
detect_project_path() {
  local remote_url
  remote_url=$(git remote get-url origin 2>/dev/null || true)
  if [[ -z "$remote_url" ]]; then
    echo "错误：当前目录不是 git 仓库，无法检测远程项目。" >&2
    exit 1
  fi
  local path
  path=$(echo "$remote_url" | sed -E \
    -e 's|^git@git\.code\.tencent\.com:||' \
    -e 's|^https?://git\.code\.tencent\.com/||' \
    -e 's|\.git$||')
  if [[ -z "$path" || "$path" == "$remote_url" ]]; then
    echo "错误：无法从 remote URL 解析工蜂项目路径: $remote_url" >&2
    echo "请确认 remote origin 指向 git.code.tencent.com" >&2
    exit 1
  fi
  echo "$path"
}

# URL 编码（owner/repo → owner%2Frepo）
encode_path() {
  python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

# ---------- 子命令 ----------

cmd_members() {
  # 工蜂 API 的 query 参数不支持中文搜索，直接返回全部成员列表
  # 由 Claude 从结果中按 name 字段匹配
  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/members"
}

cmd_create() {
  local source_branch="${1:-}"
  local target_branch="${2:-}"
  local title="${3:-}"
  local description="${4:-}"
  local reviewer_ids="${5:-}"

  if [[ -z "$source_branch" || -z "$target_branch" || -z "$title" ]]; then
    echo "用法: tencent_mr.sh create <source_branch> <target_branch> <title> [description] [reviewer_ids]" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  # 工蜂 API 要求 reviewers 为逗号分隔的 ID 字符串，如 "123,456"
  local reviewers_str=""
  if [[ -n "$reviewer_ids" ]]; then
    reviewers_str=$(echo "$reviewer_ids" | jq -r 'if type == "array" then join(",") else . end')
  fi

  local body
  body=$(jq -n \
    --arg source "$source_branch" \
    --arg target "$target_branch" \
    --arg title "$title" \
    --arg desc "$description" \
    --arg reviewers "$reviewers_str" \
    '{source_branch: $source, target_branch: $target, title: $title, description: $desc, reviewers: $reviewers}')

  curl -sS \
    --request POST \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$body" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests"
}

# ---------- 命令分发 ----------

case "${1:-}" in
  members) cmd_members ;;
  create)  cmd_create "${2:-}" "${3:-}" "${4:-}" "${5:-}" "${6:-}" ;;
  *)
    echo "腾讯工蜂 MR 操作脚本"
    echo ""
    echo "用法:"
    echo "  $0 members                                  列出项目全部成员"
    echo "  $0 create <src> <tgt> <title> [desc] [rIds] 创建合并请求"
    echo ""
    echo "Token 配置：在 .claude/settings.local.json 中设置"
    echo '  "env": { "TENCENT_GIT_TOKEN": "your-token" }'
    exit 1
    ;;
esac
