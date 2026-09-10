# CLI 交互式评测工作台设计

> 本文档是 [04 CLI 交互式评测工作台需求](../requirement/04CLI交互式评测工作台需求.md) 的架构落地：向导式工作台（`start`）、命令体系重构（直接切换）、账号与浏览器联动（`auth` / `open`）、工作台 Agent（WorkbenchAgent）、结果浏览（`runs`）。
>
> 定位为 **CLI 表现层 + 交互编排层** 设计：与 [02 编排调度层设计](./02编排调度层设计.md) 共用既有编排阶段（`cli/_stages.py`）；Agent 底座复用 [03 执行引擎设计](./03执行引擎设计.md) §3.2；配置面遵循 [06 数据管理与配置规范](./06数据管理与配置规范.md) §四；场景包规范遵循 [13 配置管理设计](./13配置管理设计.md)；平台账号对接 [09 Web 可观测平台架构设计](./09Web可观测平台架构设计.md)。

---

## 一、设计目标与范围

### 1.1 设计目标

| 需求目标 | 设计要点 |
|---------|---------|
| G1 全生命周期闭环 | 工作台四域（场景包/执行/结果/账号配置）统一入口；全部动作下沉到既有编排与内核 |
| G2 场景包 Agent 化 | 工作台 Agent（WorkbenchAgent）复用 DeepAgents 底座 + 按域装配的工具面 + 校验门禁（§六）；场景包工程为首个域，会话机与组织方式见 §6.6/§6.7 |
| G3 零门槛交互 | 向导原语库（选择/确认/输入）+ preflight 引导链 + 等价命令显示（§三） |
| G4 脚本/CI 友好 | 非 TTY 降级、`--no-input`、`--output-format json`、退出码集中映射（§4.3） |
| G5 单一事实源不变 | 配置仍落 llm.json / sut_credentials.json / platform.json（密钥区三文件）+ .env（开关与直供）；包结构仍走 13 规范 |
| G6 命名语义清晰 | `models set/clear`（配置语义）、`scenario *`（场景包）、`auth *`（平台账号）、顶层 `doctor`（§4.2） |

### 1.2 范围

- **含**：向导框架（workbench）、命令体系（`cmds/` + `console/`）、auth 平台账号与 `open` 的 CLI 侧实现、工作台 Agent（会话机/工具面/门禁/日志）、`scenario show` 与 `runs` 的本地数据读取、退出码与 JSON 输出规范、平台侧配对端点的**接口约定**。
- **不含**：平台侧 `/cli-auth` 授权页的实现（09 侧落地，本文仅约定交互流程，见 §5.1）；评测内核与指标逻辑变更；全屏 TUI（远期）；`scenario push`（包发布通道）。

---

## 二、总体架构

### 2.1 分层架构

```
┌───────────────────────────────────────────────────────────────┐
│ 表现层                                                          │
│   agent-eval start     →  WorkbenchSession（向导域循环）         │
│   agent-eval <cmd>     →  typer 命令（参数形态）                  │
│        共用向导原语 prompts.py（select/confirm/input + 降级）      │
├───────────────────────────────────────────────────────────────┤
│ 交互编排层（新增，薄层）                                          │
│   workbench/domains/（scn/exec/runs/account 四域动作）            │
│   console/：prompts（原语+降级）/ render（富渲染）                │
│             output（JSON 分流 + 退出码映射）/ equiv（等价命令）    │
├───────────────────────────────────────────────────────────────┤
│ 既有编排层（零改动复用）                                          │
│   cli/_stages.py：resolve_run_inputs / execute_stage /          │
│   evaluate_stage / finalize_eval / write_run_manifest           │
├───────────────────────────────────────────────────────────────┤
│ 既有内核                                                         │
│   PackageManager / ConfigLoader / PipelineEngine /             │
│   ExecutionAgent / ResultSink / upload                          │
└───────────────────────────────────────────────────────────────┘
        ▲ 工具面（沙盒：仅限包根目录）
   WorkbenchAgent（DeepAgents，独立于执行侧 SUT 通道）
```

### 2.2 模块布局

CLI 目录按「**装配单点 / 命令薄壳 / 表现层基础设施 / 向导层**」四区组织，子命令组统一收入 `cmds/`，交互基础设施统一收入 `console/`：

```
agent_eval/cli/
├── __init__.py        # 唯一装配点：顶层命令 app.command()() + 子命令组 add_typer
├── main.py            # 引导（dotenv/评估器注册/app/全局 callback）+ 轻量命令
│                      #   version/start/open/doctor
├── _stages.py         # 编排阶段（既有：解析/执行/评估/收尾；零交互，向导复用）
├── _common.py         # 跨组共享工具：LLM Judge 初始化 / 摘要 / 推送 / 凭证保障
│
├── console/           # 表现层基础设施（无业务语义，命令层与向导层双向复用）
│   ├── prompts.py     # 向导原语：select/confirm/ask/resolve_bypass + --no-input 旁路
│   ├── render.py      # rich 渲染：stage_progress（阶段级进度，stderr 绑定）/ 任务状态表
│   ├── agent_stream.py # Agent 流式事件渲染（✻ 思考 / 🤖 正文 / 🔧 工具行）
│   ├── output.py      # --output-format json 与 stderr 分流 + map_exit_code() 退出码集中映射
│   └── equiv.py       # 等价命令 argv 构造（单点映射表）
│
├── workbench/         # 向导工作台（start 入口专用）
│   ├── session.py     # WorkbenchSession：上下文 / 导航栈 / preflight
│   └── domains/       # 四域动作（调用 cmds 暴露的纯函数，不经过 typer）
│       ├── scn.py / exec.py / runs.py / account.py
│
└── cmds/              # 命令模块（顶层与子命令组同构：typer 绑定 + 纯函数动作）
    ├── pack.py        # 顶层 pack 绑定 + execute_pack + 内容指纹
    ├── evaluate.py    # 顶层 eval 绑定 + execute_eval + _detect_run_mode
    ├── execute.py     # 顶层 run/pipeline 绑定 + execute_run / execute_pipeline
    ├── upload.py      # 顶层 upload 绑定 + upload_run（回填动作）
    ├── scenario.py    # new/edit/show/validate/list/pull（new/edit 含 --mode agent）
    ├── workbench_agent.py # Agent REPL 宿主（流式渲染 / ask 桥 / 中断提示 / 落盘归位）
    ├── models.py      # set/list/test/clear
    ├── runs.py        # list/show（无参交互选择）
    ├── open_url.py    # open <target>（平台 URL 构造 + webbrowser 单出口）
    ├── doctor.py      # doctor（检查项编排）
    ├── auth.py        # login/status/logout/register
    └── secrets.py / suite.py / dataset.py / knowledge.py / rule_set.py   # 既有迁入

agent_eval/agent/
├── core/              # 共享内核：tools 基座 / budget / session_log / callbacks / model_bridge / session
├── executor/          # 评估执行域：agent（ExecutionAgent）+ sut_tools + protocol_tools
├── workbench/         # 评测工作台域：agent 会话机（§6.1/§6.6）+ tools 暂存沙盒（§6.2）+ sut_probe 探测面（§6.5）
└── assets/configs/workbench_agent_prompts.yaml # 提示词资产：base + domain_segments 分段装配（§6.7/§6.8）
```

**组织约定**（可维护性与扩展性的落点）：

1. **装配单点**：`__init__.py` 是唯一注册处（子命令组 `add_typer` + 顶层命令 `app.command()()`）——新增命令 = `cmds/` 新模块（绑定 + 纯函数动作）+ 一行注册，`main.py` 与其他模块零改动。
2. **命令薄壳**：typer 回调（`main.py` 与 `cmds/*`）只做参数绑定与结果输出；业务逻辑一律下沉为 `_stages` 阶段函数或组内导出的**纯函数动作**（无 typer 依赖）。
3. **双前端同构**：workbench 域动作与命令行调用**同一个纯函数动作**（D-CLI-1 的落地形态）；等价命令显示由 `console/equiv.py` 从同一参数对象组装，天然不漂移。
4. **依赖方向单向**：`cmds → (_stages / console / _common / 内核)`；`workbench → (console + cmds 纯函数)`；`console` 不依赖任何业务模块；**禁止命令组之间横向 import**（跨组复用上提到 `_common`/`console`/`_stages`）。
5. **交互与业务分离**：`_stages` 与组内动作零交互原语调用，所有人机 IO 收口 `console/prompts.py`（非 TTY 降级因此单点生效）。
6. **粒度守恒**：组内超过 ~300 行或出现多类职责时拆子模块（同目录 `_helper.py`），不提前建深目录。

