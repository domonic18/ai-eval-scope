#!/usr/bin/env node
// 腾讯云 CLS 日志查询脚本（SearchLog）
//
// 通过 TC3-HMAC-SHA256 签名调用 CLS 检索分析日志接口。
// 凭证从环境变量读取（由 .claude/settings.local.json 的 env 注入）：
//   TENCENT_SECRET_ID     必填，腾讯云 SecretId
//   TENCENT_SECRET_KEY    必填，腾讯云 SecretKey
//   TENCENT_SCF_REGION    可选，区域，默认 ap-beijing
//   CLS_DEFAULT_TOPIC_ID  可选，默认日志主题 ID
//
// 算法参考已生产验证的 backend/app/integrations/tencent/invoke_client.py。

import crypto from 'node:crypto';

const HOST = 'cls.tencentcloudapi.com';
const SERVICE = 'cls';
const VERSION = '2020-10-16';
const ACTION = 'SearchLog'; // 注意：单数（SearchLogs 会报 InvalidAction）

// ---------------------------- 凭证 ----------------------------

function resolveCredentials() {
  const secretId = process.env.TENCENT_SECRET_ID;
  const secretKey = process.env.TENCENT_SECRET_KEY;
  if (!secretId || !secretKey) {
    console.error(
      '错误：未配置腾讯云凭证 TENCENT_SECRET_ID / TENCENT_SECRET_KEY。\n\n' +
        '请在 .claude/settings.local.json 的 env 中添加：\n' +
        '  "env": {\n' +
        '    "TENCENT_SECRET_ID": "your-id",\n' +
        '    "TENCENT_SECRET_KEY": "your-key",\n' +
        '    "CLS_DEFAULT_TOPIC_ID": "可选默认主题",\n' +
        '    "TENCENT_SCF_REGION": "ap-beijing"\n' +
        '  }'
    );
    process.exit(1);
  }
  return { secretId, secretKey };
}

// ---------------------------- TC3 签名 ----------------------------

const sha256hex = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
const hmacBuf = (key, data) => crypto.createHmac('sha256', key).update(data, 'utf8').digest();

