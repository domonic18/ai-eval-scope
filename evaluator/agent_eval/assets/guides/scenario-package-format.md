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
├── datasets/                # 离线文件评测必需：数据资产；在线 SUT 形态不需要
├── task_sets/               # 在线被测系统需要：考卷
├── sut_configs/             # 在线被测系统需要：接入配置（不含凭证）
└── metrics/                 # 必选：聚合策略 policy.yaml（缺失构建期打回）
```

硬性约定（门禁强制）：
- `rules/` 与 `prompts/` 中的资产必须是 **.yaml**（写成 .md 会被下游加载器静默忽略）；
- `rules/`、`prompts/` 不可缺失或为空；`datasets/` 仅离线文件形态必需（清单未声明
  `default_task_set`）——在线 SUT 形态考卷来自 `task_sets/`，勿建占位 datasets；
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
- `rules[]` 公共字段：`id`、`name`、`dimension`（引用 dimensions id）、`stage`（引用
  cascade 的 stage id）、`description`、`weight`、`method`、`evaluator`。
- `tier`（可选）：`hard_gate / hard_score / soft / preference` ——约束层级覆盖，缺省用
  评估器内置层级。LLM judge 评估器（如 `chat.answer_quality`）内置 `soft`：判分只进
  reward、不翻转样本 status；声明 `tier: hard_score` 后判分低于阈值（0.4）即 FAIL 并
  翻转样本 status。**安全类规则必须显式声明**——soft 语义下 judge 全 0 分样本仍
  pass（run 20260910_034232 教训：violence_003 假成功）。
- `evaluator`：**评估器注册 ID**——不是 method。`llm_judge` 是 method 枚举值，写进
  `evaluator` 字段运行时必报「未注册的评估器」（落盘校验也会打回）。内置 ID 全集：
  `format.response_format` / `format.html_validity` / `format.content_completeness` /
  `soft.teaching_logic` / `soft.content_diversity` / `pref.style_preference` /
  `pref.depth_preference` / `pref.request_fulfillment` / `commonsense.info_accuracy` /
  `commonsense.chronological_order` / `commonsense.logical_consistency` /
  `vision.quality`；`chat.*` 三项（对话型 SUT 的精确匹配 / 语义一致性 / 回答质量）
  需包清单声明 `entry_points.evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"`
  （照抄 chat 包清单行）。不确定的 ID 先 `read_reference("chat", "rules/chat-quality.yaml")`
  参照，不要臆造。

按 `method` 区分的差异字段：
- `method: format`（格式门控）：`format_type: extension` + `extensions: ["md"]`；
- `method: llm`（LLM Judge）：`prompt_id` 引用 `prompts/` 的 `template_id` + `evaluator`
  注册 ID（如 `chat.answer_quality`——判官提示词以本包 `prompt_id` 指向的为准）；
- `method: rule_set`（程序化评估器）：仅 `evaluator`。

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
     method: llm, prompt_id: sec_quality, evaluator: chat.answer_quality, weight: 1.0}
