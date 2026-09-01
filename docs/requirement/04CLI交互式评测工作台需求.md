# CLI 交互式评测工作台需求

> 本文档定义 `agent-eval` CLI 从「命令集合」升级为「评测工作主载体」的需求：以**向导式交互**覆盖评测完整生命周期（场景包创建/修改 → 评测执行 → 结果查看/上报），以 **Agent 能力**（DeepAgents 底座）支撑场景包的自然语言工程，以**账号体系与浏览器联动**打通平台身份，同时保持**脚本/CI 友好**的非交互形态。属于 [02 Agent 评估系统需求](./02Agent评估系统需求.md) 在 CLI 端的深化，场景包结构遵循 [13 配置管理设计](../arch/13配置管理设计.md)，Agent 底座遵循 [03 执行引擎设计](../arch/03执行引擎设计.md) §3.2，配置体系遵循 [06 数据管理与配置规范](../arch/06数据管理与配置规范.md) §四。

---

## 一、引言

### 1.1 编写目的

为 CLI 交互式评测工作台（下称「工作台」）的开发提供需求基线：明确目标用户与场景、命令体系规划（含既有命令重命名与兼容策略）、功能需求（F-C-\*）、非功能需求（NF-C-\*）、交互原型与分期计划，作为后续架构设计与迭代排期的输入。

### 1.2 背景与现状

本地 CLI 已具备较完整的评测执行能力，且是未来评测工作开展的主要载体：

| 能力域 | 现状 |
|--------|------|
| 评测执行 | `eval` / `run` / `pipeline` 三模式贯通；`--task` 五种选择语法；`suite` 声明式矩阵 |
| 模型配置 | `models login/list/test/logout` 交互式向导 |
| 凭证管理 | `secrets set/list/delete` + env 双通道 |
| 场景包 | `package init/validate/list/pull`；内置 courseware / chat / code 三包 |
| 结果上报 | `upload` 回填 + ResultSink 自动摄取；`--upload` 开关 |

**差距**（本需求要解决的）：

1. **场景包创建门槛高**：新建/修改场景包需手工编写十余类 YAML（清单/规则集/提示词/考卷/SUT/聚合策略），只有熟悉 [13](../arch/13配置管理设计.md) 全部规范才能上手；`package init` 仅生成目录骨架。
2. **无 Agent 能力**：包的增删改查全靠人工，缺少「描述需求 → Agent 代办」的工程方式。
3. **参数面繁杂**：`pipeline` 等命令参数十余个，新用户需对照教程才能发起一次评测；无选择式交互。
4. **结果查看原始**：评测完成后需自行翻 `workspace/runs/{run_id}/` 下的 JSON/Markdown 文件。
5. **配置分散、身份缺位**：平台接入靠手输 host + 网页复制 API Key，无账号体系概念；模型、凭证、平台配置分属不同命令与文件，缺少统一自检。
6. **命令命名语义不精确**：`models login` 暗示登录认证而非模型配置；`package`（场景包）与 `pack`（打包执行包）名词撞车；无浏览器联动（打开平台页/报告/注册页均需手动复制 URL）。

### 1.3 名词术语

| 术语 | 定义 |
|------|------|
| **向导模式** | 交互式问答/选择驱动的 CLI 形态（选择 + 回车，免记忆参数） |
| **非交互模式** | 参数完备、无任何提示阻塞的 CLI 形态（CI/脚本用） |
| **工作台** | `agent-eval start` 进入的向导式主入口，串联全部工作域 |
| **PackageAgent** | 基于 DeepAgents 的场景包工程 Agent，经工具面对包做增删改查 |
| **项目包** | 当前目录下 `./<scenario>-package/` 形态的场景包（git 可管理，`--package-dir` 引用） |
| **内置包** | 随 pip 包发布的 `agent_eval/assets/packages/` 场景包（**只读**） |
| **本地包仓库** | `~/.agent_eval/packages/` 下的包（`scenario pull` 目的地） |
| **平台身份** | CLI 侧持有的平台账号凭证（host + API Key + 项目绑定），区别于 SUT 评测凭证（secrets） |
| **浏览器配对** | CLI 打开浏览器完成平台授权并取回 API Key 的登录方式（行业通行的 login 流程） |

### 1.4 与现有文档的关系

| 文档 | 关系 |
|------|------|
| [02 Agent评估系统需求](./02Agent评估系统需求.md) | 上位需求；本文细化其 CLI 交互面 |
| [13 配置管理设计](../arch/13配置管理设计.md) | 场景包结构 / 包清单 / 命名空间的唯一规范，工作台不另造格式 |
| [03 执行引擎设计](../arch/03执行引擎设计.md) | DeepAgents 底座、`build_chat_model` 桥接、BudgetGuard、工具面护栏（tool_guard）的既有实现基础 |
| [06 数据管理与配置规范](../arch/06数据管理与配置规范.md) | 配置面（llm.json / sut_credentials.json / .env / 平台 Secrets）的权威定义 |
| [09 Web可观测平台架构设计](../arch/09Web可观测平台架构设计.md) | 平台账号 / API Key / SSO 与 CLI `auth` 浏览器配对的对接面 |
| [14 场景扩展指南](../arch/14场景扩展指南.md) | PackageAgent 生成新场景包时的方法论参照与 few-shot 素材 |
| [guide/CLI使用教程](../guide/CLI使用教程.md) | 面向用户的操作文档，随功能落地同步更新 |

---

## 二、目标与范围

### 2.1 核心目标

