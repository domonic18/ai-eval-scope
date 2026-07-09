# 质量（Quality）LLM-as-judge 评分细化与可解释性方案

> 本文档设计评估器"质量（Quality）阶段"LLM-as-judge 的**评分标准细化**与**评分可解释性**机制：覆盖 5 个 soft/preference 评估器（教学逻辑、内容多样性、风格偏好、深度偏好、需求满足）的逐维度细化标准、结构化逐项扣分输出 schema、以及从评估器到前端的改动清单与渐进式落地。
>
> 属于 [04 评估引擎设计](./04评估引擎设计.md) 的细化。提示词与判官流水线现状见 [04](./04评估引擎设计.md) 与评估器 `agent_eval/llm/judge/`、`agent_eval/assets/prompts/`。

---

## 一、背景与目标

质量阶段用 LLM-as-judge 评 5 个 soft/preference 评估器：

| 评估器 id | 名称 | tier | 提示词 template_id |
|-----------|------|------|-------------------|
| `soft.teaching_logic` | 教学逻辑 | SOFT | `pedagogical_logic` |
| `soft.content_diversity` | 内容多样性 | SOFT | `content_diversity` |
| `pref.style_preference` | 风格偏好 | PREFERENCE | `style_preference` |
| `pref.depth_preference` | 深度偏好 | PREFERENCE | `depth_preference` |
| `pref.request_fulfillment` | 需求满足 | PREFERENCE | `request_fulfillment` |

### 1.1 现状问题

1. **评分标准过简**：每个提示词只有"3 个子维度 + 5 档定性锚点"（如"7-8 良好"无任何分档行为描述），模型打分粗、波动大、缺乏专业口径。
2. **可解释性不足**：`output_schema` 只让 LLM 返回 `{维度: number, summary}`，且 `orchestrator._coerce_score` 会把 `{score, issues}` **主动拍平成数字**（`evaluator/agent_eval/llm/judge/orchestrator.py:41-64`）；`details.dimensions[]` 只存 `{id,name,score,weight,confidence}`，**无逐维度扣分原因**。前端 `ConstraintItem` 只读 `details.errors`（`web/frontend/src/pages/SampleDetail.tsx:231-236`），而质量约束根本没有 `errors` 字段 → **"发现的问题"恒为空**，低分时用户不知道扣在哪，对评分缺乏信任。

### 1.2 设计目标

| 编号 | 目标 | 验收口径 |
|------|------|----------|
| G1 | 评分标准专业、细化 | 每个子维度给出分档行为标准 + 扣分触发 + 证据要求 |
| G2 | 评分可解释、可追溯 | 判官逐维度产出结构化扣分（issues + 亮点 + 一句话理由），前端逐项渲染，低分能看出扣在哪 |
| G3 | 向后兼容、可灰度 | 升级一个提示词不影响其余；旧提示词 details 形态不变 |

### 1.3 非目标

- 不改评分尺度（仍 0-10/维度 → 归一化 [0,1]）与权重（提示词内 0.4/0.3/0.3；评估器间 soft 0.5/0.5、pref 0.33/0.33/0.34）。
- 不改判官稳定性机制（3 样本中位数 + stddev 置信度，`stability.py` 不变）。
- 不改管道层 schema（ingest `details` 为任意 JSON + DB JSONB，已就绪）。

### 1.4 现状链路与瓶颈

```
prompt YAML(assets/prompts/*.yaml) → orchestrator.judge → _coerce_score【拍平】
→ quality_evaluators 组装 details.dimensions(仅5字段) → events.py 整体透传
→ constraint_results.details(JSONB,任意深) → 前端 ConstraintItem(只认 details.errors)
```

管道层（ingest schema `{}` + JSONB + 整体透传）**已就绪、无需迁移**；瓶颈在产出端 3 处 + 展示端 2 处（见 §四）。

---

## 二、设计总览

- **评分仍 0-10/维度**，归一化到 [0,1] 的逻辑不变（`quality_evaluators.py:143-154`）。
- **每维度输出升级为对象**：`{score, reason, issues[], highlights[]}`（`band` 由 score 派生，不让 LLM 给，避免分/级不一致）。
- `issues[]` 结构化：`{desc, severity, evidence?}`；`severity ∈ {high, medium, low}`。
- **向后兼容**：仍返回裸 number 的旧提示词照常工作（`_coerce_score` 提取 number；无 issues 时 details 维持旧形态）→ 支持逐个提示词升级。