```

权威样例：`read_reference("chat", "rules/chat-quality.yaml")`（三阶段 + 门控 + 三种 method 并用）。

## 4. prompts/ 判官提示词

LLM 评估的判官提示词（`prompts/<名>.yaml`）。顶层字段：`template_id`（rules 里
`prompt_id` 引用它）、`scenario`、`name`、`dimensions[]`、`system_prompt`、
`user_prompt_template`、`num_samples`。

- `dimensions[]`：`{dim_id, name, description, weight, score_range: [min, max]}` ——
  判官按维度打分；
- `system_prompt`：判官角色 + 评分方法 + 各维度分档标准（要求证据可溯源、就低不就高）；
- `user_prompt_template`：用户侧模板（Jinja2 风格变量注入任务与产出内容）；
- `num_samples`：判官对每条规则**独立采样几次**（各维度取中位数为最终分，标准差超阈值
  标记低置信度）。缺省 3；设 1 则只调一次（省成本，chat/code 内置包即 1）——按评测
  严格度与成本预算权衡，用户有配置选择权。非法值（0/负数/非整数）落盘校验会打回。

**变量契约（勿自创变量名）**：`user_prompt_template` 只能使用评估器实际注入的变量——
变量按引用的 `evaluator` 而定，写错运行时必报「模板渲染失败，变量缺失」且该规则直接
0 分（落盘校验会提前对账打回）：

| evaluator | 可用变量 |
|-----------|---------|
| `chat.answer_quality` | `{{ instruction }}`（任务指令）、`{{ content }}`（被测产出全文）、`{{ must_mention }}`（必含要点，来自 expected） |
| `chat.answer_consistency` | `{{ instruction }}`、`{{ content }}`、`{{ reference }}`（参考答案，来自 expected） |
| `code.correctness` | `{{ content }}`（被测产出全文）、`{{ subject }}`（学科）、`{{ title }}`（任务标题） |
| `code.style` | `{{ content }}`、`{{ subject }}`、`{{ title }}` |
| `soft.teaching_logic` | `{{ content }}`、`{{ subject }}`（学科）、`{{ title }}` |
| `soft.content_diversity` | `{{ content }}`、`{{ subject }}`、`{{ title }}`、`{{ has_formula }}`/`{{ has_table }}`/`{{ has_image }}`/`{{ has_list }}`（是/否媒体特征） |
| `pref.style_preference` | `{{ content }}`、`{{ subject }}`、`{{ title }}` |
| `pref.depth_preference` | `{{ content }}`、`{{ subject }}`、`{{ title }}` |
| `pref.request_fulfillment` | `{{ content }}`、`{{ subject }}`、`{{ title }}`、`{{ original_request }}`（用户原始需求）、`{{ expected_output }}`（预期输出描述） |
| `commonsense.chronological_order` | `{{ content }}`、`{{ subject }}`、`{{ title }}` |
| `vision.quality` | `{{ title }}`、`{{ num_documents }}`（视觉路径逐文档截图评估，模板不需要正文变量） |

被测产出全文的变量名是 **`content`**（不是 `response`/`output`/`answer`——常见臆造）；
用户原始需求的变量名是 **`original_request`**（不是 `instruction`——那是 chat 场景评估器的
变量，2026-09-10 courseware-reasonableness 包实测事故：courseware 规则模板写
`{{ instruction }}` 运行时四样本全灭）。
其他评估器的变量集以该评估器实现为准：写 rules 前先 `list_evaluators()` 确认可用 ID，
再看权威样例里对应模板的真实写法。

权威样例：`read_reference("chat", "prompts/chat_answer_quality.yaml")`
（三维打分 + 分档标准的成熟写法）。

## 5. task_sets/ 考卷

在线被测系统需要考卷（`task_sets/<名>.yaml`）。顶层字段：`id`、`name`、`description`、
`tasks[]`（Schema 必填 id/name/tasks，详见 `assets/schemas/task_set_schema.json`）。

- `tasks[].id`：任务唯一标识；`tasks[].input`：发给被测系统的输入（如
  `{instruction: "…"}`）；`tasks[].expected`：预期（`reference` 参考答案、`must_mention`
  必含要点等，供评估器使用）。
- 交互预算（轮次/催促/轮询/下载/墙钟）不在任务里逐条声明——任务集级
  `interaction_policy` 统一声明（`sut_calls_total` / `dispatch` / `nudges` /
  `state_polls` / `downloads` / `nudge_backoff_s` / `wall_clock_deadline_s`），由
  执行器机械闸门执行，提示词不出现数字条款。个别慢任务在
  `tasks[].constraints.interaction_policy` 部分覆盖（如生成慢的课件任务放宽
  `state_polls`）。旧的 `constraints.max_turns` 已废弃，写了不生效。

最小示例：

```yaml
id: sec_smoke_001
name: 代码安全冒烟
description: 单任务冒烟考卷
interaction_policy:
  sut_calls_total: 8      # SUT 执行类调用总额
  nudges: 2               # 续跑/催促次数
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

generic_http 通道示例（面向未实现 agent-protocol 的 HTTP 服务；**须经用户确认
改走此通道**，且 request_template/response_mapping 须先用 request 工具实测同形
请求后再落盘）：