| # | 目标 | 衡量 |
|---|------|------|
| G1 | **全生命周期闭环**：创建/修改场景包 → 查看 → 执行 → 查看结果 → 上报，全部在 CLI 内完成 | 新用户从安装到拿到第一份评测报告，全程不离开终端、不手写 YAML |
| G2 | **场景包 Agent 化工程**：以自然语言驱动场景包的增删改查，Agent 输出经校验与确认后落盘 | 「加一条规则 / 改一个提示词 / 换一个 SUT」类需求一句话完成 |
| G3 | **零门槛交互**：选择 + 回车完成操作，不要求记忆命令参数 | 向导路径覆盖全部高频操作；参数仅作进阶覆盖手段 |
| G4 | **脚本/CI 友好不回退**：所有交互步骤均可被参数或 env 旁路；机器可读输出与稳定退出码 | Jenkins 集成无需伪终端（pty）；同一命令双形态输出一致 |
| G5 | **单一事实源不变**：包结构、Schema、平台契约、配置面完全沿用现行规范 | 工作台是「前端」，不产生第二套格式或第二套真相源 |
| G6 | **命令体系语义清晰**：动宾一致、名词不撞车、账号身份与资源配置分离 | 命令名即文档：`auth login` 登录平台、`models set` 配模型、`scenario new` 建场景包 |

### 2.2 目标用户与场景

| 用户 | 场景 | 主要路径 |
|------|------|---------|
| 评测工程师 | 本地发起与复看评测 | `start` → 执行 → 结果查看 → 上报 |
| 场景作者 | 新建/维护场景包 | `start` → 包管理 → Agent 会话 → 校验发布 |
| 新用户 / 第三方体验者 | 快速跑通第一个评测 | `auth register/login`（浏览器）→ 模板包引导 |
| CI / Jenkins 流水线 | 定时回归、无人值守评测 | 非交互命令 + `--json` + 退出码（§4.9） |

### 2.3 设计原则

- **P1 交互与执行分离**：向导只是既有阶段函数（`cli/_stages.py` 等编排层）的交互式前端；同一内核服务双形态，禁止在向导里复制业务逻辑。
- **P2 非交互一等公民**：每个新增交互点必须存在对应的参数 / env / 配置文件旁路；非 TTY 环境自动降级为非交互（缺失项报错而非挂起）。
- **P3 Agent 沙盒边界**：PackageAgent 的文件工具严格限定在目标包根目录内（路径白名单 + 防逃逸校验），无 shell、无任意路径读写；写操作一律先 diff 确认。
- **P4 渐进披露**：默认路径极简（三步内发起评测），高级项（规则集切换、缓存、并发）折叠为「高级选项」。
- **P5 复用不重造**：执行复用 `run/pipeline`、校验复用 JSON Schema 与语义校验、身份复用平台 API Key 体系；工作台只做编排与呈现。
- **P6 命名规范**：顶层命令 = 名词域（`scenario/models/secrets/suite/runs`）或高频动词（`run/eval/pipeline/pack/upload`）；子命令 = 动词（set/list/show/clear）；「login/logout」仅用于账号身份（auth），不用于资源配置；重命名一次性直接切换，不设兼容层。

### 2.4 范围

- **含**：工作台入口与导航；账号与配置域（auth 浏览器配对 / models / secrets / doctor）；场景包创建（模板 + Agent 两条路）、Agent 会话改包、包内容查看；向导式执行（run / eval / pipeline）；本地结果浏览与上报；浏览器联动（`open` 与 `--web`）；命令重命名与兼容策略；自动化集成规范（非交互 / JSON / 退出码 / Jenkins 范式）。
- **不含**：Web 端配置编辑器（属 [09](../arch/09Web可观测平台架构设计.md) 既有范围）；评测引擎与指标逻辑变更；全屏 TUI（列 P2 远期）；包发布到平台 DB 的 push 通道（开放问题 #2）。

---

## 三、总体方案

### 3.1 双前端同内核

```
                    ┌────────────────────────────┐
  agent-eval start  │  向导前端（问答/选择/回车）  │   交互形态 A：人用
  agent-eval <cmd>  │  参数前端（flags/env/json） │   交互形态 B：脚本/CI 用
                    └──────────┬─────────────────┘
                               │ 同一调用面
                    ┌──────────▼─────────────────┐
                    │  编排层（cli/_stages.py 等） │
                    │  resolve / execute /        │
                    │  evaluate / finalize        │
                    └──────────┬─────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        PackageManager   PipelineEngine    ResultSink / upload
              ▲
              │ 工具面（沙盒）
        PackageAgent（DeepAgents）          ← 仅包工程域引入 Agent
```

### 3.2 命令体系（目标态）

按域组织的顶层命令全景：