### 2.3 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| D-CLI-1 | **双前端同内核**：向导动作最终组装与命令行相同的参数对象，直接调 `_stages` 阶段函数；向导内不出现第二份业务逻辑 | 一份业务逻辑两处复用；等价命令显示天然成立（argv 即真相） |
| D-CLI-2 | **交互原语收口 `console/prompts.py`：以编号选择落地（gcloud 同款，零新依赖）；questionary 键盘导航为可选升级**（分页/搜索需求出现时） | 零依赖先行 + 升级路径保留；原语签名不变，替换不动调用方 |
| D-CLI-3 | **包域独立工具面**（`workbench/tools.py`），不复用执行侧 SUT 通道 | 两域工具语义无关（文件编辑 vs SUT 交互）；沙盒约束不同（会话根 vs workspace） |
| D-CLI-4 | **平台身份落密钥区 `~/.agent_eval/platform.json`**（host/api_key/project，0600），CLI 启动注入 env **仅补缺**——env 直供（CI/云函数/executor/`.env`）优先；`.env` 归用户手工管理，残留旧值检测提示不代删 | 三域三文件与 `models`（llm.json）/`secrets`（sut_credentials.json）对齐（06 §4.7）；「登录 A 实际上报 B」的静默错乱由 env 优先 + 提示兜底 |
| D-CLI-5 | **浏览器打开统一走 `cmds/open_url.py`**：`webbrowser.open`（`$BROWSER` 可指定浏览器）+ 无浏览器环境（SSH/未设 `$BROWSER`）降级打印 URL | gh `pkg/browser` 同款行为；单一出口便于 mock 测试（NF-C-05） |
| D-CLI-6 | **命令命名不设兼容层**：`scenario` / `models set|clear` 等新命名直接生效，无旧名别名 | 名字即语义（场景包 ≠ 打包执行包；配置模型 ≠ 登录模型），别名层只会延续误用 |
| D-CLI-7 | **退出码集中映射**：`console/output.py::map_exit_code(exc)` 单点适配异常体系 → 0/1/2/3/130 | 契约可测试；新增异常不改命令层 |
| D-CLI-8 | **`runs` 读本地索引优先**：`workspace/index/runs_index.json`（06 §3.8）列表，run 目录直读详情；平台态经 manifest 上传标记推断 | 零新存储；与 Web 平台解耦 |

### 2.4 复用清单（不重造边界）

| 工作台能力 | 复用既有实现 |
|-----------|-------------|
| 平台账号 | `auth login/status/logout/register`（`cmds/auth.py` 纯函数动作 + `auth_wizard` 子向导：登录/状态/退出/注册；身份探测 `GET /api/public/whoami`；写密钥区 platform.json（0600，`apply_platform_env` 启动注入 env 仅补缺）；登录后 `session._refresh()` 刷新平台态） |
| 模型配置向导 | `models set`（原 login 逻辑，改触发词与文案） |
| SUT 凭证 | `secrets set`（工作台「账号与配置 → SUT 凭证」为交互子向导 `secrets_wizard`：查看表 / 录入-更新（ref 从已录键与场景包 sut_configs 的 credential_ref 数据发现、字段名自由输入、值隐藏输入）/ 删除；与命令行同读写 `~/.agent_eval/sut_credentials.json`；执行前缺失由 `ensure_sut_credentials` 自动引导补录，见 §7.2） |
| 执行 | `run/pipeline/eval` + `_stages.py` 五阶段 |
| 包校验 | `package validate` 既有 Schema + 语义校验（改名后为 `scenario validate`） |
| 包发现/解析 | `PackageManager`（内置/项目/本地仓库三源） |
| Agent 底座 | `create_deep_agent` / `build_chat_model` / BudgetGuard / tool_guard 范式（03 §3.2） |
| 上报 | `upload` + ResultSink |

---

## 三、工作台向导框架

### 3.1 WorkbenchSession

```python
@dataclass
class WorkbenchContext:
    platform: PlatformStatus | None   # auth status 缓存（host/用户/项目/Key 有效性）
    models_ok: dict[str, bool]        # 三角色连通态
    active_package: PackageRef | None # 当前包（scenario/版本/来源）
    active_task_set: str | None
    active_sut: str | None

class WorkbenchSession:
    """向导会话：上下文 + 域导航栈 + preflight 引导。"""
    def run(self, domain: str | None = None) -> None: ...
    def preflight(self) -> list[Guidance]   # 依上下文生成引导项（未登录→auth 等）
```

- 域循环：主菜单 → 域菜单 → 动作 →（执行/反馈）→ 返回域菜单；ESC 逐级返回，Ctrl-C 优雅退出（清理临时态，不影响 workspace 已落盘产物）。
- 上下文跨域保持（F-C-NAV-03）：执行域选定的包/考卷/SUT 供结果域与包域复用。

### 3.2 向导原语与非 TTY 降级

| 原语 | TTY 行为 | 非 TTY 行为 |
|------|---------|------------|
| `select(options)` | 编号列表 + 回车（可选升级 ↑↓ 键盘导航） | `--no-input` 下 env/default 旁路，缺失 → exit 2；管道输入正常提示 |
| `confirm(q)` | y/n | 读 `--yes`/env，缺省即错 |
| `input(hide=)` | 文本（可隐藏回显） | 读参数/env，缺省即错 |
| `stage_progress` | 阶段级 spinner（stderr 绑定，transient）| 单行阶段提示到 stderr；--json 下禁用 |
| `print_task_table` | 完成态逐任务状态表（进度视图回落摘要） | 正常输出（rprint） |

全部原语收口 `console/prompts.py`，签名统一带 `default`/`env_key` 旁路参数，测试经依赖注入 mock。

### 3.3 preflight 引导链

进入工作台与各域动作前按序检查，产出 `Guidance(label, fix_action)` 列表渲染为菜单项：

```
平台未登录 → auth login ／ 模型未配置 → models set ／
SUT 凭证缺失 → secrets set <ref>.<field> ／ 无项目包 → scenario new 或选内置包
```

### 3.4 等价命令显示

`console/equiv.py` 维护「动作 → argv 构造器」映射表；向导确认页渲染 `等价命令: agent-eval pipeline --package chat ...`。argv 由向导已收集的参数组装而成——与实际执行的参数对象同源（D-CLI-1），不会漂移。

### 3.5 主菜单：工作台 Agent 一级入口

Agent 是工作台的首选工作方式——不是某个域里的一个动作，因此主菜单首项即对话式 Agent：

```
选择工作域
  1. 工作台 Agent（对话式·推荐）   ← 一级入口：自然语言下需求，跨域任务
  2. 场景包管理
  3. 执行评测
  4. 查看结果
  5. 账号与配置
  6. 退出
```

- **一级入口 = 通用档位**：进入 WorkbenchAgent REPL（自我介绍横幅见 §6.8 + 会话循环），
  能力域如实标注当前装配范围（场景包工程 + SUT 接入调试）。`start --domain agent`
  提供等价直达（与 `--domain auth` 别名惯例一致）。
  **直入对话，无前置菜单**：进入即横幅介绍能力与示例，随后直接 REPL——「新建 /
  改已有包 / 排查」都是会话里的一句话，不由菜单分流（对标 claude：打开即对话，
  能力介绍先行）。默认任务对象 = 新包草稿（`workspace/.staging`，会话后按清单 id
  归位 `cwd/<id>-package/`，空会话退出清理草稿，见 §6.3）；改已有项目包由 Agent 经
  `read_file` 读入现有内容后在草稿中改造（prompts 域段「改造已有项目包」规约），
  `scenario new/edit --mode agent` 命令与域内快捷方式保留为显式直达。
- **域内入口 = 档位快捷方式**：场景包域两项标签为「用 Agent 创建场景包」「用 Agent
  修改选中的包」——语义是「预载对象上下文的快捷方式」（改包先经 `select_editable_ref`
  选定，选中对象注入首条上下文；对标在仓库目录里启动 claude，cwd 即上下文）。
  快捷方式进入的会话显示同一横幅（档位=包域，示例文案为包域档）。
- **preflight 差异**：Agent 入口前置检查 LLM 配置，未配置 → 指引 `models set` 并阻断进入
  （无模型 Agent 不可用，与首屏「只提示不阻断」的查看类检查语义不同）。

---

## 四、命令体系

### 4.1 typer 应用结构

```python
# cli/__init__.py —— 唯一装配点
from agent_eval.cli.cmds import (auth_app, dataset_app, knowledge_app, models_app,
                                 rule_app, runs_app, scenario_app, secrets_app, suite_app)
app.add_typer(scenario_app)   # new/edit/show/validate/list/pull
app.add_typer(models_app)     # set/list/test/clear
app.add_typer(auth_app)       # login/status/logout/register
app.add_typer(runs_app)       # list/show
app.add_typer(secrets_app); app.add_typer(suite_app); app.add_typer(rule_app)
app.add_typer(dataset_app);  app.add_typer(knowledge_app)
# cli/main.py 顶层：eval/run/pipeline/pack/upload/version + start/open/doctor
```