---

## 三、5 个评估器的细化评分标准（核心内容）

> 每个子维度给出：① 分档行为标准（各档"长什么样"）② 扣分触发条件 ③ 证据要求。
> 实施时 dim_id 以各提示词 YAML 的 `dimensions[].dim_id` 为准（`pedagogical_logic` = structure/progression/engagement；其余 4 个见各自 YAML，对齐即可）。

### 3.1 教学逻辑 `pedagogical_logic`（structure 0.4 / progression 0.3 / engagement 0.3）

**结构完整性 structure**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 完整覆盖 目标/导入→新授→练习/示例→总结/评价 全环节，承转自然 |
| 7-8 | 覆盖≥4 环节，个别（如总结/导入）偏弱但流程可支撑教学 |
| 5-6 | 缺 1-2 个关键环节，或环节间断层、缺衔接 |
| 3-4 | 仅内容堆砌，缺教学结构（导入/练习/总结缺≥3 项） |
| 0-2 | 无教学设计结构，纯文本罗列 |

- 扣分触发：缺总结/评价；无导入或目标；练习与内容脱节；环节断裂无过渡。
- 证据：指出缺失环节名 / 引用衔接处原文。

**知识递进 progression**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 由浅入深、具体→抽象清晰阶梯，前后铺垫呼应，无断层 |
| 7-8 | 整体递进合理，局部跳跃略大但可理解 |
| 5-6 | 存在明显认知跳跃/难度断层 |
| 3-4 | 编排混乱，难度反复横跳 |
| 0-2 | 无递进逻辑，知识点随机堆放 |

- 扣分触发：概念先于其前置知识出现；抽象内容无具体示例铺垫；难度断崖。
- 证据：指出跳跃发生在哪两个知识点之间。

**互动设计 engagement**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 多元有效参与（探究/分层/协作/自评）且与目标匹配 |
| 7-8 | 有互动但形式较单一（如仅问答） |
| 5-6 | 偶有互动但流于形式（"思考一下"无具体任务） |
| 3-4 | 基本单向信息呈现 |
| 0-2 | 完全单向灌输 |

- 扣分触发：互动与目标无关；一刀切无分层；伪互动。
- 证据：引用互动任务或指出其缺失。

### 3.2 内容多样性 `content_diversity`（媒体多样性 0.4 / 主题广度 0.3 / 示例丰富度 0.3）

**媒体多样性**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 综合运用≥4 种表达形式（分层任务/案例/图表/问题链/量表/资源索引等）且贴切 |
| 7-8 | 3 种形式，运用较贴切 |
| 5-6 | 2 种形式，单一形式（纯文本）占主导 |
| 3-4 | 基本纯文本，偶有 1 种其他形式 |
| 0-2 | 纯文本堆砌 |

- 扣分触发：为多样而多样、形式与内容不匹配；本可图示却大段文字描述。
- 证据：列出实际出现的表达形式种类。

**主题广度**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 围绕主题覆盖多个有意义的子视角/子主题，无明显核心遗漏 |
| 7-8 | 主要子主题覆盖，个别有意义视角缺失 |
| 5-6 | 覆盖面较窄，仅聚焦 1-2 个子主题 |
| 3-4 | 偏离或仅触及主题表层 |
| 0-2 | 几乎不相关或极窄 |

- 扣分触发：遗漏核心子主题；大量跑题内容。
- 证据：列出已覆盖子主题 / 指出缺失的核心子主题。

**示例丰富度**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 提供多样化、贴近学习者的示例/情境/案例（≥3 类） |
| 7-8 | 有示例但类型较单一 |
| 5-6 | 示例少或与学习者距离远 |
| 3-4 | 几乎无示例 |
| 0-2 | 无任何示例 |

- 扣分触发：示例不贴切学情；示例单一。
- 证据：引用示例或指出缺失。

### 3.3 深度偏好 `depth_preference`（知识深度 0.4 / 细节程度 0.3 / 严谨程度 0.3）