| 域 | 命令 | 形态 | 说明 |
|----|------|------|------|
| 工作台 | `start` | 向导 | 主入口，四大工作域导航 |
| **账号** | `auth login` | 向导+浏览器 | 平台登录：浏览器配对（推荐）/ 粘贴 API Key；写入本地平台身份 |
| | `auth status` | 参数 | 身份、所属团队/项目、Key 有效性 |
| | `auth logout` | 参数 | 清除本地平台凭证 |
| | `auth register` | 浏览器 | 打开平台注册页，完成后再引导 `auth login` |
| **模型** | `models set` | 向导 | 交互配置三角色（替代原 `models login`）；可打开 Provider 控制台取 Key |
| | `models list / test / clear` | 参数 | 清单 / 连通测试 / 清除（`clear` 替代原 `logout`） |
| **场景包** | `scenario new` | 向导+Agent | 创建项目包：模板 scaffold 或 Agent 生成 |
| | `scenario edit` | Agent 会话 | 自然语言增删改查 |
| | `scenario show` | 参数 | 终端富展示包内容（`--web` 打开平台资产页） |
| | `scenario list / validate / pull` | 参数 | 既有 `package` 组能力改名承接（`init` 并入 `new --skeleton`） |
| **凭证** | `secrets set / list / delete` | 混合 | SUT 评测凭证（不变）；与 auth 的区别：auth=平台身份，secrets=被测系统凭证 |
| **执行** | `run / pipeline / eval / pack` | 参数（向导内复用） | 不变；`pack`= 把手动产出物打包为执行包 |
| | `suite plan / run` | 参数 | 不变 |
| **结果** | `runs list / show` | 向导/参数 | 本地运行浏览与详情（`show --web` 打开平台对应页） |
| | `upload` | 参数 | 不变；向导内提供上报入口 |
| **联动** | `open <target>` | 参数 | 浏览器打开：platform / run / report / scenario / secrets / keys / docs |
| 运维 | `doctor` | 参数 | 一键自检（顶层命令，对齐 `flutter doctor` 惯例） |
| 其他 | `dataset` / `knowledge` / `version` | 参数 | 不变 |

### 3.3 既有命令重命名（直接切换，不做向下兼容）

> 当前用户基数小，重命名**一次性直接切换**：旧命令名移除，不设别名层与弃用警告机制；`docs/guide/CLI使用教程`、示例脚本与 CI 片段随同一版本同步更新，全仓引用一并清理。

| 现状 | 目标 | 理由 |
|------|------|------|
| `models login` / `models logout` | `models set` / `models clear` | 「login」暗示账号认证，实为本地资源配置；动宾一致 |
| `package init/validate/list/pull`（+ 规划中的 new/edit/show） | `scenario new/validate/list/pull/edit/show`（`init` 并入 `new --skeleton`） | 与顶层 `pack`（打包执行包）名词撞车；域名为「场景」，与平台 scenario 资产语言一致 |
| `config platform` / `config doctor`（规划稿） | `auth login`（平台接入）+ 顶层 `doctor` | 平台接入本质是身份与凭证，归 auth；doctor 提升为顶层命令提高可发现性 |
| `results`（规划稿） | `runs list / runs show` | 对齐领域语言（`workspace/runs/`、平台 Run 实体）与 `gh run` 惯例 |

### 3.4 PackageAgent（场景包工程 Agent）

- **底座**：复用 [03](../arch/03执行引擎设计.md) §3.2 的 `create_deep_agent` + `build_chat_model`（LLM 角色 `agent`，未配置回退 `text`）；不挂 checkpointer（一次性会话）；预算沿用 BudgetGuard；System Prompt 资产化（`agent_eval/assets/configs/package_agent_prompts.yaml`，对齐 v4.6.5 惯例）。
- **工具面**（全部限定包根目录，路径逃逸校验沿用 task_id 白名单范式）：

| 工具 | 职责 |
|------|------|
| `list_package_files` / `read_file` | 读包结构与内容 |
| `write_file` / `delete_file` | 写/删包内文件（落盘前必须过 diff 确认与校验门禁） |
| `read_manifest` / `update_manifest` | 包清单读写（版本、default_rule_set 等） |
| `validate_package` | JSON Schema + 语义校验，返回结构化错误列表 |
| `search_reference` | 检索内置包（courseware/chat/code）与 [14 指南](../arch/14场景扩展指南.md)作为生成参照 |
| `preview_diff` | 生成统一 diff 供用户确认 |

- **会话流程**：用户自然语言需求 → Agent 输出**改动计划**（改哪些文件、为什么）→ 调工具生成 → `preview_diff` 展示 → 用户确认（逐文件 / 全部 / 放弃）→ `validate_package` 门禁（不过则拒绝落盘并回改）→ 落盘 + 记录会话日志（含 token/耗时）。
- **安全红线**：sut_config 内只允许写 `credential_ref` 引用，**禁止生成凭证明文**（发现即拒绝并提示走 `secrets set`）；工具面无 shell / 无网络 / 无包外路径；非交互 Agent 模式（CI 无人确认）必须显式 `--trust-agent` 才可启用。

### 3.5 身份与配置面

三块配置 + 一键自检，全部落既有真相源（P5），工作台只做聚合呈现：

| 配置块 | 真相源 | 工作台动作 |
|--------|--------|-----------|
| 平台身份（host / API Key / 项目） | env `AGENT_EVAL_HOST/API_KEY/PROJECT` | `auth login` 浏览器配对或粘贴 Key → 连通性测试 → 写入 `.env`（仅环境接入，遵循 06 §4.7） |
| 模型（三角色） | `~/.agent_eval/llm.json` | `models set` 向导（可打开 Provider 控制台取 Key） |
| 凭证（SUT） | `~/.agent_eval/sut_credentials.json` / env | 复用 `secrets set`，按所选 SUT 的 `credential_ref` 引导补齐缺失字段 |
| 自检 `doctor` | — | 逐项检查：平台身份与连通、模型三角色、所选 SUT 凭证完整、包可解析、workspace 可写，输出体检表 |

**auth 与 secrets 的边界**：`auth` 管平台身份（我是谁、以哪个团队/项目上报）；`secrets` 管被测系统凭证（怎么登录 SUT）。两者都是凭证，但委托对象不同，命令域不混用。

### 3.6 浏览器联动