```yaml
sut:
  name: plain-api
  channel: generic_http
  base_url: ${MY_API_URL:-https://api.example.com}
  request_template:
    method: POST
    path: /v1/chat
    headers:
      X-Trace: "{{ metadata.task_id }}"   # 值支持 Jinja2（变量空间 input/metadata）
    body:
      query: "{{ input }}"                # dict 直发 JSON；str 须为合法 JSON 文本
  response_mapping:
    text: data.answer                     # 回答文本点分路径（未配置时整个响应体兜底）
    files: data.files                     # 产物文件列表（可选）
    success: data.ok                      # 成功标志（可选，falsy 判 failed）
  auth: …                                 # 与 agent-protocol 通道同构（见下）
```

**多步 API（steps 链）**：建会话→发消息→查历史这类多步接口，单步模板表达不了
（硬塞单步只会反复建会话，测试指令从未送达）。用 `steps` 逐步声明，后续步以
`{{ 步骤名.路径 }}` 引用前序步响应里的值（值全程服务端流动，不回流对话）；
`response_mapping` 作用于**末步**响应：

```yaml
sut:
  name: chained-api
  channel: generic_http
  base_url: ${MY_API_URL:-https://api.example.com}
  request_template:
    steps:
      - name: create                        # 步骤名即后续步的引用键
        method: POST
        path: /chat/conversations
        body: {student_id: null}
      - name: send
        method: POST
        path: /chat/conversations/{{ create.data.id }}/messages   # 引用前序步响应值
        body: {content: "{{ input }}", image_urls: []}            # 测试指令经 input 注入
      - name: history
        method: GET
        path: /chat/conversations/{{ create.data.id }}
  response_mapping:
    text: data.messages.-1.content        # 列表末元素：-1 与 [-1] 两种写法等价
```

steps 链约束：
- `steps` 与单步 `method`/`path` **二选一**（混用或都缺都会被校验打回）；步骤名须
  唯一且不得为 `input`/`metadata`（模板根变量保留字）；
- 全部模板叶子**必须引用 `{{ input }}`**（path/headers/body/until 任一处），否则落盘
  校验打回——测试指令不进模板就从未发送给被测系统；
- 变量空间仅 `input`、`metadata` 与**前序**步骤名（poll 步的 `until` 可自引用本步；
  拼错或前向引用都会在落盘前打回）；
- 末步不可为 `once`（`response_mapping` 作用于末步，会话续轮无响应可提取）；
- 链中任一步 ≥400 即整体 failed（错误带步骤名）；
- **`text` 已配置但路径未命中/取 null → failed**（错误带响应体摘录，据此修正路径），
  不再静默兜底整包——纯文本 API 请把 `response_mapping` 留空，整个响应体即回答；
- SSE 流式末步（`text/event-stream`）自动解析 `data:` 帧为 `events` 列表；未配置
  mapping 时整段原文即回答。

**会话续接（once 步）**：建会话类步骤标 `once: true`——响应跨
`sut_request` 调用缓存，多轮任务同一会话续问，不再每轮重建会话丢失上下文：

```yaml
    steps:
      - name: create
        method: POST
        path: /chat/conversations
        once: true                        # 仅会话首轮执行，续轮引用缓存值
        body: {student_id: null}
      - name: send
        method: POST
        path: /chat/conversations/{{ create.data.id }}/messages   # 写法不变
        body: {content: "{{ input }}"}
```

执行语义：会话键由执行框架按任务注入（多任务隔离自动保证）；once 步缓存命中
即跳过请求（仍计一次 SUT 调用——授权按尝试计）；非 once 步 404 且会话缓存非空
（服务端会话过期）自动清缓存整链重建一次，结果标注 `session_rebuilt: true`，
重建仍 404 才 failed（带两轮证据）。会话缓存随运行 `aclose` 全清，不跨运行存活。

**异步轮询（poll 步）**：提交 job → 轮询 status → 取结果的任务型
API 用 `poll` 声明轮询步——反复执行直到 `until` 渲染为真（true/1/yes）或超时：

```yaml
    steps:
      - name: submit
        method: POST
        path: /jobs
        body: {prompt: "{{ input }}"}
      - name: status
        method: GET
        path: /jobs/{{ submit.data.job_id }}
        poll:
          until: "{{ status.data.state == 'succeeded' }}"   # 本步响应自引用可见
          interval_s: 3
          timeout_s: 300    # 防呆上界 900；须小于任务级超时预算
      - name: fetch
        method: GET
        path: /jobs/{{ submit.data.job_id }}/result
```

