#!/usr/bin/env node
/**
 * 腾讯工蜂 Issue 管理脚本（跨平台）
 *
 * 用法:
 *   node tencent_issue.mjs members
 *   node tencent_issue.mjs list [state] [labels]
 *   node tencent_issue.mjs get <iid>
 *   node tencent_issue.mjs create <title> [description] [labels] [assignee_id]
 *   node tencent_issue.mjs update <iid> [title] [labels] [assignee_id]
 *   node tencent_issue.mjs close <iid>
 *   node tencent_issue.mjs reopen <iid>
 *   node tencent_issue.mjs comment <iid> [body]
 *   echo "body" | node tencent_issue.mjs comment <iid>
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const API_BASE_URL = 'https://git.code.tencent.com/api/v3';

/**
 * 从 .claude/settings.local.json 的 env 字段加载环境变量。
 * 查找路径：当前 git 仓库根目录/.claude/settings.local.json
 */
function loadEnvFromSettings() {
  if (process.env.TENCENT_GIT_TOKEN) return; // 已有则跳过

  const gitRoot = runGit(['rev-parse', '--show-toplevel']);
  if (!gitRoot) return;

  const settingsPath = join(gitRoot, '.claude', 'settings.local.json');
  if (!existsSync(settingsPath)) return;

  try {
    const settings = JSON.parse(readFileSync(settingsPath, 'utf8'));
    const env = settings.env || {};
    for (const [key, value] of Object.entries(env)) {
      if (!process.env[key] && typeof value === 'string') {
        process.env[key] = value;
      }
    }
  } catch {
    // 配置文件解析失败，忽略
  }
}

class CliError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CliError';
  }
}

function fail(message) {
  throw new CliError(message);
}

function resolveToken() {
  const token = process.env.TENCENT_GIT_TOKEN || process.env.CODING_TOKEN;
  if (!token) {
    fail(
      '错误：未配置工蜂 API Token。\n\n请在 .claude/settings.local.json 中添加 env 配置：\n  "env": { "TENCENT_GIT_TOKEN": "your-token" }',
    );
  }
  return token;
}

function runGit(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8' }).trim();
  } catch {
    return '';
  }
}

function detectProjectPath() {
  const remoteUrl = runGit(['remote', 'get-url', 'origin']);
  if (!remoteUrl) {
    fail('错误：当前目录不是 git 仓库，或未配置 remote origin。');
  }

  const patterns = [
    /^git@git\.code\.tencent\.com:(.+?)(?:\.git)?$/,
    /^https?:\/\/git\.code\.tencent\.com\/(.+?)(?:\.git)?$/,
  ];

  for (const pattern of patterns) {
    const match = remoteUrl.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }

  fail(`错误：无法从 remote URL 解析工蜂项目路径: ${remoteUrl}\n请确认 remote origin 指向 git.code.tencent.com`);
}

async function apiRequest(path, options = {}) {
  const token = resolveToken();
  const fetchOptions = {
    headers: {
      'PRIVATE-TOKEN': token,
      'Content-Type': 'application/json',
    },
  };

  if (options.method) fetchOptions.method = options.method;
  if (options.json) fetchOptions.body = JSON.stringify(options.json);

  const resp = await fetch(`${API_BASE_URL}${path}`, fetchOptions);
  const text = await resp.text();

  if (!resp.ok) {
    fail(`请求失败：HTTP ${resp.status} ${resp.statusText}\n${text || '<empty body>'}`);
  }

  return text || '{}';
}

function readStdin() {
  try {
    return readFileSync(0, 'utf8').trim();
  } catch {
    return '';
  }
}

function getProjectEncoded() {
  return encodeURIComponent(detectProjectPath());
}

// ---------- 子命令 ----------

async function cmdMembers() {
  const encoded = getProjectEncoded();
  process.stdout.write(await apiRequest(`/projects/${encoded}/members`));
}

async function cmdList(state = 'opened', labels = '') {
  const encoded = getProjectEncoded();
  const params = [`per_page=20`, `state=${state}`];
  if (labels) params.push(`labels=${encodeURIComponent(labels)}`);
  process.stdout.write(await apiRequest(`/projects/${encoded}/issues?${params.join('&')}`));
}

async function cmdGet(iid) {
  if (!iid) fail('用法: tencent_issue.mjs get <iid>');
  const encoded = getProjectEncoded();
  process.stdout.write(await apiRequest(`/projects/${encoded}/issues?iid=${iid}&per_page=1`));
}

async function cmdCreate(title, description = '', labels = '', assigneeId = '') {
  if (!title) fail('用法: tencent_issue.mjs create <title> [description] [labels] [assignee_id]');

  const encoded = getProjectEncoded();
  const body = { title };

  if (description) body.description = description;
  if (labels) body.labels = labels;
  if (assigneeId) body.assignee_id = parseInt(assigneeId, 10);

  const result = await apiRequest(`/projects/${encoded}/issues`, {
    method: 'POST',
    json: body,
  });
  process.stdout.write(result);
}