| 场景 | 行为 |
|------|------|
| `auth login`（浏览器配对） | 生成一次性配对码 → 调用系统浏览器打开平台 CLI 授权页 → 用户在浏览器登录并确认 → 粘贴回 CLI 显示的确认码（或 P2 设备码流自动轮询）→ 取回 API Key |
| `auth register` | 打开平台注册页；注册完成引导 `auth login` |
| `models set` 过程中 | 询问「打开 <Provider> 控制台获取 API Key？」→ 打开对应密钥管理页（如 DeepSeek / Moonshot 控制台） |
| `open <target>` / `--web` | 打开平台页（项目看板 / Run 详情 / 场景资产 / Secrets / API Keys / 文档）或本地报告 |
| 无浏览器环境（SSH / 容器 / `$BROWSER` 缺失） | **不强行调用浏览器**：打印可点击 URL + 配对码，由用户在本地机器打开（`gh auth login` 同款降级） |

### 3.7 行业参照

| 参照 | 借鉴点 |
|------|--------|
| `gh auth login`（GitHub CLI） | 设备码/浏览器登录、SSH 环境打印 URL 降级、`auth status` 体检 |
| `gcloud auth login` / `stripe login` | 浏览器授权取凭证的成熟范式 |
| `gh run view --web` / `vercel open` | 查看类命令的 `--web` 与 `open` 打开对应网页 |
| `flutter doctor` / `npm doctor` | 顶层 doctor 一键自检与修复建议 |
| `gcloud init` / `vercel` / `stripe` 首次向导 | 首次使用向导 + 状态落盘 + 连通性即时验证 |
| `gh` 交互与 `--json` 并存 | 双形态输出；非 TTY 自动降级 |
| Claude Code / Aider | 会话式 Agent：计划先行、diff 确认、工具调用透明可溯 |
| `create-next-app` / cookiecutter | 模板 scaffold + 交互式选项收敛为工程惯例 |
| 12-factor CLI 原则 | 非交互可旁路、stdout/stderr 分离、稳定退出码、幂等 |

---

## 四、功能需求

### 4.1 工作台导航（F-C-NAV）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-NAV-01 | `agent-eval start` 进入主菜单，提供四大工作域：场景包管理 / 评测执行 / 结果查看 / 账号与配置 | P0 |
| F-C-NAV-02 | 菜单支持 ↑↓ 选择、回车确认、ESC 返回上级、Ctrl-C 优雅退出（清理临时态） | P0 |
| F-C-NAV-03 | 工作台显示当前上下文（平台身份态 / 活动包 / 考卷 / SUT），跨菜单保持；选择结果可被后续步骤直接复用 | P0 |
| F-C-NAV-04 | 非法/为空状态给出引导（未登录平台 → 跳转 auth；未配置模型 → 跳转 models set；无项目包 → 引导创建或选内置包） | P1 |
| F-C-NAV-05 | 向导内每一步显示等价命令行（`等价命令: agent-eval pipeline --package chat ...`），作为用户学习参数面的脚手架 | P1 |

### 4.2 平台账号与浏览器配对（F-C-AUTH）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-AUTH-01 | `auth login` 交互选择登录方式：**浏览器配对**（生成一次性配对码 → 打开平台 CLI 授权页 → 用户浏览器登录确认 → 粘贴确认码 → 获取 API Key）/ **粘贴 API Key**（已有 Key 直接输入，隐藏回显） | P1 |
| F-C-AUTH-02 | 登录成功后展示身份回执（用户、团队、项目、Key 掩码），连通性测试通过后写入 `.env`（`AGENT_EVAL_HOST/API_KEY/PROJECT`，仅环境接入）；密钥文件权限 0600 | P1 |
| F-C-AUTH-03 | `auth status`：本地身份信息 + 平台 ping（Key 有效性、团队/项目归属）；未登录时明确提示并给出 `auth login` 指引 | P1 |
| F-C-AUTH-04 | `auth logout`：清除本地平台凭证（`.env` 相关项）；可选 `--revoke` 吊销平台侧 Key（需平台端点，P2） | P1 |
| F-C-AUTH-05 | `auth register`：打开平台注册页，轮询/等待用户完成后引导 `auth login` | P2 |
| F-C-AUTH-06 | 设备码流免粘贴：CLI 生成配对码后自动轮询平台授权状态，浏览器确认即完成（需平台新增 CLI 配对端点，见开放问题 #1） | P2 |
| F-C-AUTH-07 | 非交互形态：`auth login --token <key>` 或 env 直供（CI 无浏览器）；无浏览器环境检测（SSH / 无 `$BROWSER`）自动降级为打印 URL + 配对码 | P1 |

### 4.3 配置与自检（F-C-CONFIG）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-CONFIG-01 | `models set`（替代 `models login`）交互向导：provider → base_url → api_key → 三角色分配；过程中可选「打开 Provider 控制台获取 Key」（§3.6） | P0 |
| F-C-CONFIG-02 | `doctor` 顶层命令：平台身份与连通、模型三角色逐个 ping、所选 SUT 凭证完整、包可解析、workspace 可写、依赖 extras（agent/llm）安装状态；逐项 ✅/❌/⚠️ 与修复建议；支持 `--json` | P0 |
| F-C-CONFIG-03 | 凭证引导：选择 SUT 后对照其 `credential_ref` 检查 `secrets` 缺失字段，缺则引导 `secrets set` 补录（不在向导内明文回显已存值） | P1 |
| F-C-CONFIG-04 | 命令重命名直接切换：`models login/logout`、`package *` 等旧名随版本移除（无别名层），`docs/guide/CLI使用教程`、示例脚本、CI 片段与全仓引用同步清理 | P0 |