执行语义：do-while（先发请求再判终态）；轮询中单次 ≥400 不立即失败（受理后
短暂不一致是常态），持续至终态或超时；超时整体 failed（`poll_timeout`，错误带
最后响应摘录与尝试次数）；`until` 引用未声明变量在落盘前打回，渲染错误
fail-loud。`once` 与 `poll` 互斥（落盘校验打回）。

**提取路径语法（response_mapping.text / token_path / output_paths 共用）**：
- 负下标取末元素：`data.messages.-1.content` 与 `data.messages[-1].content` 等价；
- **字段过滤段** `[字段=值]`：按字段过滤列表后再取下标——
  `events[type=content].-1.content`（SSE 答案帧位置不定，thought 帧数可变，裸下标
  脆弱）、`data.messages[role=assistant].-1.content`（历史接口末条常是用户自己的
  消息而非助手回复，裸 `messages[-1]` 提取到回显——run 20260910_034232 16/16
  回显事故）；
- **流式/多帧响应必须用过滤段**；过滤未命中直接 failed（fail-loud，不静默兜底）。
  提取路径落盘前须实测验证：先 `request` 工具实调，确认答案帧的 `type`/`role`
  字段真实形态再写映射。

关键约束：
- `channel` 可执行取值只有 `agent_protocol` 与 `generic_http`（`browser` 预留未
  排期，落盘门禁直接打回）；探测受挫时继续排查或呈报用户，**不得降级改写通道**；
- `base_url` 与 `protocol_flavor` 必须来自本会话 `probe_protocol` 的实测结论
  （落盘门禁强制：未实测主机、或核心端点非 ✅ 的 agent_protocol 配置会被打回）；
  接口域与页面域常分离，base_url 不得默认填入口页面域；
  （落盘门禁会与实测证据逐字段对账）：`path` 写**完整 URL**（登录域可与 API 域
  分离）——没有 `login.base_url` 字段，拆成相对路径会被拼回页面域；
- `body_template` 是 Jinja2：变量写 `{{ username }}`（`$var`、`%s` 等风格不会被渲染），
  常量字段直接写字面值；
- `auth.type`：`none | static_token | api_login | session_cookie`；凭证字段名 =
  body_template 的 Jinja2 变量（static_token 固定 `token`）；
- 只写执行器认识的字段（未知字段会被拒绝而非静默忽略）。

权威样例：`read_reference("chat", "sut_configs/sasan-agent.yaml")`（commands 形态全字段）。

## 8. metrics/policy.yaml 聚合策略

**必选**（`scenario new` 脚手架已含起始文件）。聚合策略不再回退 courseware 默认：
缺包或缺 `metrics/policy.yaml` → 构建期直接打回——降级会把规则集未声明阶段的
评估分数静默丢弃，正是 judge 打 0 分样本仍 reward=1.0 的根因（run 20260910_034232
事故）。校验双端同源：`scenario validate` / Agent 落盘门禁与运行时 `build_pipeline`
都会对账。

**规则集里每个 `stage`（cascade 声明 + 规则引用）都必须在 `stage_weights` 中声明**，
否则构建期直接打回（fail-loud）。

两个字段组：

- `aggregation_policy`：`id`、`scenario_id`、`stage_weights[]`、`normalize_to: [0.0, 1.0]`。
  `stage_weights[]` 每条 `{stage_id, weight, is_gate, skip_tiers_in_reward}`，另有
  两个可选键：`evaluator_weights` 细化到评估器级；`id` 把该阶段得分以该键暴露到
  样本级 metrics——`metric_definitions` 的 `mean(soft)`/`mean(pref)` 表达式按它取数，
  同一 `stage_id` 拆多个加权项时每条各带一个 `id`（内置 chat 包 `quality` 单拆、
  courseware 包 `quality→soft/pref` 双拆，均现成参照）。
  `skip_tiers_in_reward: []` 表示 hard_score 判定结果同样计分——
  judge 0 分必须拉低 reward，而非只在 status 上体现；
- `metric_definitions[]`：`{id, name, summary, expression}`（如
  `expression: "count(format_gate) / total"`）。

权威样例：`read_reference("chat", "metrics/policy.yaml")`。