**知识深度**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 触及学科本质与核心概念，深度匹配学段认知 |
| 7-8 | 多数核心概念到位，个别浅尝 |
| 5-6 | 停留表面罗列，核心概念阐释不足 |
| 3-4 | 偏浅，仅罗列事实 |
| 0-2 | 无实质内容 |

- 扣分触发：核心概念一笔带过；深度低于学段要求。
- 证据：指出哪个核心概念阐释不足。

**细节程度**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 关键概念/原理/方法有充分展开、解释或示范 |
| 7-8 | 多数关键点有展开 |
| 5-6 | 关键点常一笔带过 |
| 3-4 | 几乎无展开 |
| 0-2 | 无细节 |

- 扣分触发：关键方法无示范；原理无解释。
- 证据：指出被略过的关键点。

**严谨程度**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 概念表述、学科用语准确严谨，无科学性瑕疵 |
| 7-8 | 基本准确，偶有用语不规范 |
| 5-6 | 有少量不规范或不严谨表述（非硬错误） |
| 3-4 | 有明显不严谨/易误导表述 |
| 0-2 | 科学性错误较多 |

- 扣分触发：用语不规范；易误导的表述（注：真正的科学性硬错误应由常识检查捕获，此处仅记不严谨）。
- 证据：引用不严谨表述。

### 3.4 风格偏好 `style_preference`（语言风格 0.4 / 排版风格 0.3 / 语气风格 0.3）

**语言风格**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 用词贴合学段学习者，清晰生动可理解 |
| 7-8 | 整体贴合，偶有过于学术/成人化 |
| 5-6 | 部分表述不适配学段 |
| 3-4 | 大量学术/成人化，学习者难懂 |
| 0-2 | 完全不适配目标受众 |

- 扣分触发：生僻词无解释；长难句；学术腔。
- 证据：引用不适配的表述。

**排版风格（文本组织）**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 标题层级清晰、列表/分层结构一致、便于阅读 |
| 7-8 | 整体清晰，偶有不一致 |
| 5-6 | 层级混乱或缺乏结构标记 |
| 3-4 | 基本无排版结构 |
| 0-2 | 一团文本 |

- 扣分触发：标题层级缺失/混乱；无列表或分层；信息密度过高。
- 证据：指出排版混乱处。

**语气风格**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 引导性、鼓励性、亲和力恰当，符合导学场景 |
| 7-8 | 整体得体，偶有生硬 |
| 5-6 | 语气中性偏冷 |
| 3-4 | 生硬/说教 |
| 0-2 | 不友好 |

- 扣分触发：说教腔；缺乏鼓励；冷漠。
- 证据：引用语气问题。

### 3.5 需求满足 `request_fulfillment`（完整性 0.4 / 相关性 0.3 / 质量 0.3）

**完整性**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 覆盖需求全部主要方面（有需求时）或核心内容齐全（无需求时） |
| 7-8 | 覆盖主要方面，个别次要项缺失 |
| 5-6 | 部分满足，有明显缺口 |
| 3-4 | 偏离较多，覆盖<50% |
| 0-2 | 几乎未满足 |

- 扣分触发：遗漏需求明确要求的项；核心内容缺失。
- 证据：列出缺失项 / 引用需求条目对照。

**相关性**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 紧扣主题，无无关/跑题内容 |
| 7-8 | 基本紧扣，少量偏题 |
| 5-6 | 有一定量跑题内容 |
| 3-4 | 大量跑题 |
| 0-2 | 几乎全跑题 |

- 扣分触发：跑题段落；冗余无关内容。
- 证据：指出跑题处。

**质量（产出质量）**

| 分档 | 行为标准 |
|---|---|
| 9-10 | 结构/表述/可用性达可交付水准 |
| 7-8 | 基本可交付，少量打磨空间 |
| 5-6 | 有明显粗糙/不完整 |
| 3-4 | 质量较差，难直接使用 |
| 0-2 | 不可用 |

- 扣分触发：半成品；错别字/格式错误多；结构残缺。
- 证据：指出粗糙处。

---

## 四、结构化输出 Schema（可解释性）