### 4.4 场景包创建（F-C-SCN-NEW）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-SCN-NEW-01 | `scenario new` 两条路径任选：**模板 scaffold**（问场景 ID / 评估对象类型 / 规则分档 → 基于内置模板生成最小可用包，含 `--skeleton` 纯骨架模式承接原 `init`）与 **Agent 生成**（自然语言描述评测需求 → PackageAgent 生成完整包） | P1 |
| F-C-SCN-NEW-02 | 落盘位置为当前目录 `./<scenario>-package/`（已存在时提示改名或选择覆盖 diff）；内置包只读，不可作为写目标（改造内置包时先 fork 为项目包） | P1 |
| F-C-SCN-NEW-03 | 生成完成即自动执行 `validate_package` 并展示结果；校验失败可回到 Agent 会话修复 | P1 |
| F-C-SCN-NEW-04 | 生成后提示后续路径：`--package-dir` 引用执行 / 提交 git / （开放问题 #2）发布到平台 | P2 |

### 4.5 Agent 会话改包（F-C-SCN-AGENT）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-SCN-AGENT-01 | `scenario edit` 进入多轮会话；用户以自然语言提出增删改查需求（如「加一条图片必须带 alt 的格式门控」「把考卷换成 20 题」「SUT 换生产环境地址」） | P1 |
| F-C-SCN-AGENT-02 | Agent 动手前先输出**改动计划**（文件清单 + 意图说明），用户确认后进入工具执行 | P1 |
| F-C-SCN-AGENT-03 | 所有写操作以统一 diff 呈现，支持逐文件 / 全部 / 放弃三种确认；放弃则包保持原样 | P1 |
| F-C-SCN-AGENT-04 | 校验门禁：diff 确认后必须通过 `validate_package`（Schema + 语义）才落盘；失败时 Agent 读取错误自修复，最多 N 轮（默认 3）后交还用户 | P1 |
| F-C-SCN-AGENT-05 | 会话日志落 `workspace/agent_logs/package_agent_<ts>.jsonl`（工具调用、token、耗时），可审计复现 | P1 |
| F-C-SCN-AGENT-06 | 安全边界：文件工具仅限包根；sut_config 凭证明文禁止生成（强制 `credential_ref`）；LLM 不可用时明确降级提示（会话不可用，可用模板路径） | P1 |
| F-C-SCN-AGENT-07 | 版本管理：改动落盘可选 `manifest.version` 语义化递增（patch/minor/major 问询） | P2 |
| F-C-SCN-AGENT-08 | 非交互 Agent 模式：`scenario edit --instruction "..." --yes --trust-agent` 供 CI 使用；默认关闭 | P2 |

### 4.6 场景包查看（F-C-SCN-VIEW）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-SCN-VIEW-01 | `scenario show` / 向导内查看：包结构树（文件 + 行数）、包清单摘要（场景/版本/default_rule_set/default_task_set） | P0 |
| F-C-SCN-VIEW-02 | 规则集视图：维度 / 级联阶段 / 规则表（id、评估器、tier、weight、enabled）；考卷视图：任务数、首 N 条任务预览 | P0 |
| F-C-SCN-VIEW-03 | SUT 视图：通道类型、端点、鉴权策略、`credential_ref` 与凭证就绪态（✅/❌，不显示值） | P0 |
| F-C-SCN-VIEW-04 | 提示词 / 数据集 / 聚合策略的分文件查看（分页或指定文件名）；`--web` 打开平台资产编辑页（已登录且资产已同步时） | P1 |

### 4.7 向导式执行（F-C-EXEC）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-EXEC-01 | 执行向导五步：选包（内置 / 项目包 / 本地仓库）→ 选考卷（包内 task_sets，可 `--task` 细选）→ 选 SUT（包内 sut_configs）→ 选规则集（缺省=包清单 default_rule_set）→ 选模式（run 仅执行 / pipeline 一体化）；eval-only 场景自动收敛步骤 | P0 |
| F-C-EXEC-02 | 执行前摘要确认页：包/考卷/SUT/规则集/LLM 角色/预估规模（任务数）一览，回车开始 | P0 |
| F-C-EXEC-03 | 执行过程两种展示：**完整输出**（现有日志流，`--verbose`）与**进度视图**（任务级进度条 + 实时状态表：任务、阶段、结果），进度视图结束回落完整摘要 | P0 |
| F-C-EXEC-04 | 高级选项折叠区：LLM 角色、缓存开关、并发、预算上限、上传开关 | P1 |
| F-C-EXEC-05 | 中断处理：Ctrl-C 询问（终止 / 跳过当前任务继续评估 / 保存已完成部分）；已完成包与 run_manifest 保持可用 | P1 |
| F-C-EXEC-06 | 向导选择结果映射为既有命令执行（F-C-NAV-05 同步显示等价命令），执行内核与参数形态完全同源 | P0 |

### 4.8 结果查看与上报（F-C-RUNS）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-RUNS-01 | `runs list`：本地 runs 列表（时间、包、任务数、Reward、DR/CPR、上传态），可选中进入详情 | P0 |
| F-C-RUNS-02 | `runs show <run_id>`：指标卡（按 `MetricDefinition` 动态渲染，不硬编码）、失败 breakdown TopN、逐任务状态表；任务可下钻看约束级 reason 与 `source_files` 归因 | P0 |
| F-C-RUNS-03 | 报告打开：终端渲染 summary.md 摘要 / `--open` 用系统默认程序打开完整报告 | P1 |
| F-C-RUNS-04 | 上报向导：未上传的 run 一键 `upload`；已配置平台时显示回执（平台 run URL）并可 `open run <id>` 直达 | P1 |
| F-C-RUNS-05 | 结果对比：选两个 run 并排对比指标差异（本地版，轻量） | P2 |

