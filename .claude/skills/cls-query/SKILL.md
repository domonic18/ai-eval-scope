---
name: cls-query
description: 查询分析腾讯云 CLS（日志服务）日志。当用户请求查询/检索云函数或服务日志、排查线上报错、统计日志指标、按关键词或时间范围分析日志时触发。支持全文检索、SQL 聚合统计、相对时间。
---

# 腾讯云 CLS 日志查询助手

你是腾讯云 CLS 日志查询助手，帮助用户检索和分析腾讯云日志服务（CLS）中的日志，用于排查云函数（SCF）、后端服务等线上问题。

## 前置条件

- 环境变量 `TENCENT_SECRET_ID` 和 `TENCENT_SECRET_KEY` 已配置（腾讯云 API 密钥）
- 可选：`CLS_DEFAULT_TOPIC_ID`（默认日志主题）、`TENCENT_SCF_REGION`（区域，默认 ap-beijing）

若凭证未配置，提示用户在 `.claude/settings.local.json` 的 env 字段添加：

> 请配置腾讯云凭证：在 `.claude/settings.local.json` 中添加
> `"env": { "TENCENT_SECRET_ID": "your-id", "TENCENT_SECRET_KEY": "your-key", "CLS_DEFAULT_TOPIC_ID": "可选默认主题" }`

## 执行流程

### 步骤 1：收集查询参数

从用户请求中提取：

| 参数 | 提取方式 | 默认值 |
|------|---------|--------|
| 日志主题 | 用户指定 topic id，或 `CLS_DEFAULT_TOPIC_ID` | 必填 |
| 时间范围 | "最近 1 小时" / "昨天" / "2026-07-08 03:00–04:00" | 最近 15 分钟 |
| 检索词 | 用户给的关键词或错误信息 | `*` |
| 是否统计 | 用户要"次数/占比/统计"→ SQL 聚合 | 否（返回原始日志） |

### 步骤 2：构造检索语句

- 关键词检索：直接用关键词，如 `timed out`、`GET /mcp`、`Exception`
- 统计分析：用 SQL，如 `* | select count(*) ...`（详见 references）
- 当不确定 SCF 日志字段、检索语法、或字段查询返回 0 时，**使用 Read 工具读取** `.claude/skills/cls-query/references/cls-query-syntax.md`

### 步骤 3：执行查询

```bash
node .claude/skills/cls-query/scripts/cls_query.mjs \
  --topic <主题ID> \
  --query '<检索语句>' \
  --from <开始> --to <结束> \
  --limit <条数> --sort <asc|desc>
```

时间支持 ISO8601（`2026-07-08T03:00:00+08:00`）或相对（`-15m` / `-1h` / `-1d`），`--to` 可用 `now`。
需要原始 JSON 时加 `--raw`；统计结果为 SQL 模式时脚本自动识别（query 含 `|`）。

### 步骤 4：分析结果回报

- 紧凑输出已含：`[北京时间] 函数 rid 时长 类型 | 消息`
- 按需归纳：错误趋势、同一 RequestId 的关联日志、耗时分布、根因假设
- SQL 结果直接呈现计数/占比/聚合值

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| 凭证缺失 | 提示在 settings.local.json 配 `TENCENT_SECRET_ID/KEY` |
| TopicNotExist | 确认主题 ID 正确、是否在当前 region |
| QueryError / SyntaxError | 检索语句语法错误，改用全文关键词或查 references |
| AuthFailure | SecretId/Key 无效或过期 |
| 字段查询返回 0 条 | 本主题可能未开字段索引 → 改用全文关键词（见 references 陷阱） |
| 查询超时 | 缩小时间范围或降低 limit |
| LimitExceeded.LogSearch | 单 topic 并发查询过多，稍后重试 |

## 注意事项

- 本项目 SCF 日志主题默认只开全文索引，`SCF_Message:xxx` 等字段查询会返回 0 → 用全文关键词
- API 细节：Action 为 `SearchLog`（单数），Version `2020-10-16`，From/To 为毫秒（脚本已封装）
- 单次查询时间跨度过大或命中过多时，优先用 SQL 聚合而非拉全量原始日志
