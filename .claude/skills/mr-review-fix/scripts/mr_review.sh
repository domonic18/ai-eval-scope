#!/usr/bin/env bash
# 工蜂 MR 评论获取与分析脚本
# 获取 MR 的评论/notes，识别 AI 代码审查中的 critical/warning/suggestion 问题
# Token 通过环境变量 TENCENT_GIT_TOKEN 传入
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

encode_path() {
  python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

# ---------- 子命令 ----------

# 根据 IID 查找 MR，返回 MR 的全局 ID 和基本信息
cmd_find_by_iid() {
  local iid="${1:-}"
  if [[ -z "$iid" ]]; then
    echo "用法: mr_review.sh find-by-iid <mr_iid>" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests?iid=${iid}&per_page=1"
}

# 根据源分支查找 MR（返回最近一个开放的 MR）
cmd_find_by_branch() {
  local branch="${1:-}"
  if [[ -z "$branch" ]]; then
    branch=$(git branch --show-current 2>/dev/null || true)
    if [[ -z "$branch" ]]; then
      echo "错误：无法获取当前分支，请手动指定源分支。" >&2
      exit 1
    fi
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests?source_branch=${branch}&state=opened&per_page=1"
}

# 获取 MR 的全部 notes（需要 MR 的全局 ID）
cmd_notes() {
  local mr_id="${1:-}"
  if [[ -z "$mr_id" ]]; then
    echo "用法: mr_review.sh notes <mr_id>" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  # 获取所有 notes，按创建时间正序排列，支持分页
  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/notes?per_page=100&sort=asc"
}

# 获取 MR 的单条评论（需要 MR 全局 ID 和 note_id）
cmd_get_note() {
  local mr_id="${1:-}"
  local note_id="${2:-}"
  if [[ -z "$mr_id" || -z "$note_id" ]]; then
    echo "用法: mr_review.sh get-note <mr_id> <note_id>" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/notes/${note_id}"
}

# 编辑 MR 的单条评论（需要 MR 全局 ID 和 note_id，内容通过 stdin 传入）
cmd_edit_note() {
  local mr_id="${1:-}"
  local note_id="${2:-}"
  if [[ -z "$mr_id" || -z "$note_id" ]]; then
    echo "用法: mr_review.sh edit-note <mr_id> <note_id>" >&2
    echo "评论内容通过 stdin 传入" >&2
    exit 1
  fi

  local body
  body=$(cat)
  if [[ -z "$body" ]]; then
    echo "错误：评论内容不能为空。请通过 stdin 传入评论内容。" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  local json_body
  json_body=$(python3 -c "import json, sys; print(json.dumps({'body': sys.stdin.read()}))" <<< "$body")

  curl -sS \
    --request PUT \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$json_body" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/notes/${note_id}"
}

# 获取 MR 的全部 discussions（含线程评论，需要 MR 的全局 ID）
cmd_discussions() {
  local mr_id="${1:-}"
  if [[ -z "$mr_id" ]]; then
    echo "用法: mr_review.sh discussions <mr_id>" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/discussions?per_page=100"
}

# 回复指定评论（需要 MR 全局 ID 和 note_id，回复内容通过 stdin 传入）
cmd_reply_note() {
  local mr_id="${1:-}"
  local note_id="${2:-}"
  if [[ -z "$mr_id" || -z "$note_id" ]]; then
    echo "用法: mr_review.sh reply-note <mr_id> <note_id>" >&2
    echo "回复内容通过 stdin 传入" >&2
    exit 1
  fi

  local body
  body=$(cat)
  if [[ -z "$body" ]]; then
    echo "错误：回复内容不能为空。请通过 stdin 传入回复内容。" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  # 查找 note_id 所属的 discussion_id
  local discussions discussion_id
  discussions=$(curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/discussions?per_page=100")

  discussion_id=$(echo "$discussions" | python3 -c "
import sys, json
note_id = '${note_id}'
data = json.load(sys.stdin)
for d in data:
    for n in d.get('notes', []):
        if str(n['id']) == note_id:
            print(d['id'])
            sys.exit(0)
print('', end='')
sys.exit(1)
" 2>/dev/null || true)

  if [[ -z "$discussion_id" ]]; then
    echo "错误：未找到 note_id=${note_id} 对应的 discussion。" >&2
    exit 1
  fi

  # 发送回复
  local json_body
  json_body=$(python3 -c "import json, sys; print(json.dumps({'body': sys.stdin.read()}))" <<< "$body")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$json_body" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/discussions/${discussion_id}/notes"
}

# 创建 MR 评论（需要 MR 全局 ID，评论内容通过 stdin 传入）
cmd_create_note() {
  local mr_id="${1:-}"
  if [[ -z "$mr_id" ]]; then
    echo "用法: mr_review.sh create-note <mr_id>" >&2
    echo "评论内容通过 stdin 传入" >&2
    exit 1
  fi

  local body
  body=$(cat)
  if [[ -z "$body" ]]; then
    echo "错误：评论内容不能为空。请通过 stdin 传入评论内容。" >&2
    exit 1
  fi

  local project_path encoded_path
  project_path=$(detect_project_path)
  encoded_path=$(encode_path "$project_path")

  local json_body
  json_body=$(python3 -c "import json, sys; print(json.dumps({'body': sys.stdin.read()}))" <<< "$body")

  curl -sS \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$json_body" \
    "${API_BASE_URL}/projects/${encoded_path}/merge_requests/${mr_id}/notes"
}

# ---------- 命令分发 ----------

case "${1:-}" in
  find-by-iid)    cmd_find_by_iid "${2:-}" ;;
  find-by-branch) cmd_find_by_branch "${2:-}" ;;
  notes)          cmd_notes "${2:-}" ;;
  get-note)       cmd_get_note "${2:-}" "${3:-}" ;;
  edit-note)      cmd_edit_note "${2:-}" "${3:-}" ;;
  discussions)    cmd_discussions "${2:-}" ;;
  reply-note)     cmd_reply_note "${2:-}" "${3:-}" ;;
  create-note)    cmd_create_note "${2:-}" ;;
  *)
    echo "工蜂 MR 评论获取与分析脚本"
    echo ""
    echo "用法:"
    echo "  $0 find-by-iid <mr_iid>        根据 MR IID 查找 MR 信息"
    echo "  $0 find-by-branch [branch]      根据源分支查找 MR（默认当前分支）"
    echo "  $0 notes <mr_id>                获取 MR 全部 notes"
    echo "  $0 get-note <mr_id> <note_id>   获取 MR 单条评论"
    echo "  echo 'body' | $0 edit-note <mr_id> <note_id>"
    echo "                                 编辑 MR 单条评论（内容通过 stdin 传入）"
    echo "  $0 discussions <mr_id>          获取 MR 全部 discussions"
    echo "  echo 'body' | $0 reply-note <mr_id> <note_id>"
    echo "                                 回复指定评论（内容通过 stdin 传入）"
    echo "  echo 'body' | $0 create-note <mr_id>"
    echo "                                 创建 MR 评论（内容通过 stdin 传入）"
    echo ""
    echo "Token 配置：在 .claude/settings.local.json 中设置"
    echo '  "env": { "TENCENT_GIT_TOKEN": "your-token" }'
    exit 1
    ;;
esac