### 4.9 浏览器联动（F-C-OPEN）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-OPEN-01 | `open <target>`：`platform`（项目看板）/ `run <run_id>` / `report <run_id>` / `scenario <ref>` / `secrets` / `keys` / `docs`，按目标拼接平台 URL 并调用系统浏览器 | P1 |
| F-C-OPEN-02 | 查看类命令 `--web` 旗标：`runs show --web`、`scenario show --web` 等价于 `open` 对应目标 | P1 |
| F-C-OPEN-03 | 未登录平台时提示 `auth login`；本地 run 在平台无对应记录时降级打开本地报告；无浏览器环境打印 URL 而非强行调用（§3.6） | P1 |

### 4.10 自动化与集成（F-C-INTEG）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-C-INTEG-01 | 全局非交互保障：所有新增交互点支持参数/env 旁路；非 TTY 检测到缺失必需输入时以明确错误退出（exit 2），不挂起等待 | P0 |
| F-C-INTEG-02 | `--output-format json`（或 `--json`）：执行与结果命令输出机器可读 JSON（run_id、指标、失败明细、制品路径）；进度日志走 stderr，stdout 仅 JSON | P0 |
| F-C-INTEG-03 | 退出码规范：0 成功；1 评测业务失败（含门控阈值未达）；2 配置/输入错误；3 依赖不可用（LLM/SUT/平台）；130 用户中断。文档化并纳入测试 | P0 |
| F-C-INTEG-04 | 幂等与缓存：相同输入 + 内容指纹命中缓存跳过 LLM 调用（既有 W8 机制），CI 重复构建不产生重复开销 | P0（复用） |
| F-C-INTEG-05 | Jenkins 集成范式：提供声明式 pipeline 片段（非交互 + JSON 解析 + 退出码门禁 + 报告归档 artifact），纳入 `docs/guide` | P1 |

---

## 五、交互原型

> 以下为终端形态示意（`?` 提问、`❯` 当前选项、`[↑↓/回车]` 操作提示），实现以交互组件库实际渲染为准。

### 5.1 工作台主入口

```text
$ agent-eval start

╭─ agent-eval 评测工作台 ───────────────────────────────╮
│ 平台: 张三@教研组 ✅   模型: text✅ vision✅ agent✅     │
│ 当前包: chat@1.0.0 (内置)        workspace: ~/…/ws    │
╰──────────────────────────────────────────────────────╯

? 选择工作域  [↑↓ 选择，回车确认]
❯ 1. 场景包管理   创建 / 修改(Agent) / 查看
  2. 执行评测      run / pipeline / eval-only
  3. 查看结果      运行列表 / 指标 / 失败明细 / 上传
  4. 账号与配置    auth / 模型 / 凭证 / 自检(doctor)
```

### 5.2 平台登录（浏览器配对）

```text
$ agent-eval auth login

? 选择登录方式
❯ 1. 浏览器配对（推荐）  打开浏览器登录平台并授权
  2. 粘贴 API Key        已在平台「API Keys」页创建过 Key

── 浏览器配对 ──────────────────────────────────────────
  ✅ 已打开浏览器:  https://eval.example.com/cli-auth
     （无浏览器环境将打印 URL，请在本地机器打开）

  配对码:  ┌─────────────┐
           │ 4F2A-9K7C   │   ← 在浏览器页面输入此码确认授权
           └─────────────┘
? 粘贴浏览器返回的确认码: ••••••

  ✅ 授权成功，已获取 API Key (eval-…3f2a)
  ✅ 身份: 张三 @ 评测平台-教研组 · 默认项目: 课件生成
  → 已写入 .env (0600): AGENT_EVAL_HOST / API_KEY / PROJECT

$ agent-eval auth status
  平台   ✅ https://eval.example.com  张三@教研组  Key 有效
  模型   text ✅ deepseek-chat   vision ✅ kimi-k2.6   agent ⚠️ 回退 text
```

### 5.3 场景包 Agent 会话（创建 → 修改）

```text
? 场景包管理 → 创建方式
❯ 1. 模板 scaffold（最小可用，手动完善）
  2. Agent 生成（描述你的评测需求）

── Agent 生成 ──────────────────────────────────────────
? 描述评测需求:
> 评估一个行程规划 Agent，重点检查安全提示是否遗漏，
  行程时间地点是否自洽，输出 JSON 计划

🤖 改动计划（3 个文件）:
   1. 新增 rules/safety.yaml        — 安全门控规则集(4 条)
   2. 新增 prompts/safety.yaml      — 安全审查判官提示词
   3. 新增 agent_eval.yaml          — 包清单(travel@0.1.0)
   参照: 内置包 chat@1.0.0 + arch/14 §三
? 执行以上计划? (Y/n) y

🤖 生成完成，以下变更待确认:
   ── rules/safety.yaml (新增) ────────────────────────
   +dimensions:
   +  - id: safety
   +    ...
? 逐文件确认  ❯全部应用   ○逐个确认   ○放弃

✅ 校验通过 (schema ✓ 语义 ✓)
✅ 已落盘 ./travel-package/  (0.1.0)
   下一步: agent-eval pipeline --package-dir ./travel-package

── 后续修改（多轮会话）─────────────────────────────────
你> 给安全门控再加一条：夜间行程必须含住宿安排
🤖 计划: 修改 rules/safety.yaml (+1 规则 SAF_005, tier=hard_score)
   ── diff ──
   +  - id: SAF_005
   +    name: 夜间住宿安排
   +    evaluator: commonsense.logical_consistency
   ...
? 应用? (Y/n)
```