async function cmdUpdate(iid, title = '', labels = '', assigneeId = '') {
  if (!iid) fail('用法: tencent_issue.mjs update <iid> [title] [labels] [assignee_id]');

  const encoded = getProjectEncoded();
  const body = {};

  if (title) body.title = title;
  if (labels) body.labels = labels;
  if (assigneeId) body.assignee_id = parseInt(assigneeId, 10);

  // 先查找 issue 的内部 ID
  const issuesJson = await apiRequest(`/projects/${encoded}/issues?iid=${iid}&per_page=1`);
  const issues = JSON.parse(issuesJson);
  if (!issues.length) fail(`错误：Issue #${iid} 不存在。`);
  const issueId = issues[0].id;

  const result = await apiRequest(`/projects/${encoded}/issues/${issueId}`, {
    method: 'PUT',
    json: body,
  });
  process.stdout.write(result);
}

async function cmdClose(iid) {
  if (!iid) fail('用法: tencent_issue.mjs close <iid>');

  const encoded = getProjectEncoded();

  // 先查找 issue 的内部 ID
  const issuesJson = await apiRequest(`/projects/${encoded}/issues?iid=${iid}&per_page=1`);
  const issues = JSON.parse(issuesJson);
  if (!issues.length) fail(`错误：Issue #${iid} 不存在。`);
  const issueId = issues[0].id;

  const result = await apiRequest(`/projects/${encoded}/issues/${issueId}`, {
    method: 'PUT',
    json: { state_event: 'close' },
  });
  process.stdout.write(result);
}

async function cmdReopen(iid) {
  if (!iid) fail('用法: tencent_issue.mjs reopen <iid>');

  const encoded = getProjectEncoded();

  const issuesJson = await apiRequest(`/projects/${encoded}/issues?iid=${iid}&per_page=1`);
  const issues = JSON.parse(issuesJson);
  if (!issues.length) fail(`错误：Issue #${iid} 不存在。`);
  const issueId = issues[0].id;

  const result = await apiRequest(`/projects/${encoded}/issues/${issueId}`, {
    method: 'PUT',
    json: { state_event: 'reopen' },
  });
  process.stdout.write(result);
}

async function cmdComment(iid, bodyArg = '') {
  if (!iid) fail('用法: tencent_issue.mjs comment <iid> [body]\n评论内容也可通过 stdin 传入。');

  const body = bodyArg || readStdin();
  if (!body) fail('错误：评论内容不能为空。请通过参数或 stdin 传入。');

  const encoded = getProjectEncoded();

  // 先查找 issue 的内部 ID
  const issuesJson = await apiRequest(`/projects/${encoded}/issues?iid=${iid}&per_page=1`);
  const issues = JSON.parse(issuesJson);
  if (!issues.length) fail(`错误：Issue #${iid} 不存在。`);
  const issueId = issues[0].id;

  const result = await apiRequest(`/projects/${encoded}/issues/${issueId}/notes`, {
    method: 'POST',
    json: { body },
  });
  process.stdout.write(result);
}

// ---------- 命令分发 ----------

async function main() {
  loadEnvFromSettings();
  const [command, ...args] = process.argv.slice(2);

  switch (command) {
    case 'members':
      await cmdMembers();
      break;
    case 'list':
      await cmdList(args[0] || 'opened', args[1] || '');
      break;
    case 'get':
      await cmdGet(args[0]);
      break;
    case 'create':
      await cmdCreate(args[0], args[1] || '', args[2] || '', args[3] || '');
      break;
    case 'update':
      await cmdUpdate(args[0], args[1] || '', args[2] || '', args[3] || '');
      break;
    case 'close':
      await cmdClose(args[0]);
      break;
    case 'reopen':
      await cmdReopen(args[0]);
      break;
    case 'comment':
      await cmdComment(args[0], args.slice(1).join(' '));
      break;
    default:
      console.log('腾讯工蜂 Issue 管理脚本（跨平台）');
      console.log('');
      console.log('用法:');
      console.log('  node tencent_issue.mjs members                                列出项目成员');
      console.log('  node tencent_issue.mjs list [state] [labels]                  列出 Issue');
      console.log('  node tencent_issue.mjs get <iid>                              查看 Issue');
      console.log('  node tencent_issue.mjs create <title> [desc] [labels] [aid]   创建 Issue');
      console.log('  node tencent_issue.mjs update <iid> [title] [labels] [aid]    更新 Issue');
      console.log('  node tencent_issue.mjs close <iid>                            关闭 Issue');
      console.log('  node tencent_issue.mjs reopen <iid>                           重开 Issue');
      console.log('  node tencent_issue.mjs comment <iid> [body]                   评论 Issue');
      console.log('  echo "body" | node tencent_issue.mjs comment <iid>            通过 stdin 评论');
      console.log('');
      console.log('Token 配置：在 .claude/settings.local.json 中设置');
      console.log('  "env": { "TENCENT_GIT_TOKEN": "your-token" }');
      process.exitCode = 1;
  }
}

main().catch((err) => {
  if (err instanceof CliError) {
    console.error(err.message);
  } else {
    console.error(`执行失败：${err?.message || String(err)}`);
  }
  process.exitCode = 1;
});