### 4.2 命令命名与语义

| 命令 | 语义 | 说明 |
|------|------|------|
| `scenario new/edit/show/validate/list/pull` | 场景包全生命周期 | 组名取「场景包」而非「包」——消除与顶层 `pack`（打包执行包）的名词冲突；`init` 并入 `new --mode skeleton` |
| `models set/list/test/clear` | 三角色 LLM 配置 | 动词取「配置」语义（set/clear）而非 login/logout——配置的是凭据与端点，不是登录一个远端会话 |
| `auth login/status/logout/register` | 平台账号 | 与 `models` 严格区分：auth 面向 Web 平台身份，models 面向 LLM 网关 |
| `runs list/show` | 本地结果浏览 | 读 workspace 本地索引与 run 目录（§7.2） |
| 顶层 `doctor` | 自检 | 仿 `flutter doctor` / `npm doctor`：环境与配置体检 |

### 4.3 全局参数与退出码

```python
def map_exit_code(exc: BaseException) -> int:
    # 0 成功；1 评测业务失败（含门控未达，--no-fail-on-threshold 关闭该语义）
    # 2 ConfigError / InputError / 包校验失败
    # 3 SUTChannelError / AgentProtocolError / LLMUnavailable / 平台连接失败
    # 130 用户中断（typer.Abort / KeyboardInterrupt）
```

- `--no-input`：全局回调注入，向导原语进入非 TTY 语义。
- `--output-format json`：stdout 仅 JSON 文档（run_id/指标/失败明细/制品路径），人读进度走 stderr；对 `run/pipeline/eval/runs/doctor` 生效。
- 契约测试：退出码 × 异常矩阵、JSON 输出 Schema 快照。

---

## 五、账号与浏览器联动

### 5.1 `auth login` 流程（双通道）

```
CLI                                          平台
 │ ① 选通道：A 打开 Keys 页 / B /cli-auth 授权页
 │
 │ 通道 A（零平台改动）:
 │   open_url.open("{host}/settings/keys") ──→ 用户登录并创建 Key
 │   input(hide=True) ←──────────────────── 用户粘贴 Key
 │
 │ 通道 B（平台新增一个前端页，复用既有登录态 + 建 Key API）:
 │   code =随机配对码(8位, 一次性, ≤10min)
 │   open_url.open("{host}/cli-auth") ──────→ 用户登录，输入配对码
 │                                           页面经既有 POST /api/v1/keys
 │                                           创建 Key（name=cli-{code}）并展示
 │   input(hide=True) ←──────────────────── 用户粘贴新 Key
 │
 │ ② Key 有效性探测：既有 Bearer 端点轻量调用（如 GET /api/v1/jobs?limit=1）
 │ ③ 解析身份（团队/项目）→ 写密钥区 platform.json（0600，env 直供优先）
 │ ④ 回执：用户@团队 · 项目 · Key 掩码
```

- 通道 A/B 共用 ②③④；差异只在 Key 的获取方式。`auth login --token <key>`（或 env）为 CI 无浏览器形态。
- `auth status`：读密钥区 platform.json（env 补缺）→ 平台 ping → 身份回显；`auth logout`：删除密钥区 platform.json 与进程 env（`--revoke` 吊销平台侧 Key 需平台删除端点授权，暂仅提示）；`.env` 归用户手工管理，检测到残留平台配置仅提示不代删（env 优先会覆盖密钥区）。

> **落地形态**：身份探测端点为 `GET /api/public/whoami`（Bearer API Key，返回 `{kind, key:{name,scopes}, project:{id,name,slug}, org:{id,name,slug}}`）；前端暂无独立 Keys 页与 `/cli-auth` 授权页：通道 A 打开 `{host}/login` 并引导至项目「设置 & API Key」页创建 Key，通道 B 待平台侧落地。CLI 对 404（旧平台无 whoami）回退 `GET /api/public/secrets` 轻探测——Key 有效但身份未知，回执降级不阻断登录。身份持久化于 `~/.agent_eval/platform.json`（0600，`AGENT_EVAL_PLATFORM_CONFIG` 可覆盖），CLI 启动 `apply_platform_env` 注入进程 env **仅补缺**（CI/云函数/executor env 直供与 `.env` 显式配置优先）；`.env` 归用户手工管理，登录/登出检测到残留平台配置即提示（env 优先将覆盖密钥区），不代为删改。

### 5.2 `open <target>` 与 `--web`

| target | URL 模板（host 取 `.env` `AGENT_EVAL_HOST`） |
|--------|----------------------------------------------|
| `platform` | `/`（项目看板） |
| `run <run_id>` | `/projects/{project}/runs/{run_id}`（平台侧无对应 run 时降级 `report`） |
| `report <run_id>` | 本地 `workspace/runs/{id}/reports/summary.md`（系统默认程序打开，非浏览器限定） |
| `scenario <ref>` | `/projects/{project}/assets/scenario/{ref}` |
| `secrets` / `keys` / `docs` | 对应平台设置页 / 文档站 |

- 查看类命令 `--web` 等价 `open` 对应目标；未登录时提示 `auth login`。
- 全部打开动作经 `cmds/open_url.py` 单出口（D-CLI-5），测试 mock。

---

## 六、工作台 Agent（WorkbenchAgent）

> 定位对标 Claude Code：**一个通用会话机 + 按域装配的工具面（profile）+ 统一红线策略**。
> 场景包工程是首个域——域 = 工具面 + 提示词段 + 门禁策略（档位注入），新域零改会话机（§6.7）；
> 会话机的失控防线（§6.6）全域受益。

### 6.1 会话机组装

```python
agent = WorkbenchAgent(
    pkg_root,                                   # 任务对象：包根或新包草稿目录
    config=WorkbenchAgentConfig(...),           # tunables 单点（§6.9）
    domain="scenario_package",                  # 域档位：选择提示词段
    ask_fn=ask_fn,                              # CLI 交互桥（ask/select/隐藏输入）
)
```

装配要点（`agent/workbench/agent.py`）：

- **模型**：`build_chat_model(llm_role="agent")`（回退 text）；底座 `create_deep_agent`（03 §3.2 同源）。
- **双工具面**：`PackageToolServer`（文件沙盒，§6.2）+ `SUTProbeToolServer`（受控网络探测，§6.5）
  并列挂载，`_describe_tools` 汇总注入系统提示词；`ask_fn` 同时桥接两面交互。
- **提示词分段装配**：`system_prompt_base`（会话机段，零域语义）+ `domain_segments.<域>` 拼接，
  统一字面 replace 渲染 `{domain}/{tools}/{pkg_root}/{assets_root}`；未装配域抛 `AgentError`。
- **预算与检查点**：`BudgetGuard` 会话级 token/成本预算（跨段/跨轮累计，`None` 不启用）；
  `MemorySaver` 内存检查点仅作事故现场保存器（§6.6 salvage），成功路径保持「宿主持有消息重放」。
- **tool_guard 范式**：工具异常转 `{"error": ...}` 结果交 Agent 决策，不中断图。

**会话记忆（跨进程续作）**：对话要点（≤40 条）持久化 `workspace/agent_sessions/<root 路径摘要>.json`
——同一包目录命中同一记录文件，续作时注入此前记录（≤24 条、单条 400 字截断）并附「勿重复
追问已给信息」指引，CLI 显示「已续接 N 条对话」。

**流式直播**：`astream` 事件流（`thinking`/`token`/`tool_start`/`tool_end`/`phase`/`tool_args`）
实时回调，`console/agent_stream.py` 按 Claude Code 式渲染；大文件内容在 tool_call args 里
增量生成（不走 text 流），`tool_args` 事件以单行进度显示——否则数十秒无输出形同卡住。

### 6.2 工具面与沙盒（PackageToolServer）

| 工具 | 实现要点 |
|------|---------|
| `list_files` / `read_file` | **分级授权读取**（Claude Code 式）：会话根内（暂存视图优先，含 added/staged/deleted 标记）→ 随包资源 `assets/`（自动授权只读，如包结构规范 guide）→ 外部路径经 `ask_fn` 向用户申请（拒绝即拉黑）；read 截断长文件（防上下文爆炸） |
| `write_file` / `delete_file` | **先写暂存区**（staging dict），不直接落盘——diff 确认与校验门禁通过后才由宿主提交（§6.3） |
| `read_manifest` / `update_manifest` | `agent_eval.yaml` 读写同样走暂存（update 为浅合并） |
| `validate_package` | 对暂存视图执行清单合法 + 资源目录 + 规则 YAML 可解析校验（含对账门禁族，§6.3），返回结构化 errors |
| `search_reference` | 按文件名检索内置包（courseware/chat/code），返回命中文件与各包真实文件清单 |
| `read_reference` | 只读内置包文件内容（ref + 包内 path）——Agent 参照真实格式的**合法通道**（`read_file` 对包外路径受分级授权约束，防反复试探） |
| `list_evaluators` | 当前可用评估器注册 ID 的注册表实时快照（含本包 entry_points 声明）——rules 的 `evaluator` 字段从此清单**原样复制，勿凭记忆臆造**（copy, don't recall：示范强于指令） |
| `preview_diff` | 暂存区 vs 磁盘原文的统一 diff（宿主确认界面同源） |