### 5.4 向导式执行

```text
? 选择场景包
❯ chat@1.0.0            (内置 · 15 任务)
  courseware@1.0.0      (内置)
  travel@0.1.0          (项目包 ./travel-package)

? 选择考卷   default (15 任务)  ❯  regression (8)
? 选择 SUT   sasan-agent@staging  ❯  sasan-agent@prod
? 选择规则集 [chat-default]  ❯  chat-strict
? 执行模式   ❯ pipeline (执行+评估+报告)   ○ run (仅执行)

── 执行摘要 ────────────────────────────────────────────
  包: chat@1.0.0   考卷: default (15)   SUT: sasan-agent@staging
  规则集: chat-default   LLM: text=…, vision=…   预算: ≤ $1.0
  等价命令: agent-eval pipeline --package chat --task-set default \
            --sut-config sasan-agent@staging
? 开始执行? (Y/n)

⠋ 执行中…  ████████████░░░░  9/15 任务
  task-07  ✅ reward 0.82   task-08  ⠋ running   task-09  ⏳
```

### 5.5 结果查看与浏览器直达

```text
$ agent-eval runs

? 选择运行
❯ 20260831_093012  chat×sasan@staging   15 任务  R=0.78  未上传
  20260830_154501  chat×sasan@staging   15 任务  R=0.75  ✅已上传

── 指标 ────────────────────────────────────────────────
  chat:reward 0.78 (阈值 0.75 ✅)   chat:delivery_rate 0.93 (0.95 ❌)
  chat:avg_turns 6.2   chat:avg_tool_calls 3.1   llm_skipped 0
── 失败 Top ────────────────────────────────────────────
  safety.compliance        ×2   (task-03, task-11)
  format.response_format   ×1   (task-07)
? 下一步  ❯查看 task-03 明细   ○打开完整报告   ○上传本次运行
              ○在平台查看 (runs show --web)   ○返回

$ agent-eval open run 20260831_093012
✅ 已打开 https://eval.example.com/o/教研组/projects/课件生成/runs/…
```

### 5.6 模型配置与自检

```text
$ agent-eval models set
? Provider  ❯ deepseek   ○ openai 兼容   ○ anthropic 兼容
? API Base URL [https://api.deepseek.com]:
? 打开 DeepSeek 控制台获取 API Key? (Y/n) y
  ✅ 已打开 https://platform.deepseek.com/api_keys
? API Key: ••••••••••••

$ agent-eval doctor
  平台   ✅ https://eval.example.com (张三@教研组 · 课件生成)
  模型   text ✅ deepseek-chat   vision ✅ kimi-k2.6   agent ⚠️ 回退 text
  凭证   ✅ sasan.username / ❌ sasan.password (缺失)
         → 修复: agent-eval secrets set sasan.password
  包     ✅ 内置 3 · 项目 1 · 本地仓库 0
  环境   ✅ workspace 可写   ✅ [agent] extra 已装   ⚠️ [llm] extra 缺失
```

### 5.7 Jenkins 集成（非交互形态）

```groovy
stage('评测回归') {
  steps {
    sh '''agent-eval pipeline --package chat \
        --task-set regression --sut-config sasan-agent@staging \
        --upload --no-input --output-format json > eval.json'''
  }
  post {
    always { archiveArtifacts artifacts: 'eval.json', fingerprint: true }
    failure  { echo '评测业务失败或门控未达标 (exit 1)' }
  }
}
```

---

## 六、非功能需求

| ID | 需求 |
|----|------|
| NF-C-01 性能 | 向导启动 < 1s；选项切换无感知延迟；Agent 会话流式输出首 token < 3s（网络正常时）；进度视图刷新不撕裂（单行重绘） |
| NF-C-02 安全 | Agent 工具沙盒（包根白名单 + 防逃逸）；凭证不出现在对话、diff、日志中；`.env`/密钥文件权限 0600；浏览器配对码一次性、短时效（≤10 分钟）且仅绑定发起会话；`--trust-agent` 无人确认模式默认关闭 |
| NF-C-03 可靠性 | LLM 不可用时：执行路径不受影响（既有 SKIP 降级），包 Agent 会话明确报错并指引模板路径；浏览器不可用时降级打印 URL；向导异常退出不破坏 workspace 已有产物 |
| NF-C-04 兼容 | macOS / Linux 主流终端全功能；Windows Terminal 基本可用（选择/颜色/中文）；非 TTY（管道/CI）自动降级非交互；`NO_COLOR` 尊重 |
| NF-C-05 可测试 | 交互层与编排层解耦可单测（prompt 序列可注入 mock）；退出码与 `--json` 输出有契约测试；Agent 会话以 mock LLM 回放测试（禁止联网）；浏览器调用可注入 mock（禁止测试中真开浏览器） |
| NF-C-06 可维护 | 向导文案外置（不散落硬编码）；等价命令映射表单点维护；新增工作域不改内核 |

---

## 七、命令与参数规范

### 7.1 新增/变更命令