function signHeaders({ payload, secretId, secretKey, region }) {
  const ts = Math.floor(Date.now() / 1000);
  const dateUTC = new Date(ts * 1000).toISOString().slice(0, 10); // YYYY-MM-DD(UTC)
  const hashedPayload = sha256hex(payload);
  const canonicalHeaders = `content-type:application/json\nhost:${HOST}\nx-tc-action:${ACTION.toLowerCase()}\n`;
  const signedHeaders = 'content-type;host;x-tc-action';
  const canonicalRequest = `POST\n/\n\n${canonicalHeaders}\n${signedHeaders}\n${hashedPayload}`;
  const scope = `${dateUTC}/${SERVICE}/tc3_request`;
  const stringToSign = `TC3-HMAC-SHA256\n${ts}\n${scope}\n${sha256hex(canonicalRequest)}`;
  const secretDate = hmacBuf(Buffer.from('TC3' + secretKey, 'utf8'), dateUTC);
  const secretService = hmacBuf(secretDate, SERVICE);
  const secretSigning = hmacBuf(secretService, 'tc3_request');
  const signature = crypto
    .createHmac('sha256', secretSigning)
    .update(stringToSign, 'utf8')
    .digest('hex');
  const authorization = `TC3-HMAC-SHA256 Credential=${secretId}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  return {
    'Content-Type': 'application/json',
    Host: HOST,
    'X-TC-Action': ACTION,
    'X-TC-Version': VERSION,
    'X-TC-Timestamp': String(ts),
    'X-TC-Region': region,
    Authorization: authorization,
  };
}

// ---------------------------- 时间解析 ----------------------------
// 支持 ISO8601（2026-07-08T03:00:00+08:00）或相对（-15m / -1h / -2h30m / -1d），或 "now"。

function parseTime(raw, defaultMs) {
  if (!raw || raw === 'now') return defaultMs;
  const rel = raw.match(/^-([\d.]+)(ms|s|m|h|d)$/);
  if (rel) {
    const n = Number(rel[1]);
    const unit = { ms: 1, s: 1000, m: 60000, h: 3600000, d: 86400000 }[rel[2]];
    return Date.now() - n * unit;
  }
  const ms = Date.parse(raw);
  if (Number.isNaN(ms)) {
    console.error(`错误：无法解析时间 "${raw}"。支持 ISO8601 或相对（-15m / -1h / -1d）。`);
    process.exit(1);
  }
  return ms;
}

// ---------------------------- 参数解析 ----------------------------

function parseArgs(argv) {
  const args = { raw: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      const v = argv[++i];
      if (v === undefined) {
        console.error(`错误：${a} 缺少值`);
        process.exit(1);
      }
      return v;
    };
    switch (a) {
      case '--topic': args.topic = next(); break;
      case '--query': args.query = next(); break;
      case '--from': args.from = next(); break;
      case '--to': args.to = next(); break;
      case '--limit': args.limit = Number.parseInt(next(), 10); break;
      case '--sort': args.sort = next(); break;
      case '--region': args.region = next(); break;
      case '--raw': args.raw = true; break;
      case '--help':
      case '-h': args.help = true; break;
      default:
        console.error(`错误：未知参数 ${a}（用 --help 查看用法）`);
        process.exit(1);
    }
  }
  return args;
}

function printHelp() {
  console.log(`腾讯云 CLS 日志查询（SearchLog）

用法:
  cls_query.mjs --topic <id> --query <检索语句> --from <开始> --to <结束> [选项]

参数:
  --topic   日志主题 ID（或配置 CLS_DEFAULT_TOPIC_ID）
  --query   CLS 检索语句，默认 *；含 | 触发 SQL 聚合模式
  --from    开始时间：ISO8601 或相对（-15m / -1h / -1d），默认 -15m
  --to      结束时间：ISO8601 或 now，默认 now
  --limit   返回条数，默认 100
  --sort    asc | desc，默认 desc
  --region  区域，默认 $TENCENT_SCF_REGION 或 ap-beijing
  --raw     输出原始 JSON（默认紧凑可读）

示例:
  cls_query.mjs --topic f5cb... --query 'timed out' --from -24h --to now
  cls_query.mjs --from -1h --query "* | select count_if(SCF_Message like '%GET /mcp%') gets"
`);
}

// ---------------------------- 输出 ----------------------------

function fmtTimeBeijing(ms) {
  const d = new Date(ms + 8 * 3600000); // 北京时间 UTC+8
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

function raiseApiError(data) {
  const err = data.Error;
  if (err) {
    console.error(`API 错误 [${err.Code}]: ${err.Message}`);
    process.exit(1);
  }
}

function printLogs(resp) {
  const data = resp.Response || resp;
  raiseApiError(data);
  const results = data.Results || [];
  console.log(
    `hits=${results.length} ListOver=${data.ListOver} Context=${(data.Context || '').slice(0, 40)}`
  );
  for (const item of results) {
    let obj;
    try {
      obj = typeof item.LogJson === 'string' ? JSON.parse(item.LogJson) : item.LogJson;
    } catch {
      obj = null;
    }
    const ts = fmtTimeBeijing(item.Time || 0);
    const truncate = (s, n = 500) =>
      s.length > n ? `${s.slice(0, n)} ...(${s.length} chars, 已截断)` : s;
    if (obj && typeof obj === 'object') {
      const fn = String(obj.SCF_FunctionName || '').slice(0, 24);
      const rid = String(obj.SCF_RequestId || '').slice(0, 13);
      const dur = String(obj.SCF_Duration ?? '');
      const type = String(obj.SCF_Type || '').slice(0, 4);
      const msg = truncate(String(obj.SCF_Message || ''));
      console.log(
        `[${ts}] ${fn.padEnd(24)} rid=${rid.padEnd(13)} dur=${dur.padStart(8)} ${type.padEnd(4)} | ${msg}`
      );
    } else {
      const raw = typeof item.LogJson === 'string' ? item.LogJson : JSON.stringify(item.LogJson);
      console.log(`[${ts}] ${truncate(raw)}`);
    }
  }
}

function printSql(resp) {
  const data = resp.Response || resp;
  raiseApiError(data);
  const cols =
    (data.Columns && data.Columns.map((c) => c.Name)) || data.ColNames || [];
  const recs = data.AnalysisRecords || data.AnalysisResults || [];
  console.log(`[SQL] columns=${JSON.stringify(cols)} rows=${recs.length}`);
  for (const r of recs) {
    console.log('  ', typeof r === 'string' ? r : JSON.stringify(r));
  }
}

// ---------------------------- 主流程 ----------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const { secretId, secretKey } = resolveCredentials();
  const region = args.region || process.env.TENCENT_SCF_REGION || 'ap-beijing';
  const topic = args.topic || process.env.CLS_DEFAULT_TOPIC_ID;
  if (!topic) {
    console.error('错误：未指定 --topic，且未配置 CLS_DEFAULT_TOPIC_ID。');
    process.exit(1);
  }

  const fromMs = parseTime(args.from, Date.now() - 15 * 60000);
  const toMs = parseTime(args.to, Date.now());
  if (fromMs >= toMs) {
    console.error('错误：--from 必须早于 --to。');
    process.exit(1);
  }

  const query = args.query || '*';
  const isSql = query.includes('|');
  const body = {
    TopicId: topic,
    From: fromMs,
    To: toMs,
    Query: query,
    Limit: args.limit ?? 100,
    Sort: args.sort || 'desc',
  };
  if (isSql) {
    body.UseNewAnalysis = true;
    body.SyntaxRule = 1; // CQL 语法
  }

  const payload = JSON.stringify(body);
  const headers = signHeaders({ payload, secretId, secretKey, region });

  let resp;
  try {
    const r = await fetch(`https://${HOST}`, { method: 'POST', headers, body: payload });
    resp = await r.json();
  } catch (e) {
    console.error(`请求失败：${e.message}`);
    process.exit(1);
  }

  if (args.raw) {
    console.log(JSON.stringify(resp, null, 2));
    return;
  }
  if (isSql) printSql(resp);
  else printLogs(resp);
}

main();