**沙盒规则（读写不对称）**：**读**分级授权（会话根 → assets → 用户授权的外部路径；
凭证类路径——密钥区 / sut_sessions / `.env`——**先于授权逻辑硬拒**，凭证不回流 LLM
上下文）；**写**不泛化：write/delete 硬沙盒 confined 会话根，路径 `resolve()` 后必须
`is_relative_to(pkg_root.resolve())`（防 `..` 与 symlink 逃逸），扩展名白名单
`.yaml/.yml/.json/.md`；无 shell、无网络、无包外路径。

### 6.3 会话状态机与落盘门禁

```
用户需求 → [计划] Agent 输出改动计划（文件清单+意图）→ 用户确认
        → [生成] Agent 调工具写暂存区 → preview_diff 展示
        → [确认] 全部应用 / 放弃（放弃=清空暂存，磁盘未动；唯一回滚触发器）
        → [门禁] validate_package(暂存快照) + 门禁族（下表）
             ├─ 通过 → 宿主提交暂存到磁盘（原子替换）→ 记录会话日志
             └─ 失败 → errors 注入 Agent 自修复（≤max_fix_rounds 轮）→ 仍失败交还用户
```

关键不变量：**磁盘上的包在任何时刻都只见过「用户确认 + 校验通过」的内容**。

**落盘与归位**：场景包是源资产（用户要编辑、可团队共享），与 `workspace/` 运行产物区归属
不同——会话在 `workspace/.staging/agent-eval-pkg-<rand>/` 草稿区进行，结束后按**最终清单 id**
归位 **`cwd/<id>-package/`**（同卷原子归位，与 skeleton 模式 `./<id>/` 方向一致；给了 REF 则
直接定址）。配套语义：

- **中断 ≠ 放弃**：异常退出不清理草稿，提示 `--output <草稿路径>` 续作；显式指定路径非空
  放行（续作），默认路径仍要求空目录。
- **归位时序**：成果完整的「中断」照常归位交付；「保留现场」只适用于半途。
- **归位冲突报错保留草稿**：目标已存在或清单未落盘 → `Exit(1)` 交用户处置。
- **git 视野**：仓库 `.gitignore` 收 `/*-package/`（实验态默认忽略）；工具不改用户
  `.gitignore`，仅收尾提示。

**生成即发现**：`PackageStore` 第三来源 **project**——项目根（默认 cwd，
`AGENT_EVAL_PROJECT_DIR` 覆盖）与 `workspace/scenario-packages/` 双根一级子目录扫描
（含 `agent_eval.yaml` 即项目包；仅扫一层防重复发现）。`PackageManager.list/find` 单点
打通：工作台执行域与 `scenario show/edit`、`eval/run/pipeline --package` 全部直达刚生成的包。

**落盘门禁族**（staging 校验与 `scenario validate` 双端接线；全部机械对账，打回信息
携带可照抄的权威内容）：

| 门禁 | 校验内容 | 防的事故 |
|------|---------|---------|
| 清单与结构 | `agent_eval.yaml` 合法 + 资源目录 + `rules/`、`prompts/` 各含 ≥1 个 `.yaml`（加载器只认 `.yaml`，README 式提示词会静默失效 `prompts=0`） | 提示词写成 `.md` 后静默无判官 |
| 规则引用对账（`evaluation/rule_refs.py`） | 四类引用可解析：evaluator 注册态 / prompt_id / dimension / stage；注册表快照经 `load_package_entry_points` **运行时同源装载**（少装包会把「清单已声明、运行时可用」的 ID 误判未注册） | guide 示例把 method 枚举值写进 `evaluator` 字段被照抄 → 运行时规则全跳过仍产出全 0 报告 |
| 判官模板变量契约 | `user_prompt_template` 只能用所引评估器实际注入的变量——评估器以类级 `prompt_variables` 声明契约（渐进声明：未声明的不参与对账）；jinja2 `meta.find_undeclared_variables` 对账，越界随可用清单打回 | `{{ response }}` vs `content` 注入集错位 → StrictUndefined 渲染失败 → 规则全 0 分 |
| SUT 未知键拒绝（`registry.validate_sut_config_document`） | 以执行器模型 `model_fields` 为白名单（运行时 `extra="allow"` 前向兼容意味着发明字段被**静默丢弃**），并复用 `SUTSystemConfig` 校验必填/枚举/`${VAR}` 展开 | 自造 `login.base_url` 字段被静默丢弃 → 执行时拼回页面域 404 |
| 通道排期校验（v4.7.3 起） | `channel` ∈ `SCHEDULED_CHANNELS`（`agent_protocol`/`generic_http`，与执行工厂同源单点）；预留通道（如 `browser`）落盘即打回，错误文案自带「探测受挫不是换通道的理由……**不得静默降级改写落盘**」行动指引；generic_http 免协议端点对账（无协议语义），登录对账照走 | 协议探测受挫后 Agent 静默降级写预留通道 → 落盘成功、答完 5 个交互到执行工厂才报「预留未排期」 |

引擎侧配套守卫：评估器**尝试创建且全部失败即中止**（部分失败跳过语义保留）——防
「垃圾报告静默产出」。

### 6.4 安全红线实现

- sut_config 内容扫描：出现 `password/token/api_key` 值字段且非 `credential_ref` 引用 → 拒绝写入并提示 `secrets set`（启发式 + System Prompt 双保险）。
- `scenario new/edit --instruction ... --yes --trust-agent`：非交互模式必须双重显式旗标；默认关闭。
- 会话日志 `workspace/agent_logs/workbench_agent_<ts>.jsonl`：消息、工具调用与参数（凭证字段脱敏）、token、耗时；SUT 探测证据随会话日志同文件落盘（时间线完整）。
- 传输层日志降噪：httpx/httpcore/openai/anthropic 的 INFO 级「HTTP Request: …」在非 DEBUG 模式压到 WARNING（`core/logging.py` 单点）——root 日志是进程级全局态，工作台里执行域先跑过一次评测，噪声就会混进之后所有 Agent 流式直播会话；`--verbose`（DEBUG）诊断模式全量放行。
- 执行面工具按需装配（v4.8，执行域）：`SUTToolServer` 默认仅导出通用工具白名单（`DEFAULT_EXECUTION_TOOLS`），`invoke_http_sut`/`invoke_cli_sut` **退出 LLM 工具面**（`enabled_tools` 显式恢复，方法保留供服务端直调）——实测语义工具受挫后 LLM 借任意 shell `cat` 凭证与 `.env`，prompts 禁令打不过工具可用性，结构性裁剪才有效；配套 `read_file`/`scan_directory`/`list_files` 限 workspace 子树与任务目录模式路径（`extra_allowed_roots` 逐任务机械注入，不由 LLM 运行时决定）。
- generic_http 模板变量审计（v4.8，落盘门禁）：request_template 全部模板叶子的 Jinja2 未声明变量并集必须**含 `input`**（测试指令未进模板 = 从未发送给被测系统，content-safety 假成功事故的机械判定），且 ⊆ {`input`, `metadata`, 前序步骤名}（拼错变量名/前向引用落盘前打回）；staging 门禁与 CLI `scenario validate` 同源生效（arch/03 §4.2）。

### 6.5 SUT 接入调试

> 动机：用户只知道「带登录框的页面地址」，不知道登录 API 域与字段名（也不知道登录域可与
> API 域分离）；纯文件沙盒生成的 sut_configs 等于盲配，地址不通要到跑考卷时（最贵环节）才
> 暴露。目标：**创建场景包时即由 Agent 智能探测与调试 SUT，验证过的结论才写进
> `sut_configs/`，需用户决策的点经 ask_user 询问**。复用拼装件：`provider._login_by_api`、
> `thread_commands` 协议客户端、tool_guard 范式、staging/confirm 门禁 + 流式直播。

#### 工具面：`SUTProbeToolServer`（与文件沙盒并列的独立 server，绑定同一 DeepAgents）