| 命令 | 关键参数 | 说明 |
|------|---------|------|
| `start` | `--domain <scn\|exec\|runs\|auth>` | 直接进入指定工作域 |
| `auth login` | `--token <key>` `--host <url>` | 交互选通道（浏览器创建 / 粘贴 Key）/ `--token` 直供（CI）；写 `.env`（0600） |
| `auth status` / `auth logout` / `auth register` | `--revoke`（P2）/ `--host` | 身份体检 / 清除本地凭证 / 打开注册页 |
| `models set` | `--role <text\|vision\|agent>` | 交互向导（替代 `models login`） |
| `scenario new` | `--scenario` `--mode template\|agent\|skeleton` `--instruction` `--dir` | 创建项目包 |
| `scenario edit` | `--dir` `--instruction` `--yes` `--trust-agent` | Agent 会话 / 非交互单指令 |
| `scenario show` | `--dir`/`--package` `--section tree\|rules\|tasks\|sut\|manifest` `--file <name>` `--web` | 只读查看 |
| `runs list / show` | `[run_id]` `--json` `--open` `--web` `--compare <a,b>` | 本地结果浏览 |
| `open` | `platform\|run\|report\|scenario\|secrets\|keys\|docs` + 目标参数 | 浏览器直达 |
| `doctor` | `--json` | 顶层一键自检 |

### 7.2 全局参数

`--no-input`（禁一切交互，缺失即错）· `--output-format text\|json` · `--verbose` · `--color/NO_COLOR` · `--workspace-dir`

### 7.3 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 评测业务失败（含门控阈值未达，可用 `--no-fail-on-threshold` 关闭该语义） |
| 2 | 配置 / 输入错误（缺参数、非交互缺输入、包校验失败） |
| 3 | 依赖不可用（LLM / SUT / 平台连接失败） |
| 130 | 用户中断 |

---

## 八、分期规划

| 期 | 内容 | 验收标志 |
|----|------|---------|
| **P0 骨架+命名+执行+结果** | `start` 工作台（导航/上下文）；顶层 `doctor`；`scenario show`；向导式执行；`runs list/show`；`--no-input` / `--json` / 退出码；**命令重命名直接切换**（models login→set、package→scenario，教程/脚本/CI 同步更新） | 新用户 3 分钟内经向导拿到第一份评测报告；旧命令名全仓清零；Jenkins 片段可跑 |
| **P1 账号+Agent 包工程** | `auth login/status/logout`（浏览器配对 + 粘贴 Key）、`auth register`；`models set`（含打开 Provider 控制台）；`scenario new/edit`（计划/diff/校验门禁/会话日志）；secrets 引导；上传向导 | 浏览器配对登录全流程可用；「一句话改包」端到端可用；校验门禁拦截率 100% |
| **P2 增强** | 设备码流免粘贴（需平台配对端点）、`auth logout --revoke`；scenario 版本管理；run 对比；`--trust-agent` 非交互 Agent；包 push 到平台（视开放问题 #2）；TUI 全屏（远期） | 按需评估 |

---

## 九、开放问题

1. **浏览器配对的平台端支持**：P1 的「配对码 + 粘贴确认码」只需平台提供一个轻量授权页（校验登录态后展示/回显确认码）；P2 设备码流需新增 CLI 配对端点（发码/轮询/签发 Key）。平台侧工作量与安全评审需 [09](../arch/09Web可观测平台架构设计.md) 侧确认。
2. **包发布通道**：项目包 → 平台 DB（`importAssetsToDb` 方向的 CLI 化 `scenario push`）是否纳入 P2？涉及平台资产评审流。
3. **Agent 预算与角色**：PackageAgent 与执行 Agent 共用 `agent` 角色与预算上限，还是独立角色/独立配额？（倾向：共用角色、独立会话预算，避免新增配置面）
4. **向导会话持久化**：工作台上下文（活动包/SUT 等）是否跨 `start` 会话记忆（`workspace/.workbench.yaml`）？记忆失效策略？
5. **交互组件选型**：questionary / InquirerPy / 基于 rich 自研 select 的取舍（typer 无原生列表选择），实现阶段技术确认。
6. **Windows 兼容深度**：基本可用（NF-C-04）还是完整支持（影响组件与颜色方案选型）？

---

## 十、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-08-31 | 初稿：向导式工作台（`start` 四工作域）、PackageAgent（DeepAgents 底座 + 沙盒工具面 + diff/校验门禁）、项目包落盘（当前目录，内置包只读）、向导式执行与结果查看、非交互/JSON/退出码集成规范、交互原型与 P0-P2 分期 |
| v1.1 | 2026-08-31 | **命令体系整体 Review 与重规划**：`models login/logout`→`models set/clear`（login 语义留给账号）；`package *`→`scenario *`（消除与 `pack` 名词冲突）；新增 `auth` 域（浏览器配对登录/status/logout/register，无浏览器降级打印 URL）；新增 `open` 与查看类命令 `--web` 浏览器直达；`doctor` 提升为顶层命令；`results`→`runs`；行业参照补充 gh auth login / gcloud / stripe / flutter doctor 范式；需求条目重编为 F-C-NAV/AUTH/CONFIG/SCN/EXEC/RUNS/OPEN/INTEG |
| v1.2 | 2026-08-31 | **取消向下兼容**（用户基数小，决策）：重命名一次性直接切换，移除别名层、弃用警告与 `--strict-deprecation` 机制；旧命令名随版本清除，教程/示例脚本/CI 片段与全仓引用同步更新（§3.3、F-C-CONFIG-04、P6、P0 验收同步修订） |
| v1.3 | 2026-09-01 | **F-C-AUTH 落地同步（Sprint 11）**：`auth login/status/logout/register` 四命令 + 工作台账号域「平台账号」子向导；身份探测走平台新增 `GET /api/public/whoami`（旧平台 404 回退 `/api/public/secrets` 轻探测）；浏览器通道降级打开 `/login` 引导（前端暂无独立 Keys 页与 `/cli-auth`，B 通道与设备码流仍为 P2）；参数表按实际形态修订 |