每个维度从 `number` 升级为对象（`output_schema` + `user_prompt_template` 同步改）：

```jsonc
{
  "structure": {
    "score": 8,                              // 0-10，必填
    "reason": "结构基本完整，但总结环节偏弱",      // 该维度一句话总评
    "issues": [                              // 扣分点（可为空数组）
      { "desc": "缺少明确的总结/评价环节", "severity": "medium", "evidence": "全文未见'小结/回顾'" }
    ],
    "highlights": ["导入与练习衔接自然"]          // 亮点（可为空数组）
  },
  "progression": { /* 同上 */ },
  "engagement": { /* 同上 */ },
  "summary": "全局评语：亮点 + 主要短板"            // 保留
}
```

约束：

- `severity`：`high|medium|low`（high≈该维度≤4 分的主因；low≈小瑕疵）。
- `band` **不要求 LLM 输出**，由 score 派生（9-10 优秀 / 7-8 良好 / 5-6 合格 / 3-4 不足 / 0-2 严重不足），避免分/级矛盾。
- system_prompt 增补硬约束：**`issues` 必须可溯源**（尽量给 evidence 原文片段或位置）；**禁止捏造**（内容无该问题时 `issues=[]`）；`reason` 与 `issues` 不得互相矛盾、与 `score` 区间自洽（如 score=9 但 issues 含 high → 自相矛盾，应避免）。

---

## 五、改动清单（按链路顺序）

### 5.1 产出端（评估器，`evaluator/`）

1. **提示词 YAML**（`agent_eval/assets/prompts/{pedagogical_logic,content_diversity,depth_preference,style_preference,request_fulfillment}.yaml`）
   - `system_prompt`：把"评审口径 + 评分锚点"替换为 §三的**细化分档行为标准 + 扣分触发 + 证据要求**；增补"issues 可溯源、不得捏造、分/级自洽"硬约束。
   - `output_schema`：每维度 `type: number` → `type: object`（`score/reason/issues/highlights`）；`summary` 保留。
   - `user_prompt_template`：JSON 示例改为对象结构。

2. **`agent_eval/llm/judge/orchestrator.py`**（`_coerce_score` + `single_judge` + JudgeRecord 透传）
   - `_coerce_score` 改为**严格解析**（仅接受 `number` 与 `{"score": number, ...}`；bool/str/None/对象缺 score 等非法形态一律抛 `LLMError`，不再静默兜底 0.0 或正则提取字符串），便于调试定位；`single_judge` 缺维度同样抛错（schema 已 required）。
   - **新增**：`single_judge` 中对每个维度，若 LLM 返回 dict，则把 `{reason, issues, highlights}` 收集到 `dim_details[dim_id]`（per sample，经 `_extract_dim_detail`），与 `scores` 并行；纯数值维度 `dim_details[dim_id]={}`。
   - 把 `dim_details`（取末样本；temperature=0 下三样本近似一致）写入 `JudgeRecord`（`llm/models.py` 增字段 `dim_details` + `to_dict`/`from_dict`），随 `evidence/*.json` 持久化。
   - 兼容：纯数值提示词的维度 → `dim_details` 为空 → 下游 details 维持旧形态（number 仍被严格解析接受）。

3. **`agent_eval/evaluation/evaluators/quality_evaluators.py:170-191`**（组装 details）
   - `details["dimensions"][i]` 增补 `reason/issues/highlights/band`（band 由 score 派生），取自 `record.dim_details.get(dim_id, {})`。
   - `reason` 文本（165-167）可同步丰富：除维度分外，追加该维度 top1 issue（若 score<7）。

### 5.2 管道层（无需改动，已验证）

- `observability/events.py`：`details` 整体透传。
- `db/web/prisma/schema.prisma` + `web/backend/src/repositories/ingest.repository.ts`：`details/moduleResults` 已 JSONB 整块写。
- `web/backend/src/schemas/ingest.event.v1.json`：`details` 为 `{}`（任意 JSON）——**可选**补 `properties.dimensions[].issues` 描述强契约（非必须）。

### 5.3 展示端（`web/frontend/`）

