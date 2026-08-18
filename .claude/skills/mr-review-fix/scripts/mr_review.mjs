#!/usr/bin/env node
/**
 * 工蜂 MR 评论获取与分析脚本（跨平台）
 * 用法:
 *   node mr_review.mjs find-by-iid <iid>
 *   node mr_review.mjs find-by-branch [branch]
 *   node mr_review.mjs notes <mr_id>
 *   node mr_review.mjs get-note <mr_id> <note_id>
 *   echo "body" | node mr_review.mjs edit-note <mr_id> <note_id>
 *   node mr_review.mjs discussions <mr_id>
 *   echo "body" | node mr_review.mjs reply-note <mr_id> <note_id>
 *   echo "body" | node mr_review.mjs create-note <mr_id>
 */

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const API_BASE_URL = 'https://git.code.tencent.com/api/v3';

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

// ---------- 子命令 ----------

async function cmdFindByIid(iid) {
  if (!iid) fail('用法: mr_review.mjs find-by-iid <mr_iid>');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);
  process.stdout.write(await apiRequest(`/projects/${encoded}/merge_requests?iid=${iid}&per_page=1`));
}

async function cmdFindByBranch(branch) {
  if (!branch) {
    branch = runGit(['branch', '--show-current']);
    if (!branch) fail('错误：无法获取当前分支，请手动指定源分支。');
  }

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);
  process.stdout.write(await apiRequest(`/projects/${encoded}/merge_requests?source_branch=${branch}&state=opened&per_page=1`));
}

async function cmdNotes(mrId) {
  if (!mrId) fail('用法: mr_review.mjs notes <mr_id>');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);
  process.stdout.write(await apiRequest(`/projects/${encoded}/merge_requests/${mrId}/notes?per_page=100&sort=asc`));
}

async function cmdGetNote(mrId, noteId) {
  if (!mrId || !noteId) fail('用法: mr_review.mjs get-note <mr_id> <note_id>');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);
  process.stdout.write(await apiRequest(`/projects/${encoded}/merge_requests/${mrId}/notes/${noteId}`));
}

async function cmdEditNote(mrId, noteId) {
  if (!mrId || !noteId) {
    fail('用法: mr_review.mjs edit-note <mr_id> <note_id>\n评论内容通过 stdin 传入。');
  }

  const body = readStdin();
  if (!body) fail('错误：评论内容不能为空。请通过 stdin 传入评论内容。');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);

  const result = await apiRequest(
    `/projects/${encoded}/merge_requests/${mrId}/notes/${noteId}`,
    { method: 'PUT', json: { body } },
  );
  process.stdout.write(result);
}

async function cmdDiscussions(mrId) {
  if (!mrId) fail('用法: mr_review.mjs discussions <mr_id>');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);
  process.stdout.write(await apiRequest(`/projects/${encoded}/merge_requests/${mrId}/discussions?per_page=100`));
}

async function cmdReplyNote(mrId, noteId) {
  if (!mrId || !noteId) {
    fail('用法: mr_review.mjs reply-note <mr_id> <note_id>\n回复内容通过 stdin 传入。');
  }

  const body = readStdin();
  if (!body) fail('错误：回复内容不能为空。请通过 stdin 传入回复内容。');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);

  // 工蜂 MR Notes 无原生 threaded reply 接口，采用“引用原评论 + 新建评论”方式回复。
  let originalNote = null;
  try {
    const noteJson = await apiRequest(`/projects/${encoded}/merge_requests/${mrId}/notes/${noteId}`);
    originalNote = JSON.parse(noteJson);
  } catch {
    // note 可能已删除或无权限，降级为仅引用 note_id
  }

  let quotedBody;
  if (originalNote?.body) {
    const author = originalNote.author?.name || originalNote.author?.username || '';
    const originalLines = String(originalNote.body).split('\n');
    const quoted = originalLines.map(line => `> ${line}`).join('\n');
    quotedBody = `> **评论 #${noteId}**（@${author}）\n${quoted}\n\n${body}`;
  } else {
    quotedBody = `> **评论 #${noteId}**\n\n${body}`;
  }

  const result = await apiRequest(
    `/projects/${encoded}/merge_requests/${mrId}/notes`,
    { method: 'POST', json: { body: quotedBody } },
  );
  process.stdout.write(result);
}

async function cmdCreateNote(mrId) {
  if (!mrId) fail('用法: mr_review.mjs create-note <mr_id>\n评论内容通过 stdin 传入。');

  const body = readStdin();
  if (!body) fail('错误：评论内容不能为空。请通过 stdin 传入评论内容。');

  const projectPath = detectProjectPath();
  const encoded = encodeURIComponent(projectPath);

  const result = await apiRequest(
    `/projects/${encoded}/merge_requests/${mrId}/notes`,
    { method: 'POST', json: { body } },
  );
  process.stdout.write(result);
}

// ---------- 命令分发 ----------

async function main() {
  const [command, ...args] = process.argv.slice(2);

  switch (command) {
    case 'find-by-iid':
      await cmdFindByIid(args[0]);
      break;
    case 'find-by-branch':
      await cmdFindByBranch(args[0]);
      break;
    case 'notes':
      await cmdNotes(args[0]);
      break;
    case 'get-note':
      await cmdGetNote(args[0], args[1]);
      break;
    case 'edit-note':
      await cmdEditNote(args[0], args[1]);
      break;
    case 'discussions':
      await cmdDiscussions(args[0]);
      break;
    case 'reply-note':
      await cmdReplyNote(args[0], args[1]);
      break;
    case 'create-note':
      await cmdCreateNote(args[0]);
      break;
    default:
      console.log('工蜂 MR 评论获取与分析脚本（跨平台）');
      console.log('');
      console.log('用法:');
      console.log('  node mr_review.mjs find-by-iid <mr_iid>');
      console.log('  node mr_review.mjs find-by-branch [branch]');
      console.log('  node mr_review.mjs notes <mr_id>');
      console.log('  node mr_review.mjs get-note <mr_id> <note_id>');
      console.log('  echo "body" | node mr_review.mjs edit-note <mr_id> <note_id>');
      console.log('  node mr_review.mjs discussions <mr_id>');
      console.log('  echo "body" | node mr_review.mjs reply-note <mr_id> <note_id>');
      console.log('  echo "body" | node mr_review.mjs create-note <mr_id>');
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
