# 场景包结构规范（Agent 阅读版）

> 本文档是场景包格式的**运行时速查**，Agent 经 `read_file` 整篇阅读（随包资源
> `assets/` 为自动授权只读域）。
> 格式的最终裁决是 `validate_package` 校验门禁：本文降低试错成本，门禁保证不出坏包。
> 每节末尾的「权威样例」指内置真实包，用 `read_reference(ref, path)` 查看（path 原样
> 复制 `search_reference` 返回清单中的文件名）。

## 1. 目录结构总览

一个场景包 = 一个目录，根目录放 `agent_eval.yaml` 清单：

```
<id>-package/ 或 <id>/
├── agent_eval.yaml          # 必需：包清单
├── rules/                   # 必需：规则集（至少 1 个 .yaml）
├── prompts/                 # 必需：判官提示词（至少 1 个 .yaml）
├── datasets/                # 必需：数据资产目录（可为占位 README，在线评测可空）
├── task_sets/               # 在线被测系统需要：考卷
├── sut_configs/             # 在线被测系统需要：接入配置（不含凭证）
└── metrics/                 # 可选：聚合策略 policy.yaml
```

硬性约定（门禁强制）：
- `rules/` 与 `prompts/` 中的资产必须是 **.yaml**（写成 .md 会被下游加载器静默忽略）；
- 三个必需目录不可缺失或为空；
- `sut_configs/` 内严禁凭证明文——只允许 `credential_ref` 引用（见第 7 节）。

权威样例：`read_reference("chat", "agent_eval.yaml")`（最小完整包）。

## 2. 包清单 agent_eval.yaml

清单只有一个顶层键 `package:`。必填 `id` 与 `scenario`，`version` 缺省 1.0.0（语义化版本）。

| 字段 | 必填 | 说明 |
|---|---|---|
| id | ✅ | 包唯一标识，小写英文与连字符（如 `chat`、`code-security`） |
| scenario | ✅ | 所属场景 ID（命名空间），如 `chat`、`courseware` |
| version |  | 语义化版本，新建从 `0.1.0` 起 |
| name / description / author |  | 展示名 / 描述 / 作者 |
| labels |  | 标签列表（如 `[production, latest]`） |
| entry_points |  | 场景定制评估器注册入口（`模块路径:函数`）——自定义 evaluator 才需要 |
| artifact_types |  | 制品类型声明（如 `chat/*`） |
| default_rule_set / default_task_set |  | 缺省规则集 / 考卷（执行未显式指定时采用；task_set 值 = task_sets/ 文件名 stem） |

最小示例：

```yaml
package:
  id: code-security
  scenario: code-security
  version: 0.1.0
  name: 代码安全评测包
  default_task_set: default
```

权威样例：`read_reference("chat", "agent_eval.yaml")`（含 entry_points 与 artifact_types 用法）。

## 3. rules/ 规则集

规则集文件（`rules/<名>.yaml`）定义评估维度、级联阶段与规则清单。顶层字段：
`version`、`scenario`、`description`、`dimensions[]`、`cascade[]`、`rules[]`。

- `dimensions[]`：`{id, name, weight}` ——评估维度；
- `cascade[]`：`{stage, name, stop_on_fail}` ——执行阶段级联；`rules[].stage` 必须引用
  这里声明的 stage id；`stop_on_fail: true` 的阶段是门控（失败即止）；
- `rules[]` 公共字段：`id`、`name`、`dimension`（引用 dimensions id）、`stage`、
  `description`、`weight`、`method`、`evaluator`。

按 `method` 区分的差异字段：
- `method: format`（格式门控）：`format_type: extension` + `extensions: ["md"]`；
- `method: llm`（LLM Judge）：`prompt_id` 引用 `prompts/` 的 `template_id`；
- `method: rule_set`（程序化评估器）：仅 `evaluator`（内置或包 entry_points 注册的 ID，
  不确定的 ID 先 `search_reference` 参照内置包，不要臆造）。

最小示例：

```yaml
version: "1.0"
scenario: code-security
description: 安全门控 + 质量 LLM 评估
dimensions:
  - {id: functional, name: 功能性, weight: 1.0}
cascade:
  - {stage: format, name: 格式门控, stop_on_fail: true}
  - {stage: quality, name: 质量评估, stop_on_fail: false}
rules:
  - {id: FMT_001, name: 产出文件存在, dimension: functional, stage: format,
     method: format, format_type: extension, extensions: ["md"], weight: 1.0}
  - {id: QUAL_001, name: 回答质量, dimension: functional, stage: quality,
     method: llm, prompt_id: sec_quality, evaluator: llm_judge, weight: 1.0}
```

权威样例：`read_reference("chat", "rules/chat-quality.yaml")`（三阶段 + 门控 + 三种 method 并用）。

## 4. prompts/ 判官提示词