4. **`web/frontend/src/pages/SampleDetail.tsx:179-239`**（ConstraintItem）
   - 新增 `DimensionBreakdown` 渲染：当 `c.details.dimensions` 存在时，逐维度展示——`名称 · 分数/10 · band 徽章 · reason`，下方 `issues[]`（按 severity 着色：high 红 / medium 黄 / low 灰）+ `highlights[]`（绿）。
   - 既有 `constraintErrors(details.errors)`（硬约束用）保留；质量约束走新的 `DimensionBreakdown` 分支。
   - 折叠的"调试详情"原始 JSON 保留（兜底）。

5. **速览 overview**（`web/backend/src/repositories/query.repository.ts` runOverview select + `web/backend/src/services/evalJob.service.ts` OverviewFailure/buildJobOverview）
   - runOverview 的 `constraintResults.select` 增 `details`（失败约束）。
   - `OverviewFailure` 增 `top_issues: string[]`（取该约束各维度 high/medium issue 的 desc，最多 3 条）；`buildJobOverview` 映射。
   - 效果：第三方 iframe 速览的"各项失败原因"从一句话变为"评分 + 关键扣分点"。

---

## 六、兼容性与稳定性

- **逐评估器灰度**：一个提示词改完即可上线（旧提示词不受影响，details 自动回退旧形态）。
- **稳定性**：temperature=0.0 + 固定 seed，三样本近似一致；`issues` 等定性字段取中位数样本，分数仍走 3 样本中位数 + stddev 置信度（`stability.py` 不变）。
- **成本**：输出 token 略增（issues/highlights/reason）；可先在 1 个评估器实测 token 与耗时再推广。
- **判官 provider 无关**：deepseek/kimi 均走 `StructuredOutputParser`（jsonschema 校验），新 schema 自动生效。

---

## 七、渐进式落地顺序（建议）

1. 先做 **`pedagogical_logic`**（最典型、子维度清晰）作样板：改提示词 → orchestrator 透传 `dim_details` → quality_evaluators details 组装 → 前端 DimensionBreakdown。
2. 跑 1 个真实课件样本，人眼校验 `details.dimensions[].issues` 是否准确、可溯源；调提示词至稳定。
3. 速览 overview 的 `top_issues` 一起打通。
4. 把样板提示词结构复制到其余 4 个评估器（仅替换 rubric 文本与 dim_id），逐个验证。

---

## 八、验证

- **单元**：`evaluator/tests/unit/` 加测——`_coerce_score` 仍正确提 number；`single_judge` 对 `{score,issues}` 输入能同时产出 score 与 `dim_details`；quality_evaluators details 含 `issues/highlights/band`（用 fixtures 黄金样本断言新字段）。
- **离线跑评**：`uv run agent-eval eval <样本>` → 检查 `workspace/runs/*/results/*/rule_results.json` 中 soft/pref 约束的 `details.dimensions[].issues` 非空且可溯源；`evidence/judge_*.json` 含 `dim_details`。
- **前端**：`npm run build` + 本地 `/run/:id/sample/:sid` 看 DimensionBreakdown 渲染（issues 着色、band 徽章）。
- **速览**：`GET /api/v1/jobs/:id/overview` 的 `items[].failures[]` 含 `top_issues`。
- **回归**：未升级的评估器 details 形态不变（兼容性）；`make check` / web lint+typecheck+test 全绿。

---

## 九、版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-07-09 | 初稿：5 个质量评估器（soft×2 + pref×3）的逐维度细化评分标准（分档行为 + 扣分触发 + 证据要求）；结构化逐项输出 schema（`{score, reason, issues[], highlights[]}`）；产出端 3 处 + 展示端 2 处改动清单；兼容性与逐评估器灰度落地顺序、验证。 |
| v1.1 | 2026-07-09 | 实施同步：`_coerce_score` 改严格解析（去兼容兜底，非法形态抛 `LLMError`，§五.1.2 更新）；`dim_details` 透传落地（orchestrator `_extract_dim_detail` → JudgeRecord → quality_evaluators details.dimensions[].band/issues/highlights）；前端 `DimensionBreakdown` + 速览 `top_issues`；补单测（`_coerce_score` / `_extract_dim_detail` / quality details 组装）；真实 LLM 跑评 + 前端实地渲染验证通过。 |