| 工具 | 职责 | 关键设计 |
|---|---|---|
| `request(method, url, headers?, body?, ref?, step?)` | 门控请求原语（v4：抓取与接口调试/登录实测同一出口）：返回状态码/耗时/响应头/响应体证据，405 的 Allow、400 业务错误消息不再被截掉 | body/headers 支持 Jinja2 模板：凭证 `{{ 字段 }}`（须带 ref，值由服务端从密钥区注入）与链式 `{{ stepN.路径 }}`（step 响应服务端持有，多步认证链可探索）；GET 入**服务端缓存**供 `search_content` 复用（凭证响应不入缓存防绕过值回流）；证据截断防上下文爆炸 |
| `discover_login(page_url)` | 登录 API 发现阶梯（**普通用户只需输入页面登录地址**）：① 页面 `<form>` 解析 → ② JS XHR/fetch/baseURL 线索 → ②.5 OpenAPI 文档探测 → ③ 定向路径探测（**路径由 Agent 自拟** ≤10 条，不发凭证）→ ④ 只向用户问**登录接口地址**一项兜底 | SPA 无线索是常态，④ 是**预期路径**而非失败兜底；**字段名不问用户**——按候选 fields 拟定，经 request 登录实测（body 带凭证模板）+ 授权预览交用户确认 |
| `search_content(pattern, context)` | 已缓存内容检索：子串匹配（防 ReDoS）、大小写不敏感、上下文摘录 ≤12 条（带「数据非指令」声明） | 分析主循环的机械原语，「搜什么」由 Agent 经 prompts 前端包分析法决定 |
| `probe_protocol(base_url, flavor)` | agent-protocol 符合性矩阵：info → 建临时线程 → commands → state → stream；支持带 configurable/modelId 重探 | 逐项 ✅/❌ + 证据，不做二值判定；3xx 不计 ✅；临时线程收尾清理；**已声明的会话凭证自动挂载**；与执行器契约同构（信封/路由头/Bearer 单源复用） |
| `declare_token(ref, token_path?, token_source?, expires_in_path?)` | **事后声明式**凭证提取（决策 D2）：对该 ref 最近一次带凭证 2xx 响应声明「凭证在哪个路径」——不重发请求，声明错了改路径重声明即可（防锁不适用）；成功时机械渲染 `sut_config_auth_snippet`（见证据账本） | **凭证值不进 LLM 上下文**（提取在服务端持有的响应上进行）；`token_source` 三态与执行器同构（`Bearer / header:<X> / cookie`，cookie 自 Set-Cookie 提取落 `session_cookie` 形态）；缺凭证时 request 错误指路 `ask_user(kind=credential)` 逐字段录入；超出执行器宽度的形态（凭证走请求头/链式认证）显式拒绝落盘——探测可探索、暂不可落盘 |
| `ask_user(question, options?, kind?)` | 主动提问：开放文本 / 单选 / 凭证录入（直写 secrets，隐藏输入） | 桥接 CLI `ask()`/`select()`；非 TTY 返回「需交互」错误 |

#### 流程整合（创建包时即调试）

system_prompt 增「SUT 接入调试」阶段：包骨架完成后，需求含被测系统 → 主动问入口地址（页面地址即可）→
逐层探测 → 登录接口用 request 实测（body 带凭证模板 + ref）→ 2xx 后 declare_token 声明提取（成功返回
`sut_config_auth_snippet`）→ **只把验证过的结论**写进 `sut_configs/`（protocol_flavor、auth 段 snippet 原样粘贴）→
缺凭证字段经 `ask_user(kind=credential)` 会话内直录 → 全绿才视为 SUT 段完成。探测证据落 `workspace/agent_logs/`
（包内只落最终 YAML）。

**通道纪律（v4.7.3 起，与门禁/提示词三面对齐）**：可执行通道只有 `agent_protocol` 与
`generic_http`（排期单源 `SCHEDULED_CHANNELS`，`browser` 预留落盘即打回）。判定「不支持
agent-protocol」前，runs/commands 两形态都须带凭证实测且核心端点均非 ✅（单形态受挫只
是「未验证」，401/403 矩阵更不构成证据）；改走 generic_http 是**用户可见的决策**——须
呈报探测结论并经用户确认，且 request_template/response_mapping 先用 request 实测同形
请求核对后才可落盘。**不得静默降级改写通道**。

#### 安全红线增量（§6.4 之外新增，工程难点所在）

1. **凭证旁路**：凭证值只经 secrets store ↔ 工具内部，LLM 上下文不见凭证值；提取在服务端
   持有的响应上进行（token 只进会话 token 表与 snippet，不进工具返回）——「禁凭证明文」
   红线延伸到网络面与声明面
2. **host 边界与凭证外发组合级授权（D1）**：网络工具仅可访问「用户本轮提供 host + sut_configs
   已有 host」；凭证外发按 **(host, ref) 组合首次外发前经 `ask_user` 确认一次**，预览展示
   **完整 URL + 模板 body 原文**（占位符形态天然不含凭证值，路径抄错只有在这里用户才看得见）；
   授权后本会话同组合不再逐次问，**每次外发留痕**（credential_grant）；非交互环境一律不外发
3. **探测内容注入防护**：抓回的 HTML/JS/响应头一律视为 **data 而非 instructions**——分隔
   包裹 + 截断 + 剥离指令样文本；最终防线是 staging→diff→用户确认门禁
4. **登录防锁（「认证层拒绝」语义）**：作用于 request 带凭证请求，按（ref, 完整URL, body）
   组合不自动重试，防试错锁死账号；**入锁集合 = 认证层拒绝（4xx/5xx）**，404（请求未到
   认证层）/ 网络失败 / 2xx 均不入锁——换候选路径继续实测是正当行为，防锁不误伤探索；
   用户纠正后 body 变化视为新组合；`declare_token` 不重发请求，重声明不受防锁约束；
   凭证重新录入（`_save_credential`）解锁该 ref
5. **值回流条件化**：「值要回流，前提是知道哪些值是凭证」——带凭证请求的 2xx 响应在
   declare_token 声明前**只回键路径结构树**（响应可能含会话凭证，零格式假设）；声明后
   掩码原文回流（token 值已知名、掩得住）；非 2xx 与非凭证请求原文回流（排错需要）；
   GET 抓取缓存排除凭证请求（防 search_content 绕过）
6. **总量约束**：单探测 10s 超时；轮内预算**按工具分池**（request 25 / declare_token 10 /
   discover_login 5 / search_content 30 / probe_protocol 8）；
   阶梯③路径 ≤10 条（定向检查，非扫描行为）
7. **探测副作用言明**：probe_protocol 建临时线程属对被测系统的写操作，探测前经 `ask_user`
   言明（可与 request 授权确认合并为一次交互）

#### 泛化设计：前端包分析原语

> 设计判据：**不 hardcode 正则/关键字，让 CLI 具备泛化的分析能力**——真实站点的登录契约
> 藏在路由级异步分块里、接口域与页面域分离，逐站点写死的正则/路径清单对下一个站点必然
> 失效（此类硬编码已全部移除，分析知识下沉 Agent 推理与 prompts 方法论）。

**能力分层**（什么进代码、什么进 LLM 的边界）：

| 层 | 内容 | 归属 |
|---|---|---|
| 机械原语 | 抓取入缓存、子串检索、HTML 结构解析（stdlib html.parser，**无语义过滤**）、OpenAPI 挂载点探测、定向路径检查（≤10 条，**路径由 Agent 经 `paths` 参数自拟**） | 代码 |
| 分析知识 | 搜什么（业务词/请求构造痕迹/分包机制痕迹）、分块命名解读与 URL 推算、接口基址与相对路径组合、登录表单判读、登录路径候选拟定 | Agent 推理 + prompts 方法论 |
| 字段语义 | 凭证字段实际要输入什么（如 captcha 实际承载密码） | Agent 经 `ask_user(desc=…)` 传入 |

- prompts 配套**前端包分析法**方法论（发现→检索→读摘录→分块跟随→基址组合→实测验证）；
  ask_user credential 必带 `desc`（直达字段语义）；request 授权预览展示**完整 URL + 模板
  body 原文**（路径抄错只有在预览里用户才看得见）。

#### 证据账本与落盘对账

> 设计原则：**凡可机械传递的事实不经 LLM 转述；必须转述处，由机械对账兜底**——LLM 转述
> 落盘会变形（实测过的 API 域被拆成自造 `login.base_url` 字段被静默丢弃、协议矩阵 ❌ 的
> host 仍被声明可用），通用机制优于点查式门禁逐字段打补丁。

**三环防线**（「验证结果正确落到场景包文件」的完整链路）：