LLM 评估的判官提示词（`prompts/<名>.yaml`）。顶层字段：`template_id`（rules 里
`prompt_id` 引用它）、`scenario`、`name`、`dimensions[]`、`system_prompt`、
`user_prompt_template`。

- `dimensions[]`：`{dim_id, name, description, weight, score_range: [min, max]}` ——
  判官按维度打分；
- `system_prompt`：判官角色 + 评分方法 + 各维度分档标准（要求证据可溯源、就低不就高）；
- `user_prompt_template`：用户侧模板（Jinja2 风格变量注入任务与产出内容）。

权威样例：`read_reference("chat", "prompts/chat_answer_quality.yaml")`
（三维打分 + 分档标准的成熟写法）。

## 5. task_sets/ 考卷

在线被测系统需要考卷（`task_sets/<名>.yaml`）。顶层字段：`id`、`name`、`description`、
`tasks[]`（Schema 必填 id/name/tasks，详见 `assets/schemas/task_set_schema.json`）。

- `tasks[].id`：任务唯一标识；`tasks[].input`：发给被测系统的输入（如
  `{instruction: "…"}`）；`tasks[].expected`：预期（`reference` 参考答案、`must_mention`
  必含要点等，供评估器使用）；`tasks[].constraints`：约束（如 `max_turns`）。

最小示例：

```yaml
id: sec_smoke_001
name: 代码安全冒烟
description: 单任务冒烟考卷
tasks:
  - id: injection_001
    input:
      instruction: "写一个检查 SQL 注入风险的函数"
    expected:
      must_mention: [参数化查询]
```

权威样例：`read_reference("chat", "task_sets/default.yaml")`（input/expected/constraints 全形态）。

## 6. datasets/ 数据资产

统一数据目录：`role: test`（测试集，benchmark 裸模型场景）或 `role: reference`
（参考知识，供检索增强评估）。在线被测系统评测通常不放数据集——放一个 `README.md`
占位即可（目录不可缺失）。字段结构见 `assets/schemas/dataset_schema.json`；
真实样例 `read_reference("courseware", "datasets/<清单中的文件>")`（先 search_reference）。

## 7. sut_configs/ 被测系统接入

每个被测系统一个文件（`sut_configs/<系统名>.yaml`）。**安全红线：凭证只允许
`credential_ref` 引用，任何 password/token/api_key 的值字段写明文都会被拒绝写入**
（明文由用户经 `agent-eval secrets set <ref>.<field>` 录入）。

agent-protocol 通道最小示例：

```yaml
sut:
  name: my-agent
  channel: agent_protocol
  base_url: ${MY_AGENT_URL:-https://agent.example.com}   # env 缺省展开
  protocol_flavor: commands    # runs | commands（按 probe_protocol 实测结论写）
  exec_mode: wait
  timeout: 300
  auth:
    type: api_login
    credential_ref: MY_AGENT   # 凭证引用键（非凭证本身）
    login:
      method: POST
      path: ${MY_LOGIN_URL:-https://login.example.com/users/login}  # 登录域可与 API 域分离
      body_template: '{"username": "{{ username }}", "password": "{{ password }}"}'
    extract:
      token_path: token        # 从登录响应提取 token 的 JSON path
      token_type: Bearer
```

关键约束：
- `base_url` 与 `protocol_flavor` 必须来自本会话 `probe_protocol` 的实测结论
  （落盘门禁强制：未实测主机、或核心端点非 ✅ 的 agent_protocol 配置会被打回）；
  接口域与页面域常分离，base_url 不得默认填入口页面域；
- `auth.login` 段原样使用 `probe_login` 成功时返回的 `sut_config_auth_snippet`
  （落盘门禁会与实测证据逐字段对账）：`path` 写**完整 URL**（登录域可与 API 域
  分离）——没有 `login.base_url` 字段，拆成相对路径会被拼回页面域；
- `body_template` 是 Jinja2：变量写 `{{ username }}`（`$var`、`%s` 等风格不会被渲染），
  常量字段直接写字面值；
- `auth.type`：`none | static_token | api_login | session_cookie`；凭证字段名 =
  body_template 的 Jinja2 变量（static_token 固定 `token`）；
- 只写执行器认识的字段（未知字段会被拒绝而非静默忽略）。

权威样例：`read_reference("chat", "sut_configs/sasan-agent.yaml")`（commands 形态全字段）。

## 8. metrics/policy.yaml 聚合策略

可选（缺省时按规则集 stage 结构聚合）。两个字段组：

- `aggregation_policy`：`id`、`scenario_id`、`stage_weights[]`
  （`{stage_id, weight, is_gate}`，可加 `evaluator_weights` 细化到评估器级）、
  `normalize_to: [0.0, 1.0]`；
- `metric_definitions[]`：`{id, name, summary, expression}`（如
  `expression: "count(format_gate) / total"`）。

权威样例：`read_reference("chat", "metrics/policy.yaml")`。
