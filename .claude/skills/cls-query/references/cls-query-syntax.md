# CLS 检索语法与排查模式

> 本文档沉淀腾讯云 CLS 日志检索的语法、SCF 日志字段速查、常见排查模式与已知陷阱。

## 检索语法

CLS 检索语句（Query）由 `[检索条件] | [SQL]` 构成，管道后的 SQL 可选。

### 全文检索（本项目 SCF 主题主要用这个）

| 写法 | 含义 |
|------|------|
| `timed out` | 多词 AND（命中同时含 timed 和 out 的日志） |
| `"GET /mcp"` | 短语（连续精确匹配） |
| `error*` | 前缀通配 |
| `*` | 全部 |

### 字段检索（需主题开启键值索引）

- `SCF_FunctionName:mcp`、`SCF_Level:ERROR`、`SCF_Duration:900000`
- ⚠️ **本项目 SCF 主题默认只开全文索引**，字段查询 `SCF_Message:xxx` 会返回 0 → 改用全文关键词；要按函数过滤用 SQL `where SCF_FunctionName like '%mcp%'`

### SQL 聚合（管道后）

统计某时段 GET/POST/超时次数（本次排查用过）：

```sql
* | select
    count_if(SCF_Message like '%GET /mcp%')  gets,
    count_if(SCF_Message like '%POST /mcp%') posts,
    count_if(SCF_Message like '%timed out%') timeouts,
    count_if(SCF_Message like '%body copy%') bodycopy
```

按函数分组计数：

```sql
* | select SCF_FunctionName, count(*) as c
  group by SCF_FunctionName order by c desc
```

## SCF 日志字段速查

| 字段 | 含义 |
|------|------|
| `SCF_Message` | 日志正文。Platform 行：`START`/`END`/`Report ... Duration`；Custom 行：业务/uvicorn 输出 |
| `SCF_FunctionName` | 函数名（如 `sasan-squadsight-mcp`） |
| `SCF_RequestId` | 请求 ID，关联同一请求的多条日志 |
| `SCF_Duration` | 执行时长（毫秒），仅 Report 行有值 |
| `SCF_Type` | `Platform`（平台日志）/ `Custom`（业务日志） |
| `SCF_StatusCode` | 状态码 |
| `SCF_Level` | `INFO` / `ERROR` |
| `SCF_StartTime` | 请求开始时间（毫秒） |
| `SCF_LogTime` | 日志产生时间（纳秒） |

## 常见排查模式

1. **按错误关键词**：`--query 'timed out'` / `'ReverseProxy'` / `'Exception'` / `'Traceback'`
2. **按函数过滤**：全文 `mcp`（命中函数名含 mcp 的日志）；但 Platform 日志正文不含函数名，更可靠用 SQL `where SCF_FunctionName like '%mcp%'`
3. **SQL 统计对比**：统计 GET/POST/超时次数，判断客户端行为（如本次：4h 内 GET=92/POST=0/timed out=2）
4. **按 RequestId 追踪生命周期**：取一个 rid，看单请求的 START → 业务 → Report Duration 完整链路
5. **慢请求**：`--query 'Report'` 后看 `SCF_Duration`（或 SQL `max(cast(SCF_Duration as bigint))`）
6. **时间对齐**：平台日志时间戳为 UTC，与北京时间差 8h；脚本紧凑输出已转北京时间

## 已知陷阱（血泪经验）

- **字段索引 vs 全文索引**：本项目 SCF 主题只开全文索引，`SCF_Message:"GET /mcp"` / `SCF_FunctionName:mcp` 会返回 0 → 用全文关键词（`mcp` / `"GET /mcp"`）
- **Action 是 `SearchLog` 单数**（`SearchLogs` 会报 `InvalidAction`）
- **Version 是 `2020-10-16`**（不是 `2020-03-03`，后者会报 action not found）
- **From / To 是毫秒时间戳**（脚本已封装为 ISO/相对时间输入）
- **SQL 模式**：query 含 `|` 自动启用，此时 `Limit`/`Sort`/`Context` 对原始日志无效，结果走 `AnalysisRecords`
- **中文检索**：中文关键词（如 `工具调用`）可能不被全文索引覆盖，优先用英文关键词或 SQL `like`