| 环 | 机制 | 落点 |
|---|---|---|
| ① 同构词汇（消除转换需求） | `declare_token` 渲染的 `auth` 段与执行器词汇同构：`token_source` 三态（`Bearer / header:<X> / cookie`）即执行器 `SUTSession.token_type`，cookie 自 Set-Cookie 提取落 `session_cookie` 形态（执行器靠共享 client 的 cookie jar 承载登录态，语义 1:1）；凭证仅 `credential_ref` 引用 | `workbench/sut_probe/tokens.py` |
| ② 工具返回即产物（装配在证据产生处完成一次） | 声明成功时由**工具机械渲染** `sut_config_auth_snippet`（auth: 段 YAML，词汇零翻译）并登记证据账本；Agent 的职责收缩为「原样粘贴」 | `workbench/sut_probe/tokens.py::_render_auth_snippet` |
| ③ 落盘对账（变形必被打回） | 提交门禁用**执行器同款** `resolve_login_url` 把暂存配置还原成「实际会打到哪个 URL」，与账本逐字段对账（登录 URL/method/body_template/token_path/token_source/expires_in_path；协议核心端点 ✅）——不一致打回并携带权威片段 | `workbench/gates.py::sut_evidence_gate`（取代 `_sut_protocol_gate` 点查） |

配套修正：

- **证据账本**：`SUTProbeToolServer` 持有 `_verified_logins`（ref→登录事实）与
  `_verified_protocols`（host→矩阵事实，含失败矩阵）；登记/查询收口 `record/verified_*`。
- **协议假阳性**（`probe/protocol.py`）：3xx 重定向不计 ✅（catch-all 假证据）；建线程失败
  即跳过后续端点并如实记录「未探测」。
- **未知键显式拒绝**（`registry.validate_sut_config_document`）：以执行器 `model_fields`
  为白名单（`extra="allow"` 会静默丢弃发明字段），复用 `SUTSystemConfig` 校验必填/枚举/
  `${VAR}` 展开；staging 与 `scenario validate` 双端接线。
- **URL 解析单源**：`registry.resolve_login_url` 为「配置实际会打到哪个 URL」的唯一真相，
  执行器与落盘门禁共用，永不漂移。
- prompts/guide 同步：auth 段照抄规约、核心端点 ✅ 才可声明、301 非证据。

### 6.6 会话机：长任务执行与失控防线

> 设计动机：正当长链路（前端包分析 30+ 次检索/抓取）会撞上 `recursion_limit = max_turns × 2`
> 安全阀；撞线若一刀切回滚，用户说「继续」后 Agent 全失忆。两层修正：①步数为**阀**、
> 预算（token/成本）为**缰绳**；②撞线/中断 = **暂停保现场**，不是销毁现场。

#### 失败语义：唯一的失败是用户放弃

| 事件 | 行为 |
|---|---|
| recursion_limit 撞线 | **暂停**：salvage 保现场 → 自动开新段续跑 / 交还用户 |
| Ctrl+C 中断 | **暂停**：salvage 保现场，提示「说继续接着干 / 放弃改动回滚」 |
| LLM 瞬时错误（断流等） | **暂停**：salvage 保现场，可直接重试（首轮同此防护，会话不退出） |
| 预算到界 | **暂停**（`aborted_reason=budget_exceeded`）：交还用户，进度完整 |
| 分段数耗尽 | **暂停**（`aborted_reason=segment_limit`）：交还用户，进度完整 |
| 用户确认时放弃 | 回滚暂存、保留对话——**唯一回滚触发器**（`abandon_pending()`，磁盘不受影响） |

REPL 处置闭环：中断/瞬时错误上抛 → CLI 打印「⏸ 已暂停（进度已保留…）」；「继续」重跑；
「放弃」走唯一回滚触发器。

#### salvage：撞线保现场（根治失忆）

- `create_deep_agent(..., checkpointer=MemorySaver())`：langgraph `MemorySaver` 纯内存，
  会话级生命周期（Agent 实例销毁即释放），仅作事故现场保存器；
- `_invoke` 每次以独立 `thread_id` 调用：**成功路径行为不变**（宿主持有消息重放的既有架构
  不动）；
- 撞线/中断时 `aget_state` 捞半途消息 → **孤儿 tool_call 修复**（`repair_orphan_tool_calls`：
  无结果的调用合成「（会话在此被打断，未执行完）」失败 ToolMessage，消除孤儿调用破坏图
  的问题）→ 全线程替换宿主历史；暂存区保留（跨轮本就保留）。

#### 自动分段续跑：干完为止（Claude Code 式）

- `recursion_limit` 是**单段安全阀**：撞线不交还用户，自动开新段续跑（同一对话、
  同一预算池、同一暂存），直到——任务完成 / 分段数上限（`max_segments`=3）/ 用户 Ctrl+C；
- 段边界发 `phase: checkpoint` 事件，CLI 显示「⏭ 已自动续跑（第 N / M 段，进度保留）」；
  交还用户时进度完整，「继续」即接着跑；`probe.new_turn()` 只在**用户轮**开始时调用
  （域预算按用户轮计，不随段重置）。

#### 预算缰绳 + 配置化（失控控制的单位从「步数」换成「钱」）

- `BudgetGuard` 会话级 token/成本预算经 runtime `callbacks` 注入（复用执行侧组件）：
  到线 = 暂停交还（salvage 保进度），不是失败；
- 轮数去 hardcode：`scenario new/edit --max-turns / --max-segments / --budget-usd`，
  与 `WorkbenchAgentConfig` 同一载体（§6.9）——缺省值只是安全阀，不是天花板。

#### 进度外置：进度活在文件里，不活在对话里

- prompts 规约：**每验证一条结论立即 `write_file` 更新暂存草稿**（sut_configs/task_sets
  随探测渐进成形，不攒到最后一次性写）——暂存跨轮保留，故任何暂停/崩溃后进度都在文件里；
- 配合 agent_sessions 对话持久化与草稿目录（§6.1/§6.3），跨进程断点续作成立。

#### 失控缰绳盘点

| 缰绳 | 语义 |
|---|---|
| 工具级预算分池 | request 25 / search_content 30 …（§6.5，防单工具空转） |
| 单段步数阀 | recursion_limit（防单段死循环——阀，非任务预算） |
| 分段数上限 | 默认 3 段（总工作量封顶） |
| token/成本预算 | BudgetGuard 会话级（真实经济缰绳） |
| 人工控制 | 随时 Ctrl+C（进度保留）+ ask_user 交互点 + staging→diff→确认门 |

### 6.7 模块组织与扩展方式

**分层原则**：会话机（通用，零域语义）/ 域工具面（一域一 server）/ 域门禁（档位策略）。
会话机对应 Claude Code 的「主循环」，域对应「工具 + 上下文」——新域 = 新 tool server +
prompt 段 + 档位登记，**不改会话机**。

| 模块 | 职责 |
|---|---|
| `agent/workbench/agent.py` | 会话机：turn/流式/预算/分段/salvage/对话持久化/门禁编排（门禁策略由档位注入）；包域语义全部下沉 |
| `agent/workbench/tools.py` | 暂存沙盒原语（staging/view/commit/diff、路径与扩展名守卫）+ 包域工具（validate/manifest/reference）；原语/域的文件拆分留待第二域落地时按需切开（YAGNI） |
| `agent/workbench/sut_probe/` 包 | SUT 接入调试域：ProbeContext 共享状态 + 域工具类 request/response/search/discovery/protocol/tokens/ask_user（helpers/specs 设施）+ `server.py` 薄委托壳；组合模式，协作契约由 context 承载；「一域一 server」形态不变，拆的是实现不是边界 |
| `cli/cmds/workbench_agent.py` | REPL 宿主：流式渲染挂接 / ask 桥 / 中断提示 / 落盘归位 |
| `cli/console/agent_stream.py` | 流式事件渲染（表现层基础设施，与 prompts/render 同层） |
| `assets/configs/workbench_agent_prompts.yaml` | 提示词资产（分段装配，见下）+ `intro` 自我介绍段（§6.8） |

**域装配档位（profile）**：`WorkbenchAgent(root, domain=<域档位>)` = 工具面清单 + 提示词段
+ 门禁策略。**域命令是档位快捷方式**——`scenario new/edit` 预置包域档位。

**提示词分段装配**：资产结构 `system_prompt_base`（会话机段——身份/红线/控制，零域语义）
+ `domain_segments.<域>`（域方法论与输出规范）+ `domain_labels.<域>`（域展示名，与横幅
`{domains}` 同源）；`_build_system_prompt` = base + 装配域段拼接后统一字面 replace
（`{domain}/{tools}/{pkg_root}/{assets_root}`），未装配域抛 `AgentError`——新域上线只改
资产 + 登记档位，会话机零改。

**红线泛化**：§6.3 staging 门禁（磁盘只见「用户确认 + 校验通过」的内容）与 §6.5 网络红线
（host 边界 / 凭证旁路 / 防锁 / 注入防护）升格为**工作台级工具面策略**——任何新域的网络面 /
落盘面工具必须以策略形式接入（如数据集下载 = host 确认 + 磁盘限额），不得绕过。

### 6.8 启动横幅与自我介绍

对标 Claude Code 首屏（欢迎框 + cwd + tips）：新用户进入会话先获得一段自我介绍——
我是谁、能做什么、怎么用。

**内容要素**：身份一句话 → 当前任务对象 `{root}` + 能力域 `{domains}` → 使用示例 2–4 条
（须与档位真实能力一致，不得宣传未装配域）→ 红线与确认方式 → 控制方式，顺序固定。

**成稿（场景包域 + SUT 接入调试档位；`{root}` 渲染为实际路径）**：

> 你好，我是 **agent-eval 工作台 Agent**——你用自然语言下需求，我调用工具逐步完成
> 评测工程中的多步操作。
>
> 当前任务对象：`{root}`　　可用能力域：场景包工程 · SUT 接入调试（其余域随版本增装）
>
> 可以这样用我：
> - 「创建一个代码安全评测场景包，被测系统入口 https://…」——给页面登录地址即可，
>   我会探测登录接口与 agent 协议、实测验证后才写入配置
> - 「参照 chat 包，把规则集换成幻觉检测，再加 5 条考卷」
> - 「这个包执行报 404，帮我排查 SUT 配置」
>
> 规则：所有文件改动先进暂存区，给你看 diff、你确认后才落盘；凭证只在会话内隐藏输入，
> 不写进任何文件或日志。
> 控制：Ctrl+C 随时中断（已完成进度保留，说「继续」接着干），输入空行退出。

**实现要点**：

- 文案落提示词资产独立 `intro` 小节，`intro_text()` 以 `{root}`/`{domains}` 字面 replace
  渲染；CLI 只渲染不写死——新域上线改资产即更新介绍，不改代码。
- 渲染：rich Panel 定宽 ≤100 列（防 CJK 双宽截断），REPL 启动时、会话日志行之前；
  `--json` 与非 TTY 静默跳过。
- **横幅先于任何输入**：主菜单一级入口渲染横幅后直入 REPL（`show_intro=False` 抑制重复
  渲染）；LLM preflight 阻断仍在横幅之前（无模型 Agent 不可用）。

### 6.9 结构知识外置与配置归集

#### 6.9.1 结构知识外置：随包 Markdown 规范 + 分级授权读取

包结构知识若 hardcode 在提示词里，与真相源之间漂移无门禁，且结构字段描述混在行为规约中
撑大 system_prompt。设计三件套：

1. **新资产 `assets/guides/scenario-package-format.md`**——面向 LLM 阅读的运行时速查，
   大纲对齐 arch/13 §四（目录结构 / 清单字段表 / rules / prompts / task_sets / datasets /
   metrics policy / sut_configs）。每小节：字段表 + 最小示例 + **「权威样例」指引**（如
   `read_reference("chat", "rules/chat-quality.yaml")`）。随包发布（**运行时资料禁止引用
   仓库 docs/ 路径**——pip 安装用户没有 docs/）。
2. **通用文件工具分级授权（不做 read_guide 专用工具）**——逐文档封装专用工具正是 §6.5
   反对的 hardcode 形态。`read_file` / `list_files` 泛化为 **Claude Code 式分级授权**（§6.2）；
   写路径不泛化：write/delete 仍硬沙盒 + staging 门禁（§6.3 不变量不动）——读写不对称
   正是 Claude Code 的形态。
3. **prompts 瘦身**：「内容规范」段退役 → 沙盒边界改读写分级表述 + 工作流程指路规范
   文档路径；行为规约（工作流程 / SUT 调试方法论 / ask_user 规约 / 输出规范）全部保留。

**真相源分层（关键不变式）**：`validate_package` 门禁（代码）= **硬真相**——Agent
照 guide 写错仍会被打回自修复，漂移的最坏后果是多一轮回改，**不产生坏包**；guide
为运行时速查（受众是 Agent 与开源用户），arch/13 §四为设计真相源，变更 arch/13 时
须同步 guide（文档侧纪律）。

#### 6.9.2 配置归集：tunables 与不变量分层

**分层原则**（行业实践：**按可变性分层，而非物理集中成全局 constants.py**——大杂烩
常量文件掩盖影响面，改一处全仓重审）：

| 层 | 判据 | 归宿 |
|---|---|---|
| 可调参数（tunables） | 随场景 / 用户 / CLI 变 | frozen dataclass 配置对象，构造器注入，默认值单点——与 CLI 旗标（`--max-turns/--max-segments/--budget-usd`）**同一载体合流** |
| 固定阈值（invariants） | 行为不变式（安全红线、截断上限、超时） | 就近具名模块常量，统一 `_MAX_*` 私有风格 + 注释写明依据；跨模块复用才上提共享模块 |

**`WorkbenchAgentConfig`**（会话机 tunables 单点，取代散装构造参数与模块常量）：

```python
@dataclass(frozen=True, slots=True)
class WorkbenchAgentConfig:
    # 会话机（CLI 旗标直通，§6.6）
    max_turns: int = 40              # 单段安全阀基数（recursion_limit = max_turns × 2）
    max_fix_rounds: int = 3          # 校验门禁回改轮上限
    max_segments: int = 3            # 自动分段续跑上限
    budget_usd: float | None = None  # 会话预算（None = 不启用）
    # 对话持久化（§6.1）
    max_dialogue_entries: int = 40
    resume_max_entries: int = 24
    resume_max_chars: int = 400
    # 探测域档位默认（域档位可覆盖——域 = 工具面 + 提示词段 + 门禁策略）
    probe_budgets: dict[str, int] = field(default_factory=lambda: dict(TOOL_BUDGETS))
    probe_timeout_s: float = 10.0
```

配套纪律：非可选依赖的 import 上提模块顶层（`deepagents` 保持惰性，`[agent]` extra
红线）；**ToolSpec 描述即对外契约**（开源用户与 LLM 同读），描述与行为一致性纳入
review 检查项。

---

## 七、查看与结果浏览

### 7.1 `scenario show`

`PackageManager` 只读解析（内置/项目/本地仓库三源统一）→ 分区渲染：结构树（`tree`）、规则集表（`rules`：id/评估器/tier/weight/enabled）、考卷预览（`tasks`：任务数 + 首 N 条）、SUT 概览（`sut`：通道/端点/鉴权策略/`credential_ref` + 凭证就绪态，不显示值）、清单（`manifest`）。数据零新解析器，复用 ConfigLoader 与 manifest 模型。

### 7.2 `runs list / show`

- `list`：直接扫描 `workspace/runs/` 目录（manifest + summary 即读）→ 表格（run_id/模式/**状态**/包/任务数/Reward）。状态推导：`已评估`（有 summary）→ `已执行⚠/已执行`（有清单，⚠=日志含错误）→ `执行失败`（无清单但 agent_logs 有 error 事件）→ `中断`（无产物）。
- `show <run_id>`：直读 run 目录 → 指标卡按 `metric_definitions` 动态渲染（不硬编码）；失败 breakdown TopN。**无报告时不再是干巴巴一句「无 summary.json」**：展示状态 + 从 `agent_logs/*.jsonl` 提取最后一条 error 的失败原因；凭证类错误附 `secrets set <ref>.<field>` 录入指引；已执行未评估给出补评估命令。
- 配套机制：执行前**凭证预检**（`preflight_sut_credentials`，按 `auth.type` 逐字段 require）——缺凭证立即失败并给出录入命令，不再进 Agent 循环换通道试探烧完 `max_turns` 才以「超过轮次限制」收场；`run`/`suite` 的 workspace 根统一走 `paths.default_workspace`（`WORKSPACE_DIR` 生效），消除与 `runs list`/`pipeline` 各读各的漂移。
- **缺失自动补录**（req/04 §3.5）：`ensure_sut_credentials`（落 `_common.py`，跨组共享）挂在 **run/pipeline/suite 命令层、进度视图启动前**（`execute_stage` 保留纯 `preflight_sut_credentials` fail fast 兜底）——探测走非抛错的 `missing_credential_fields`（与预检同源 `required_credential_fields`，数据驱动），缺失时交互终端列出缺失项 → 确认 → 逐字段隐藏输入 → **一次落盘**（空输入整体取消，不留半截状态）→ 复检通过即继续执行；取消/`--no-input`（CI）退回原 fail fast（SUTAuthError 带 `secrets set` 引导），云端 executor 不经此路径（env 注入，`orchestrator.eval_packages` 独立编排）。**挂点必须在 stage_progress 之外**：进度转轮单行重绘会把输入提示行刷掉——补录提示被「执行 N 个任务」掩盖，用户不知该输入；同时补录前置于 run_id 生成，取消时不留半截运行目录。

---

## 八、非功能实现要点

| 项 | 实现 |
|----|------|
| 性能 | `start` 惰性导入（questionary/deepagents 按域加载）；进度视图 rich 单行重绘 |
| 安全 | `.env` 0600；配对码一次性短时效；凭证不进对话/diff/日志（脱敏钩子在工具层） |
| 可靠性 | LLM 不可用：执行路径零影响（既有 SKIP 降级），工作台 Agent 报错并指引模板路径；浏览器不可用降级打印 URL |
| 可测试 | console/prompts 原语 mock 注入；退出码/JSON 契约测试；WorkbenchAgent 以 mock LLM 回放（禁联网）；open_url mock（测试不开真浏览器） |
| 可维护 | 向导文案外置 YAML；等价命令映射表单点（`console/equiv.py`）；新增命令组 = cmds/ 新模块 + `__init__.py` 一行注册；新增工作域 = workbench/domains/ 新模块，均不改内核 |

---

## 九、行业实践对照

| 设计项 | 本方案 | 行业实践 | 评注 |
|--------|--------|---------|------|
| 命令/业务分离 | 命令薄壳 + 纯函数动作 + `_stages` | gh：命令构造器注入 Factory，业务在 `pkg/`；pip：解析与逻辑分离 | ✅ 一致 |
| 目录组织 | `cmds/` 一组一模块 + `console/` + `workbench/` | gh：`pkg/cmd/<域>/` + `pkg/cmdutil` + `pkg/{prompter, browser, iostreams}`；oclif：目录即命令树（嵌套子目录 = topic） | ✅ 结构同构；typer 无目录自动发现，显式注册是 Python 生态惯例（huggingface-cli 等） |
| 依赖注入 | console 模块函数 + mock 参数注入；WorkbenchContext 部分承担 | gh `cmdutil.Factory` 显式依赖束（IO / Browser / Prompter / Config 惰性构造） | ⚖️ 中型规模下模块级注入已够；命令动作需共享更多环境态时演进为显式 `CliContext`（可选，不强制） |
| 交互抽象 | `console/prompts.py` 收口 + 非 TTY 降级 | gh `pkg/prompter` 接口 + 测试替身 | ✅ 一致 |
| 浏览器边界 | `cmds/open_url.py` 单出口 + `$BROWSER` 覆盖 + 无浏览器降级 | gh `pkg/browser` | ✅ 一致（`$BROWSER` 为本次补齐） |
| 浏览器登录 | 粘贴 Key 双通道（§5.1） | gcloud / gh / stripe：RFC 8628 设备授权（user_code + verification_uri + 轮询状态机） | ➖ 设备码流复杂度高，粘贴 Key 已满足，不采用 |
| 机器可读输出 | `--output-format text\|json` + stderr 分流 + 退出码 0/1/2/3/130 | kubectl `-o` 打印器族；gh `--json` 类型化字段；sysexits 传统 | ✅ 双格式够用，需要 yaml/表格再扩 |
| 查看即网页 | `--web` / `open` | `gh <entity> view --web`、`vercel open` | ✅ 一致 |
| 首用引导 | preflight 引导链 | gh 主动 auth 提示；`gcloud init` 向导 | ✅ 一致 |
| 命令插件化 | 不做（评估器插件在 evaluation 层） | oclif plugins、gh extensions | ➖ YAGNI，出现需求再议 |

其他沿用范式：`flutter doctor` / `npm doctor`（顶层自检）、Claude Code / Aider（会话式 Agent：计划先行、diff 确认、工具透明）、`create-next-app` / cookiecutter（模板 scaffold）、12-factor CLI（非交互可旁路、stdout/stderr 分离、稳定退出码）。

---

## 十、关键文件清单

| 文件 | 职责 |
|------|------|
| `cli/__init__.py` / `cli/main.py` | 唯一装配点 / 顶层命令薄壳 |
| `cli/console/{prompts,render,agent_stream,output,equiv}.py` | 表现层基础设施（原语/渲染/Agent 流式/JSON+退出码/等价命令） |
| `cli/workbench/session.py` + `workbench/domains/*` | 向导框架与四域动作 |
| `cli/cmds/`（scenario/workbench_agent/models/auth/runs/open_url/doctor + 既有五组） | 子命令组（typer 绑定 + 纯函数动作）与 Agent REPL 宿主 |
| `agent/workbench/agent.py` / `agent/workbench/tools.py` | 工作台 Agent 会话机（turn/流式/预算/分段/salvage）与暂存沙盒工具面（§6.1/§6.2） |
| `agent/workbench/sut_probe/`（context + 域工具类 + server 薄委托壳） | SUT 接入调试域工具面：组合式工具面（§6.5/§6.7） |
| `agent_eval/assets/configs/workbench_agent_prompts.yaml` | 提示词资产：`system_prompt_base` + `domain_segments` 分段装配（§6.7）；`intro` 自我介绍段（§6.8） |
| `agent_eval/assets/guides/scenario-package-format.md` | 随包发布的包结构规范——Agent 经 `read_file` 直读（assets 自动授权域，§6.9.1） |
| 平台侧 `/cli-auth` 授权页（通道 B） | 09 侧，交互流程见 §5.1 |

---

## 十一、版本记录
> 逐版一行速览，只记「改了什么」；演进理由见 git 提交历史与正文对应章节。

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0–v1.5 | 2026-08-31 | 初稿：双前端同内核 + 向导框架 + 目录重组与 JSON 输出 |
| v1.6–v1.9 | 2026-09-01 | auth 组 + 平台身份密钥区 + 凭证自动补录 |
| v2.0–v2.13 | 2026-09-02 | SUT 接入调试：方案评审 + 五工具落地 + 泛化迭代打磨 |
| v3.0–v3.3 | 2026-09-02/03 | WorkbenchAgent 升维：会话机 + 组织迁移 + probe 拆包 |
| v3.4–v3.9 | 2026-09-03 | 横幅直入 + 防锁语义 + 证据账本 + 协议契约同构 |
| v3.10–v3.14 | 2026-09-03 | 探测迭代：先登录时序 + http_request + configurable 重探 |
| v3.15–v3.18 | 2026-09-03/04 | 对账门禁族：规则引用 + 判官变量 + 端到端复审 |
| v3.19–v3.20 | 2026-09-04 | 归位时序修复 + num_samples 包内可配 |
| v3.21 | 2026-09-07 | 移除设备码流接口约定（粘贴 Key 双通道已满足）+ §六精简去过程性内容 |
| v3.22 | 2026-09-07 | 工具面返回值规范轮（实测排查驱动）：probe_login token_path 归一化/键路径树/失败模式三分 + 探测面静默分支治理（fetch 失败原因/auth_attached/checked_paths/stream 3xx/cleanup 留痕/host 拉黑）+ 归位横幅不预设门禁通过 |
| v3.23 | 2026-09-07 | M1 值回流条件化（二轮实测事故驱动：裸 JWT 经 evidence 回流）：probe_login 2xx JSON 提取失败时 evidence 只回键路径树不回原文——「值要回流，前提是知道哪些值是凭证」，零格式假设；探测面 v4 重构设计立项（docs/plan/03 薄原语+厚思考，request/declare_token/链式变量，probe_login 拟退役） |
| v4.0 | 2026-09-08 | 探测面 v4 落地（薄原语+厚思考，docs/plan/03 M1+M2）：`request` 门控请求原语（抓取/调试/登录实测同一出口；凭证模板服务端注入 + (host,ref) 组合级外发授权 + 防锁 + 值回流条件化 + 链式变量 `{{ stepN.* }}` 探索）与 `declare_token` 事后声明式提取（token_source 三态同构执行器、snippet 机械渲染、不重发请求无撞锁、执行器宽度守卫拒绝超宽形态落盘）替代 probe_login（退役）；共享 AsyncClient 会话级持有（cookie jar 跨请求）；预算重定 request 25 / declare_token 10 |
| v4.1 | 2026-09-08 | 通道排期防线前移：落盘门禁打回未排期通道（§6.3 门禁族新行，单源 `SCHEDULED_CHANNELS`）+ 执行域 SUT 选择即预检（只答 2 个交互即见错）；§6.5 通道纪律（两形态实测才可下「不支持」结论、改通道须用户确认、不得静默降级） |
| v4.2 | 2026-09-08 | 交互会话日志降噪（§6.4）：传输层日志器（httpx/httpcore/openai/anthropic）非 DEBUG 模式压到 WARNING——修执行域 setup_logging 进程级污染后续 Agent 流式直播的噪声混流 |
| v4.3 | 2026-09-10 | 执行域事故修复（content-safety 假成功，arch/03 v4.8 同步）：generic_http steps 链式模板 + SSE 末步 + text 未命中判 failed；模板变量审计落盘门禁（§6.4 新增）；执行面工具结构性裁剪——invoke_* 退出 LLM 工具面 + 文件工具 workspace 边界（§6.4 新增）；prompts/guide 资产同步（steps 链实测纪律） |
