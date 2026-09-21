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
        ▲ 工具面（包根沙盒 / 受控网络域 / 执行直通域 / 数据集域，§6.10/§6.11）
   WorkbenchAgent（DeepAgents 统一会话：包工程 / SUT 调试 / 评测执行 / 数据集）
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
│                      #   + execution/ 评测执行域（§6.10）+ datasets/ 数据集域（§6.11）（v4.11）
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
| D-CLI-9 | **Agent 执行 = 直通阻塞调用**（v4.11，v4.12 补编排真相源）：`run_evaluation` 经 `pipeline_core` 与 CLI 共用唯一编排与渲染路径，执行期间宿主经 render_bridge 挂起 Agent 流式渲染、rich console 直出过程；LLM 只见紧凑摘要（run_id/指标/产物路径），不转述过程；执行不计会话预算（非 LLM 活动，天然成立），Ctrl+C 执行期 = 协作取消中断（任务边界，产物已落盘） | 需求 2「Agent/命令行输出一致」的结构性保证——编排与转述双面漂移被单一真相源结构性消解；执行期单输出流，终端混排问题消解（req/04 开放问题 #7） |
| D-CLI-10 | **受控出网域白名单制**（v4.11）：网络面按域开列（SUT 探测 §6.5、数据集下载 §6.11），每域单出口 + 域名白名单 + 确认门槛；其余工具面维持无网络红线 | 出网能力成为显式装配决策而非默认存在；§6.7 红线泛化（「任何新域的网络面以策略形式接入」）的实例化 |

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
  能力介绍先行）。默认任务对象 = 新包草稿（`workspace/.staging`，首次确认落盘即按清单 id
  归位 `cwd/<id>-package/`（v4.9），空会话退出清理草稿，见 §6.3）；改已有包经 `list_packages`
  三源发现（v4.4）+ `read_reference` 直读既有内容——**project/local 包轻量修改默认
  `edit_package(ref)` 会话内原位切根**（v4.12.2，§6.5：用户确认后沙盒根切到该包，
  落盘原位生效，不走骨架/五阶段/fork），明确要新版本/新包才 fork 且**换新 scenario/id**
  （沿用原 id 归位时与既有目录冲突）；prompts 域段「改造已有项目包」规约按「改什么」
  三档分流，`scenario new/edit --mode agent` 命令与域内快捷方式保留为显式直达
  （`scenario edit` 为跨进程续作的等价通道，非会话内轻量编辑的必经之路）。
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
- `--log-level quiet|normal|verbose|debug`（v4.11）：执行日志四档，取代 `--verbose` 二档（P6 惯例一次性切换，全仓引用同步清理）；详见 §4.4。
- 契约测试：退出码 × 异常矩阵、JSON 输出 Schema 快照。

### 4.4 执行日志级别（四档，v4.11）

> 需求 req/04 F-C-EXEC-07：task_sets 逐条执行时「重要过程不可见、全开又过载」。`--verbose` 只有开/关两态，
> 升级为四档后**过程可见性成为显式选择**；CI 侧 `quiet` 档显著压缩 Jenkins 日志体积（与 pipeline.stdout
> 归档实践互补）。

| 档位 | 语义 | 实现落点 |
|------|------|---------|
| `quiet` | 仅任务结果行（`task-07 ✅ reward 0.82`）+ 总摘要 | 进度视图关闭阶段 spinner 与关键阶段事件；`setup_logging(WARNING)` |
| `normal` | **现状默认**：任务级进度 + 关键阶段事件 | `setup_logging(INFO)` + 既有进度视图（行为与 v4.10 默认一致） |
| `verbose` | 过程可见性核心档：SUT 请求/响应摘要（方法/端点/状态码/耗时）、judge 交互（评估器/结论/耗时）、重试事件 | 事件行直出——以既有结构化日志（`agent_logs/*.jsonl`）与执行回调为事件源盘点补缺，console 新增事件行渲染；`setup_logging(INFO)` |
| `debug` | 全量原文（含完整请求/响应体） | `setup_logging(DEBUG)`；传输层日志解压（§6.4 v4.2「debug 级原文收紧」的反向开关） |

设计约束：

- **三形态同源**（§6.10 前置）：CLI `--log-level` 参数、向导执行高级选项、Agent 对话（`run_evaluation`
  的 `log_level` 入参，自然语言「详细一点」由 Agent 映射）共用同一枚举与渲染路径；
- **实现单点**：`console/render.py` 事件行渲染按档位过滤 + `core/logging.py::setup_logging` 档位映射；
  事件埋点缺口（SUT req/resp 摘要、judge 交互、重试）在执行内核补 hook——**只加事件、不改指标逻辑**；
- `--verbose` 移除后无别名（D-CLI-6 惯例）；`stage_progress` 启停条件由「非 verbose」改为「非 quiet/normal
  语义等价重述」（进度视图仅 quiet 关闭）。

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
- **多工具面（v4.11 起四域）**：`PackageToolServer`（文件沙盒，§6.2）+ `SUTProbeToolServer`
  （受控网络探测，§6.5）+ `ExecutionToolServer`（评测执行直通，§6.10）+ `DatasetToolServer`
  （数据集发现/下载，§6.11）并列挂载，`_describe_tools` 汇总注入系统提示词；`ask_fn` 同时桥接
  各面交互（执行/下载确认门槛同走此单通道）。
- **工具面复位中间件（v4.4，`workbench/tool_filter.py`）**：`create_deep_agent(tools=...)` 是
  additive 合并、不移除内置——内置 ls/glob/read_file 跑在 StateBackend **虚拟文件系统**
  （与真实磁盘无关、永远为空），实测 Agent 连续 ls/glob 空转后误判「没有场景包」。per-call
  中间件做**允许清单复位**（`wrap_model_call` 内 `request.override(tools=宿主装配清单)`）：
  模型可见工具面恒等于宿主装配清单（全部域工具面），对未来版本新增内置名免疫。不走全局 `register_harness_profile`
  （进程级不可注销，会波及同进程 ExecutionAgent，且按名排除误伤同名沙盒工具）；过滤按对象
  **身份**（`id`）匹配而非按名，全部失配时原样返回（保守 no-op，防上游契约漂移把工具面清空）。
- **提示词分段装配**：`system_prompt_base`（会话机段，零域语义）+ `domain_segments.<域>` 拼接，
  统一字面 replace 渲染 `{domain}/{tools}/{pkg_root}/{assets_root}`；未装配域抛 `AgentError`。
- **预算与检查点**：`BudgetGuard` 会话级 token/成本预算（跨段/跨轮累计，`None` 不启用）；
  `MemorySaver` 内存检查点仅作事故现场保存器（§6.6 salvage），成功路径保持「宿主持有消息重放」。
- **tool_guard 范式**：工具异常转 `{"error": ...}` 结果交 Agent 决策，不中断图。

**会话记忆（跨进程续作）**：对话要点（≤40 条）持久化 `workspace/agent_sessions/<root 路径摘要>.json`
——同一包目录命中同一记录文件，续作时注入此前记录（≤24 条、单条 400 字截断）并附「勿重复
追问已给信息」指引，CLI 显示「已续接 N 条对话」。

**流式直播**：`astream` 事件流（`thinking`/`token`/`tool_start`/`tool_end`/`phase`/`tool_args`/`todos`）
实时回调，`console/agent_stream.py` 按 Claude Code 式渲染；大文件内容在 tool_call args 里
增量生成（不走 text 流），`tool_args` 事件以单行进度显示——否则数十秒无输出形同卡住。
正文 TTY 下行缓冲经 markdown-lite（`console/markdown_lite.py`）行粒度渲染：完整行到达
才转换（标题/粗体/行内代码/列表/引用/围栏，围栏内逐字保真），部分行挂起至收行兜底；
非 TTY 原样直写保持管道日志机器可读。逐 token 全量重渲染（Live + Markdown）因 O(n²)
与工具行抢终端被否，保守规则集（不做单星斜体/表格对齐）防模型字面量误伤。

**任务清单**：`langchain.agents.middleware.TodoListMiddleware`（`write_todos` 工具 + `todos`
状态键，Claude Code TodoWrite 同款语义）挂入 deepagents 中间件栈；注入工具必须并入工具面
复位白名单（按实例 id 过滤，遗漏即不可见）。todos 走 langgraph state + 检查点，跨段续跑/
会话续作自然保留；`stream_collect` 自 updates delta 提取 `todos` 独立事件，CLI 渲染
`✓ 完成 / ▶ 进行中 / ○ 待办` 清单（与上次相同去重不重画）。纪律提示单源在中间件
system_prompt（与工具同源注入），域提示词资产不重复维护；deepagents 默认栈不含该中间件
（其默认 prompt 过长，见 deepagents graph.py 注释），此处传精简版。

### 6.2 工具面与沙盒（PackageToolServer）

| 工具 | 实现要点 |
|------|---------|
| `list_files` / `read_file` | **分级授权读取**（Claude Code 式）：会话根内（暂存视图优先，含 added/staged/deleted 标记）→ 随包资源 `assets/`（自动授权只读，如包结构规范 guide）→ 外部路径经 `ask_fn` 向用户申请（拒绝即拉黑）；read 截断长文件（防上下文爆炸） |
| `write_file` / `delete_file` | **先写暂存区**（staging dict），不直接落盘——diff 确认与校验门禁通过后才由宿主提交（§6.3） |
| `read_manifest` / `update_manifest` | `agent_eval.yaml` 读写同样走暂存（update 为浅合并） |
| `validate_package` | 对暂存视图执行清单合法 + 资源目录 + 规则 YAML 可解析校验（含对账门禁族，§6.3），返回结构化 errors |
| `list_packages`（v4.4） | 三源发现（builtin/local/project）与 `scenario list` 同一真相源（`PackageManager.list`）：返回 ref/source/path/name/editable + 编辑引导 notes——「有哪些包 / 有没有现成包」的**第一查询入口**，不许凭记忆或目录列举判断（v4.4 前只有 `search_reference` 硬编码 builtin，用户既有项目包不可见） |
| `search_reference` | 按文件名检索内置包（courseware/chat/code），返回命中文件与各包真实文件清单 |
| `read_reference` | 只读**已发现包（三源）**文件内容（ref + 包内 path，ref 走 `PackageManager.resolve_ref`）——Agent 参照真实格式的**合法通道**（`read_file` 对包外路径受分级授权约束，防反复试探） |
| `list_evaluators` | 当前可用评估器注册 ID 的注册表实时快照（含本包 entry_points 声明）——rules 的 `evaluator` 字段从此清单**原样复制，勿凭记忆臆造**（copy, don't recall：示范强于指令） |
| `edit_package`（v4.12.2） | **会话目标切换到既有包原位编辑**（既有包轻量修改的正道，验收事故修复——曾规约「退出会话走 scenario edit 或 fork」致加 1 条用例触发全建包流程）：非交互 refused（切写域须确认通道，与 run_evaluation 同策略）→ 定址（路径含清单直取 / `resolve_ref`；builtin 只读拒绝并指引 fork）→ 守卫（目标=当前根提示已在编辑；**staging 非空拒绝**——rebind_root「调用时 staging 已清」不变式，指引先放弃/提交）→ `ask_fn` 确认（展示当前根→目标根）→ 清旧根态（**骨架归档置 None**——跨根携带会让旧包开槽卡住新包 validate；授权账本按根记账，一并清空）→ `relocate_fn`（宿主 `relocate_root(note=…)`：server 重绑 + 图重建 + **会话记录迁移**——切换后跨进程续作命中新包 key）。切根后落盘语义由既有路径保证：非草稿前缀根，确认后**原位生效不归位**（§6.3 归位判定不变）。**切根保育**（v4.12.3）：目标 session record 已存在时不 `replace`（曾静默覆盖目标对话史+账本快照——独立数据损失 bug）——目标对话并入会话记忆（目标史在前，裁剪 `max_dialogue_entries`）、其账本快照按 key 合并恢复（当前会话条目优先），「已落盘包续改免重探」（v4.10）从同根重启扩展到切根路径 |
| `preview_diff` | 暂存区 vs 磁盘原文的统一 diff（宿主确认界面同源） |
| `write_sut_config`（v4.7） | **机械物化**（§6.5 五阶段之阶段 3）：filename 传 `sut_configs/<名字>.yaml` 或裸名 `<名字>.yaml`（机械归位 sut_configs/，v4.9——守卫曾只认带前缀形态却自称「只写平铺文件」，裸名被拒且错误不指路，Agent 在 payload 结构上空转多轮）；agent 只给决策字段（name/channel/base_url/timeout/request_template/response_mapping 等），服务端从探测证据账本取该 ref 的 `auth_snippet` **verbatim 注入 auth 段**——「验证→配置」的传递不经 LLM 转述；无账本事实即拒绝并引导先 request 实测 + declare_token；注入后**内联执行器同款 schema 校验**（未知键/模板变量审计当场打回）才入暂存；`auth` 键手写一律拒绝（防转述变形）——取代「snippet 原样粘贴」纪律，转述类打回在机制上消失。`write_file` 写 sut_configs 的旧路径保留兜底（auth_chain 链式认证等未落地形态） |

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
不同——会话在 `workspace/.staging/agent-eval-pkg-<rand>/` 草稿区进行，**首次确认落盘成功即
归位 `cwd/<id>-package/`**（v4.9，同卷原子归位，与 skeleton 模式 `./<id>/` 方向一致；给了
REF 则直接定址；此前归位压到会话结束，实测用户确认后在预告路径找不到包、以为落盘丢失）。
配套语义：

- **落盘即归位 + 沙盒重定向**（v4.9）：门禁通过、暂存落盘的同一时刻，草稿目录挪到
  `cwd/<id>-package/`，`PackageToolServer.rebind_root` 重定向沙盒根（staging 是内存态、
  root 无持久句柄，会话中重绑定零残留），`WorkbenchAgent.relocate_root` 重建图（系统提示的
  `{pkg_root}` 在建图时烘焙；对话消息由宿主持有，重建不丢上下文）并向对话注入归位注记——
  **同一会话可继续自然语言修改已归位的包**。会话记录文件随迁到新 `session_key`（含
  SKELETON.md 审计产物）：归位后跨进程续作（`--output` 指回）命中同一记录，上下文不因
  归位断裂；迁移失败仅丢跨进程续作，会话内不受影响。
- **中断 ≠ 放弃**：异常退出不清理草稿，提示 `--output <草稿路径>` 续作；显式指定路径非空
  放行（续作），默认路径仍要求空目录。中断/收尾一律以 server 实时根为准（落盘时可能已
  随首次归位迁移，入口函数持有的初始 root 变量已过期）。
- **跨进程续跑 = 进度恢复**（v4.10）：每轮对话要点落盘时同步写入**进度快照**——暂存文件
  文本 + SKELETON.md 留档 + 证据账本（`verified_logins`/`verified_protocols`，纯事实数据；
  `session_tokens` 等凭证态**绝不入快照**）。重启续作（`--output` 指回同一目录）在 Agent
  构造时自动恢复暂存与账本，并向对话注入「已恢复上次会话进度：暂存 N 个文件、已验证登录
  M 项……无需重新探测」注记——五阶段流程的中间进度不再困在内存 staging（实测事故：代理
  超时建议用户「重启会话续作」，暂存与账本实际全丢，只能从头再来；已验证过的登录被迫重探，
  违背「验证过了又来一遍在机制上消失」承诺）。`export/import_staging_snapshot` +
  `ledger_snapshot/restore_ledgers` 类型容错对称，快照随归位迁移天然随迁。
- **归位时序**：成果完整的「中断」照常归位交付；「保留现场」只适用于半途。
- **归位冲突报错保留草稿**：落盘即归位撞名 → 红字报错、包留草稿位、**不打断会话**，会话末
  `_finalize_new_package` 兜底再试（v4.9 起其职责收窄为兜底 + 改名同步：会话中自然语言改过
  包名的，按最后一次落盘的清单把目录同步到新名；已归位且未改名则静默返回，归位提示已在
  落盘时刻给出）。清单未落盘 → `Exit(1)` 交用户处置。
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
| SUT 未知键拒绝（`registry.validate_sut_config_document`） | 以执行器模型 `model_fields` 为白名单（运行时 `extra="allow"` 前向兼容意味着发明字段被**静默丢弃**）并**递归下钻 `sut.request_template.steps[i]` 与 `steps[i].poll`**（v4.7：steps 链/poll 步同样白名单化，幻觉字段逐项点名打回并附该层合法字段清单），复用 `SUTSystemConfig` 校验必填/枚举/`${VAR}` 展开；`SUTRegistry.load` **装载卡口**（v4.7）：执行入口同源复检，违例 raise `SUTChannelError`——绕过工作台手改的配置照样被拦（arch/03 §4.0.3） | 自造 `login.base_url` 字段被静默丢弃 → 执行时拼回页面域 404；GitHub Actions 肌肉记忆 `kind/depends_on/until` 写进 steps → Pydantic 静默丢弃 → 全部任务 run_error（jxb 20260917_003025，11/11） |
| 骨架开槽检查（v4.7，`skeleton_gate_errors`） | 暂存含 `SKELETON.md` 时：`- [ ]` 开槽全部列出打回（带逐条原文）；`- [x]` 闭槽必含「证据：」——**闭槽 = 有证据的结论，不是表态**；opt-in——无骨架的会话（克隆/fork 内置包）行为零变化 | 配置在事实未齐时渐进成形，证据与幻觉混在同一文件；探索结论散在头注释里、后续改登录方式无处重开 |
| 通道排期校验（v4.7.3 起） | `channel` ∈ `SCHEDULED_CHANNELS`（`agent_protocol`/`generic_http`，与执行工厂同源单点）；预留通道（如 `browser`）落盘即打回，错误文案自带「探测受挫不是换通道的理由……**不得静默降级改写落盘**」行动指引；generic_http 免协议端点对账（无协议语义），登录对账照走（限本轮暂存增量，v4.12.3 §6.5 ③） | 协议探测受挫后 Agent 静默降级写预留通道 → 落盘成功、答完 5 个交互到执行工厂才报「预留未排期」 |
| YAML 全量解析双防线（v4.10） | ①**写入时 fail-fast**：`write_file` 对 `.yaml/.yml` 内容先 `safe_load`，解析失败当场拒写（未入暂存，错误带摘要与截断提示）——「靠 Agent read_file 自检才发现截断」的一整轮消失；②**校验时全量解析**：`validate_package` 对暂存视图**所有** `.yaml/.yml`（除清单——load_manifest 已覆盖；除 `sut_configs/`——另有解析+schema 校验）解析打回，旁路写入的截断文件（旧快照恢复等）照样拦下 | `task_sets/smoke.yaml` 首写被截断，解析门禁只扫 `rules/` 时漏网，靠 Agent 自检才发现；未自检即可带伤落盘 |

引擎侧配套守卫：评估器**尝试创建且全部失败即中止**（部分失败跳过语义保留）——防
「垃圾报告静默产出」。

### 6.4 安全红线实现

- sut_config 内容扫描：出现 `password/token/api_key` 值字段且非 `credential_ref` 引用 → 拒绝写入并提示 `secrets set`（启发式 + System Prompt 双保险）。
- `scenario new/edit --instruction ... --yes --trust-agent`：非交互模式必须双重显式旗标；默认关闭。
- 会话日志 `workspace/agent_logs/workbench_agent_<ts>.jsonl`：消息、工具调用与参数（凭证字段脱敏）、token、耗时；SUT 探测证据随会话日志同文件落盘（时间线完整）。
- 传输层日志降噪：httpx/httpcore/openai/anthropic 的 INFO 级「HTTP Request: …」在非 DEBUG 模式压到 WARNING（`core/logging.py` 单点）——root 日志是进程级全局态，工作台里执行域先跑过一次评测，噪声就会混进之后所有 Agent 流式直播会话；`--log-level debug` 诊断模式全量放行。
- 子告警堆栈降噪（v4.11.1）：WARNING 以下记录一律摘除 exc_info（root handler 单点 Filter）——第三方库惯于在 DEBUG 级挂良性堆栈（实测 deepagents 对「可选 prompt-caching 中间件缺失」每条 debug 附带 ModuleNotFoundError），rich 渲染成整屏 locals 面板一次四五块，真故障信噪比反被淹没；摘除后只留消息行，WARNING 及以上堆栈完整渲染。
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
| `request(method, url, headers?, body?, ref?, step?)` | 门控请求原语（v4：抓取与接口调试/登录实测同一出口）：返回状态码/耗时/响应头/响应体证据，405 的 Allow、400 业务错误消息不再被截掉 | body/headers 支持 Jinja2 模板：凭证 `{{ 字段 }}`（须带 ref，值由服务端从密钥区注入）与链式 `{{ stepN.路径 }}`（step 响应服务端持有，多步认证链可探索）；GET 入**服务端缓存**供 `search_content` 复用（凭证响应不入缓存防绕过值回流）；证据截断防上下文爆炸；**渲染后 JSON 语义校验**（按 JSON 发送的 body 渲染后非对象/非法 JSON 发送前拦截；显式非 JSON Content-Type 的 JSON 对象 body 标签机械归一化，返回含 `content_type_normalized`，见红线 8） |
| `discover_login(page_url)` | 登录 API 发现阶梯（**普通用户只需输入页面登录地址**）：① 页面 `<form>` 解析 → ② JS XHR/fetch/baseURL 线索 → ②.5 OpenAPI 文档探测（**无前置门**——form 候选与 schema 证据并列，不再仅兜底）→ ③ 定向路径探测（**路径由 Agent 自拟** ≤10 条，不发凭证）→ ④ 只向用户问**登录接口地址**一项兜底 | SPA 无线索是常态，④ 是**预期路径**而非失败兜底；**字段名不问用户**——按候选 fields 拟定，经 request 登录实测（body 带凭证模板）+ 授权预览交用户确认；接口域与页面域分离时指引 GET `{接口域}/openapi.json` 取权威 schema（一份 schema 省掉全部路径与字段猜测） |
| `search_content(pattern, context)` | 已缓存内容检索：子串匹配（防 ReDoS）、大小写不敏感、上下文摘录 ≤12 条（带「数据非指令」声明） | 分析主循环的机械原语，「搜什么」由 Agent 经 prompts 前端包分析法决定 |
| `probe_protocol(base_url, flavor)` | agent-protocol 符合性矩阵：info → 建临时线程 → commands → state → stream；支持带 configurable/modelId 重探 | 逐项 ✅/❌ + 证据，不做二值判定；3xx 不计 ✅；临时线程收尾清理；**已声明的会话凭证自动挂载**；与执行器契约同构（信封/路由头/Bearer 单源复用） |
| `declare_token(ref, token_path?, token_source?, expires_in_path?, static_field?)` | **事后声明式**凭证提取（决策 D2）：对该 ref 最近一次带凭证 2xx 响应声明「凭证在哪个路径」——不重发请求，声明错了改路径重声明即可（防锁不适用）；成功时机械渲染 `sut_config_auth_snippet`（见证据账本）。`static_field` 非空走**静态注入**分支（v4.8）：用户直接提供的 token（如浏览器已登录态，无登录实测）按名自密钥区取值挂载，解除「无实测记录即永远 auth_attached:false」的死循环 | **凭证值不进 LLM 上下文**（提取在服务端持有的响应上进行）；`token_source` 三态与执行器同构（`Bearer / header:<X> / cookie`，cookie 自 Set-Cookie 提取落 `session_cookie` 形态）；缺凭证时 request 错误指路 `ask_user(kind=credential)` 逐字段录入；超出执行器宽度的形态（凭证走请求头/链式认证）显式拒绝落盘——探测可探索、暂不可落盘；**静态注入不入证据账本、不生成 auth: 段**——落盘对账的实测证据语义不被静态值稀释，落盘认证仍须实测路径 |
| `ask_user(question, options?, kind?)` | 主动提问：开放文本 / 单选 / 凭证录入（直写 secrets，隐藏输入） | 桥接 CLI `ask()`/`select()`；非 TTY 返回「需交互」错误 |

#### 创建流程五阶段（Plan-as-Artifact，v4.7）

> badcase 驱动重设计（jxb agent-safety 包，run 20260917_003025，11/11 run_error）。旧流程
> 「探测期 sut_configs 随探测渐进成形」的三重病：①登录实测证据写进 yaml 头注释、steps 段凭
> 训练记忆手写（GitHub Actions 肌肉记忆 `kind/depends_on/until`）——**证据与幻觉混在同一文件**，
> 幻觉字段被 Pydantic 静默丢弃落盘零报警；②「验证过了又来一遍」——修复环里 agent 的最可靠
> 手段是重新登录实测而非修文本（auth 段靠 LLM 抄写 snippet，逐字符对账打回后重探成最优解）；
> ③后续改登录方式（username→phone）时证据散在注释里，变更无受控路径。根因：配置在事实未齐
> 时就开始写，流程没有「未知」的表达方式。重设计原则：**进度即回填骨架**取代「进度即写盘」，
> 配置只能在事实齐备后由机械物化生成。

```
阶段0 意图澄清 ─→ 阶段1 落骨架 ─→ 阶段2 逐槽探测回填 ─→ 阶段3 机械物化 ─→ 阶段4 验收提交
```

| 阶段 | 核心动作 | 退出条件（门禁强制） |
|---|---|---|
| **0 意图澄清** | 主动问入口地址（页面地址即可）与登录确认，沿用现有纪律 | 意图与入口明确 |
| **1 落骨架** | write_file 生成 `SKELETON.md`：按包资产分节（SUT 接入/考卷/规则集/聚合策略）列**槽位**——事实槽写「问题+证据要求」，决策槽写「待定选项+确认方」；**禁止预填猜测答案** | 骨架覆盖全部必做资产 |
| **2 逐槽探测回填** | sut_probe 工具面逐槽探索（预算/防锁/授权红线全保留，缺凭证经 `ask_user(kind=credential)` 会话内直录）；**探测成功由服务端机械追加事实行**到骨架（fact_sink → `- [x]` + 证据摘要），agent 只把结论组织成决策槽关闭 | SUT 节事实槽全闭（骨架开槽门禁，§6.3） |
| **3 机械物化** | `write_sut_config` 从账本装配 sut_config（auth verbatim 注入 + 内联校验）；创作类资产（考卷/规则集/提示词）由 agent 撰写并关闭对应决策槽 | validate_package 全绿 |
| **4 验收提交** | 用户 confirm → 账本对账 → commit；SKELETON.md 排除在包外、归档 `workspace/agent_sessions/` 为审计产物 | 既有五段链不变 |

**骨架契约**（机器可检，`workbench/tools.py::skeleton_gate_errors`）：

- 开槽 = `- [ ]` 行；闭槽 = `- [x]` 且**必含「证据：」**（闭槽 = 有证据的结论，不是表态）；
- **事实槽**只能被探测证据关闭（服务端机械追加，agent 不可代填）；**决策槽**由用户确认或
  agent 论证关闭（agent 手改）——「哪些已验证、哪些还不知道、谁说了算」全程机器可查；
- **变更受控**：改已闭事实槽（如换登录方式）= 重开槽位（证据失效）→ 重探 → 重物化；
- **过程产物**：commit 时排除出包（包目录不见 SKELETON.md，归位干净），跨段续跑经骨架
  归档回种；探测证据仍随会话日志落 `workspace/agent_logs/`（包内只落最终 YAML）；
- **opt-in**：无骨架的会话（克隆/fork 内置包）全行为不变。

**fact_sink 机械事实行回填**：`declare_token` 成功路径（登录实测事实）与 `probe_protocol`
的 `record_protocol`（协议矩阵事实）经构造注入的 `fact_sink` 回调把证据行写给骨架
（`PackageToolServer.append_skeleton_fact`，落在暂存区；无骨架 = 静默 no-op，sink 异常吞掉
只记 `fact_sink_error` 日志）——探测面零反向依赖 workbench 模块，装配侧单向接线。落盘内容
由服务端机械生成，与「验证结果正确落到场景包文件」同一设计原则（见证据账本）。

**两份并行指令合一**：旧提示词「工作流程 6 步」与「SUT 接入调试必做步骤」并行（后者另成
线程），现合并为五阶段单线程状态机——「SUT 接入调试」段降格为**阶段 2 的执行手册**（全部
实测纪律保留：同形实测/防锁/授权/前端包分析法/判读教训），修复环**查骨架不查记忆**；
TodoListMiddleware（todos=「在做什么」）与骨架（「知道什么/不知道什么」）互补不重叠。

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
   阶梯③路径 ≤10 条（定向检查，非扫描行为）；超时错误面附代理指引（本机
   `http_proxy` 劫持会把 0.3s 请求拖到 11.7s 顶爆 10s 超时——指引为 SUT 域配
   `NO_PROXY` 直连；工具不擅改 `trust_env`，内网 SUT 可能必须走用户代理）
7. **探测副作用言明**：probe_protocol 建临时线程属对被测系统的写操作，探测前经 `ask_user`
   言明（可与 request 授权确认合并为一次交互）
8. **变形报文发送前拦截（渲染后校验，v4.5）**：按 JSON 发送的 body 渲染后机械
   `json.loads`——解析为 str/标量（**双重编码**：body 外层多一层引号，SUT 收到 JSON 字符串
   而非对象报 422 `model_attributes_type`）或解析失败（凭证值含 `"`/`\` 破坏模板拼接）一律
   拒发并给准确指引（`{{ password | tojson }}` 转义 / dict 形态传参；数组放行）；422 响应按
   detail type 分诊给 next_step（`model_attributes_type`=body 非对象，**先读 input 回显**——
   那是服务器实际收到的报文；`json_invalid`=非法 JSON；`missing`=按 loc 补字段）——「凡可
   机械判定的变形不发给 SUT 让 Agent 瞎猜」（jxb-server 422 误诊事故：双重编码被误读为
   「后端格式不明」，换字段名/换 FormData 烧光探测预算）。**Content-Type 标签机械归一化
   （v4.8）**：显式非 JSON Content-Type 会同时旁路 auto 补齐与本校验——正确的 JSON 报文顶着
   `text/plain` 标签上 wire，FastAPI 不做 JSON 解析，Pydantic 把原文当字符串校验回 422
   `model_attributes_type`（input 回显带引号，形似双重编码），LLM「换格式重试」烧光预算
   （二轮 jxb 事故，服务端排查见「json 不是 json、内容加了引号」）；body 实为 JSON 对象/
   数组时标签机械改写为 `application/json`（返回含 `content_type_normalized` 留痕），原始
   标量/非 JSON 报文探测原样放行不收缩。同批修复渲染头回填缺口：模板源是整行
   `Key: Value`，回填前须再切出值——整行回填会把 wire 头发成 `Key: Key: Value`（显式
   Content-Type 从未真正生效，FastAPI 靠子串匹配侥幸解析 JSON）

**共享 client 事件循环亲和（v4.8）**：REPL 每用户轮经 `asyncio.run` 新建事件循环，会话级
共享 AsyncClient 的连接池绑死创建时的循环——跨轮复用的首个请求即 `RuntimeError: Event loop
is closed`（暂停恢复/新指令后的轮首必炸，偶发性取决于池中是否有存活连接）。`client()` 取用
时校验循环一致性：不一致即废弃旧实例换新，cookie jar 同步搬运（纯数据可跨循环转移，cookie
型凭证与会话粘性跨轮不丢）

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

**四环防线**（「验证结果正确落到场景包文件」的完整链路；v4.7 前为三环）：

| 环 | 机制 | 落点 |
|---|---|---|
| ① 同构词汇（消除转换需求） | `declare_token` 渲染的 `auth` 段与执行器词汇同构：`token_source` 三态（`Bearer / header:<X> / cookie`）即执行器 `SUTSession.token_type`，cookie 自 Set-Cookie 提取落 `session_cookie` 形态（执行器靠共享 client 的 cookie jar 承载登录态，语义 1:1）；凭证仅 `credential_ref` 引用 | `workbench/sut_probe/tokens.py` |
| ② 工具返回即产物（装配在证据产生处完成一次） | 声明成功时由**工具机械渲染** `sut_config_auth_snippet`（auth: 段 YAML，词汇零翻译）并登记证据账本；Agent 的职责原为「原样粘贴」（v4.7 起由环 ④ 取代——连粘贴也不需要了） | `workbench/sut_probe/tokens.py::_render_auth_snippet` |
| ③ 落盘对账（变形必被打回） | 提交门禁用**执行器同款** `resolve_login_url` 把暂存配置还原成「实际会打到哪个 URL」，与账本逐字段对账（登录 URL/method/body_template/token_path/token_source/expires_in_path；协议核心端点 ✅）——不一致打回并携带权威片段。**对账范围 = 本轮暂存增量**（v4.12.3，验收事故修复：既有包只删一条用例也被要求重做登录实测）：磁盘既有且本轮未动的 sut_config 是此前已落盘放行的结论，不再重复对账；本轮重写但与磁盘基线逐字段相同的 auth（base_url+auth 全等）/ 协议结论（通道+接口域+flavor 三元组全等）同样豁免（无转述变形）；结构性错误（缺 login.path）与未排期通道**无条件打回不豁免**；磁盘无基线（新建包）/ 解析失败保守走全量对账 | `workbench/gates.py::sut_evidence_gate`（取代 `_sut_protocol_gate` 点查） |
| ④ 机械物化（转述通道关闭，v4.7） | `write_sut_config` 从账本 `auth_snippet` **verbatim 注入** auth 段（yaml 语义级与实测一致，非逐字符比对再打回）——jxb 事故中「验证过了又来一遍登录实测」的根因（LLM 抄写 snippet → 对账打回 → 重探成修复环最优解）在机制上消失；修复环只改决策字段，不再重探 | `workbench/tools.py::write_sut_config`（§6.2） |

配套修正：

- **证据账本**：`SUTProbeToolServer` 持有 `_verified_logins`（ref→登录事实）与
  `_verified_protocols`（host→矩阵事实，含失败矩阵）；登记/查询收口 `record/verified_*`。
- **协议假阳性**（`probe/protocol.py`）：3xx 重定向不计 ✅（catch-all 假证据）；建线程失败
  即跳过后续端点并如实记录「未探测」。
- **未知键显式拒绝**（`registry.validate_sut_config_document`）：以执行器 `model_fields`
  为白名单（`extra="allow"` 会静默丢弃发明字段），**递归下钻 `steps[i]`/`steps[i].poll`**（v4.7），
  复用 `SUTSystemConfig` 校验必填/枚举/`${VAR}` 展开；`SUTRegistry.load` 装载卡口同源复检
  （v4.7，违例 raise，见 arch/03 §4.0.3）；staging 与 `scenario validate` 双端接线。
- **URL 解析单源**：`registry.resolve_login_url` 为「配置实际会打到哪个 URL」的唯一真相，
  执行器与落盘门禁共用，永不漂移。
- prompts/guide 同步：auth 段经 `write_sut_config` 机械物化（照抄规约退役）、核心端点 ✅
  才可声明、301 非证据。

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

#### Ctrl+C 五态状态机（v4.12.4，对齐 Claude Code：^C 永远立即生效，中断的是当前活动而非会话）

会话生命周期五个状态下 ^C 走同一条收口（`_attempt` 的暂停语义），此前五态各自演进
（v4.12 → v4.12.1 → …）曾致交互等待期 ^C 被吞成工具 failed 结果回流 LLM——**用户中断
是控制流信号不是工具错误**，宿主桥在终端 I/O 边界把 click `Abort`（Exception 子类）
转回 `KeyboardInterrupt`（BaseException 天然穿透工具层 `except Exception` 兜底）：

| 状态 | 首按 ^C | 再按 ^C |
|---|---|---|
| 空闲提示符（你>） | 清行 +「再按一次退出」armed 提示，**不退出**（输入任意内容即重置） | 退出会话 |
| 生成/工具中 | 立即中断本轮（KI 穿透）→ salvage → 回提示符，部分产出/上下文保留 | 已回提示符 |
| 评测执行中 | 协作中断：当前任务完成后停止（v4.12） | 立即中断（v4.12.1 穿透） |
| 交互选择器（ask_user/授权/确认） | **中断本轮**（Abort→KI 桥；选择器作废，不默认、不放行） | 同左 |
| teardown 瞬态 | SIG_IGN 屏蔽（v4.12.1，护 asyncio.run 收尾毫秒级窗口） | 同左 |

配套裁决：授权/确认类选择器**空回车不再默认放行**（`select(no_default=True)`：host
授权/凭证外发/执行确认/落盘确认，提示改「输入编号」、空输入重问——隐式默认曾是安全
纵伤，编号列表又从未展示默认态）；中断措辞去魔法词（「直接说下一步即可接着干」——
checkpoint 已回对话，任意输入自然续跑，「继续」从来不是机制）。

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
| `agent/workbench/execution/` 包 | 评测执行域（§6.10）：ExecContext + 直通执行工具（list_eval_targets/run_evaluation/list_runs/show_run/upload_run）+ `server.py`；参数对象与 CLI 同构、输出直通、确认门槛永不被信任模式旁路 |
| `agent/workbench/datasets/` 包 | 数据集域（§6.11）：DatasetContext + list_datasets/download_dataset + `server.py`；DatasetManager 单出口受控出网，写面仅 workspace/datasets/ |
| `cli/cmds/workbench_agent.py` | REPL 宿主：流式渲染挂接 / ask 桥 / 中断提示 / 落盘归位 |
| `cli/console/agent_stream.py` | 流式事件渲染（表现层基础设施，与 prompts/render 同层） |
| `cli/console/markdown_lite.py` | 流式正文 markdown-lite 行渲染（标题/粗体/行内代码/列表/围栏保真） |
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
落盘面工具必须以策略形式接入，不得绕过。v4.11 起已实例化两个受控出网域：SUT 探测（§6.5）
与数据集下载（§6.11，host 确认 + 写路径白名单）。

### 6.8 启动横幅与自我介绍

对标 Claude Code 首屏（欢迎框 + cwd + tips）：新用户进入会话先获得一段自我介绍——
我是谁、能做什么、怎么用。

**内容要素**：身份一句话 → 当前任务对象 `{root}` + 能力域 `{domains}` → 使用示例 2–4 条
（须与档位真实能力一致，不得宣传未装配域）→ 红线与确认方式 → 控制方式，顺序固定。

**成稿（场景包域 + SUT 接入调试档位；`{root}` 渲染为实际路径）**：

> 你好，我是 **agent-eval 工作台 Agent**——你用自然语言下需求，我调用工具逐步完成
> 评测工程中的多步操作。
>
> 当前任务对象：`{root}`　　可用能力域：场景包工程 · SUT 接入调试 · 评测执行 · 数据集
>
> 可以这样用我：
> - 「创建一个代码安全评测场景包，被测系统入口 https://…」——给页面登录地址即可，
>   我会探测登录接口与 agent 协议、实测验证后才写入配置
> - 「参照 chat 包，把规则集换成幻觉检测，再加 5 条考卷」
> - 「执行评测」——我列出可执行的场景包给你确认，执行过程与命令行完全一致
> - 「下载 gsm8k 数据集」——确认来源与目录后经白名单源下载
> - 「这个包执行报 404，帮我排查 SUT 配置」
>
> 规则：所有文件改动先进暂存区，给你看 diff、你确认后才落盘；执行评测每次都需你确认后
> 才开始；凭证只在会话内隐藏输入，不写进任何文件或日志。
> 控制：Ctrl+C 随时中断（已完成进度保留，说「继续」接着干），输入空行退出。

**实现要点**：

- 文案落提示词资产独立 `intro` 小节，`intro_text()` 以 `{root}`/`{domains}` 字面 replace
  渲染；CLI 只渲染不写死——新域上线改资产即更新介绍，不改代码。
- 渲染：rich Panel 定宽 ≤100 列（防 CJK 双宽截断），REPL 启动时、会话日志行之前；
  `--json` 与非 TTY 静默跳过。横幅经 **rich Markdown 渲染**（v4.13.1，曾用 `Text`
  纯文本透出 `**` 加粗符）——`intro` 资产按 markdown 语义成稿：条目/段落各占一个
  逻辑行，**句中不加硬换行**（rich 重排把软换行按空格拼接，句中断行会在拼接点
  注入空格；元信息与规则/控制各成条目或独立段落，防并段）。
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

### 6.10 评测执行域（ExecutionToolServer，v4.12）

> 需求 req/04 §4.11（F-C-AGENT-01~06）：统一会话内「执行评测 → 看结果 → 上传」闭环——用户在
> 对话中说「执行评测」，Agent 给出执行候选与摘要，确认后开始执行。核心约束是**输出直通**
> （F-C-AGENT-03）：Agent 发起的执行与命令行执行内容、样式完全一致。

**编排单一真相源（`pipeline_core` 抽取，v4.12 裁决）**：管线编排（解析→凭证→执行→评估→门禁→
报告→上传→退出码映射）此前仅存在于 `cli/cmds/execute.py::execute_pipeline`，且与渲染（rprint）、
退出（typer.Exit）交织——Agent 域若绕开它直拼 `_stages` 阶段函数将成**第三份编排拷贝**，
「与 CLI 逐字节同源」必然漂移。落地形态（方案评审裁决：最彻底方案，否决手拼与直接调 CLI 壳）：

- `cli/_stages.py` 新增 **`pipeline_core(params, *, progress=None, cancel_event=None) -> PipelineOutcome`**：
  无渲染、无交互、无 typer 依赖的编排纯函数（模块既有 rprint/typer 残留不新增）；`params` 与 CLI
  参数对象同构；`progress` 为阶段进度钩子（CLI 壳注入 rprint/进度视图，Agent 域注入**同款渲染**——
  同一钩子契约保证输出一致）；`cancel_event` 供协作式取消（见 Ctrl+C 条）；退出码契约
  （0 成功 / 1 配置执行失败 / 3 门禁未达标）作为 `PipelineOutcome.exit_code` 返回而非 raise；
- `execute_pipeline` **薄壳化**：setup_logging → 调 `pipeline_core` → 渲染（rprint 阶段行/任务表/
  JSON payload/`typer.Exit(code=outcome.exit_code)`）——**CLI 外部行为零变化**（重构验收 =
  既有 CLI 输出回归 + 全量测试）；
- Agent 域 `run_evaluation` 只消费 `pipeline_core`，永不复刻编排。

**模块形态**：`agent/workbench/execution/`，复刻 sut_probe 组合模式（context 共享状态 + 域工具类 +
`server.py` 薄委托壳），「一域一 server」边界不变。

| 工具 | 说明 |
|------|------|
| `list_eval_targets` | 执行候选概要：复用包域 `list_packages` + 选中包的 task_sets/SUT/规则集解析（ConfigLoader 只读）——「执行评测」意图的第一应答 |
| `run_evaluation` | **唯一执行入口**：入参为与 CLI 完全同构的参数对象（package/task_set/sut_config/rule_set/log_level/upload…）→ 直通调用 `_stages` 阶段函数（D-CLI-1 双前端同内核在 Agent 域的延伸）；**调用前必须经 ask_fn 确认**（执行摘要 + 等价命令，`console/equiv.py` 复用）；拒绝即返回 cancelled，不执行 |
| `list_runs` / `show_run` / `upload_run` | 执行后衔接：复用 §7.2 runs 纯函数动作与既有 `upload`（回执附平台 run URL）；Agent 据此做「看结果 / 上传 / 调参重跑」衔接 |

**输出直通机制**（D-CLI-9，需求 2 的落地）：

- `run_evaluation` 是**直通阻塞调用**：执行核心经 **daemon 单飞线程 + `asyncio.wrap_future`**
  在工作线程运行（v4.12.1 起，见硬中断终局条——to_thread 落默认线程池会被 teardown join，
  弃用；不冻结事件循环——ask_fn、流式、Ctrl+C 依赖它）；执行期宿主经 **render_bridge 挂起 Agent 流式渲染**
  （host 每轮构造、ExecContext 持引用注入，与 ask_fn 同模式：suspend 后 `on_event` 事件丢弃、
  rich console 交棒给执行渲染，结束 resume，恢复由宿主单点负责），渲染经 `pipeline_core` 的
  progress 钩子走**与 CLI 同一条渲染路径**（进度视图 + `--log-level` 分档事件行，§4.4）；
  执行期单输出流，终端混排问题结构性消解（req/04 开放问题 #7）；
- **LLM 看不到过程输出、也不转述**：tool 返回值仅紧凑摘要（run_id / 指标 / 失败数 / 产物路径 /
  退出码 / 是否上传）；结束后 Agent 基于摘要做一句总结 + 下一步建议，过程细节由用户回看直通输出或
  `show_run` 追问；
- 非 JSON 形态专用：`--output-format json` 语义仍走 CLI 命令；Agent 会话内执行恒为交互形态，
  `--no-input` 旁路不存在（F-C-AGENT-06：执行工具**永不经 `--trust-agent` 旁路自主触发**，
  不进信任模式工具白名单）；
- **日志档位恢复**：执行按入参档位 `setup_logging` 是进程级全局态——执行结束由宿主恢复会话
  原档位（render_bridge suspend/resume 同点负责）。

**确认与安全门槛**：

- **凭证缺失路径**：`preflight_sut_credentials` 的结构化缺失清单作为 tool 结果返回 → Agent 经
  ask_fn 隐藏输入逐字段引导补录（复用 `ensure_sut_credentials` 的「一次落盘、空输入整体取消」
  语义，§7.2）→ 复检通过重试；_stages 零交互纪律不破——域内交互全部走 ask_fn 单通道；
- **Ctrl+C 语义（v4.12 降级裁决，F-C-EXEC-05 三选询问拆出为 P2 独立立项）**：`pipeline_core`
  任务循环加**协作式取消检查点**（`cancel_event` 任务边界粒度：置位后当前任务跑完即停）——
  Agent 会话内 Ctrl+C = 宿主置位取消令牌并中断本轮，已完成任务产物与 run_manifest 已落盘、
  可溯源（与 CLI 现状一致）；CLI 进程内 Ctrl+C 语义不变（裸中断）。三选菜单落内核后
  CLI / 向导 / Agent 域同步受益；
- **硬中断终局（v4.12.1，实测事故修复：二按 Ctrl+C 后会话报废）**：事故链 = 二按 KI 打断
  `asyncio.run` teardown → `Runner.close` join `to_thread` 默认池（上限 300s，当前任务分钟级
  时终端冻结）→ 连按的 KI 击穿 `run_forever` 登记/清理 running-loop 线程态的窗口 → 泄漏后
  本轮报「Cannot close a running event loop」、后续轮报「asyncio.run() cannot be called from
  a running event loop」。修复三件套：①执行核心改 **daemon 单飞线程**（`_spawn_pipeline_worker` +
  `wrap_future`）——teardown 无可 join，turn 即时收轮，worker 后台到任务边界收尾（cancelled
  产物照常落盘）；②KI/取消后 `active_event` **保留为僵尸 worker 取消通道**（busy 守卫加
  `worker_alive` 双判据 + 下一轮入口 reap 残留令牌，僵尸存活期拒绝并发评测）；③SIGINT handler
  二按前置 `SIG_IGN`（contextmanager 退出复原）——teardown 期屏蔽按键风暴，信号窗口不可再击穿。
  取消粒度仍为任务边界（当前任务不可打断，分钟级收尾属预期，busy 提示如实转述）；
- **预算豁免**：**天然成立**（`BudgetGuard` 仅挂 `on_llm_end` 计会话机 token，`agent/core/callbacks.py`
  ——工具执行不产生会话机 LLM 事件，评测 judge 走独立 client 不经会话回调）；以回归测试断言
  长执行不烧会话预算（F-C-AGENT-04）；执行自身成本由评测配置的 judge 预算管（既有 budget_usd）。

### 6.11 数据集域（DatasetToolServer，v4.11 设计 → v4.13 实施）

> 需求 req/04 §4.12（F-C-DATA-01~04）：CLI 既有 `dataset list/download`（DatasetManager：
> HF/ModelScope 双源 + `assets/datasets/dataset_index.yaml` 索引）接入 Agent 工具面。
> 数据集驱动考卷生成（F-C-DATA-05）为 P2 独立立项，本域只做发现与下载。
>
> **v4.13 已实施**（Sprint 14c）：装配照 §6.10 范式——`WorkbenchAgent` 构造期挂载
> `DatasetToolServer`（workspace 同源 `default_workspace`，事件账本随 agent_logs 同文件），
> `_build_graph` 白名单与 `_describe_tools` 四 server 展平；`WorkbenchAgentConfig` 零改动
> （§6.7 扩展机制第三次验证）。与设计稿的一处收紧：`download_dataset` **不接受 token 参数**
> （设计稿的「token 经 env/secrets 传入」落地为工具签名完全不暴露 token——HF/MS SDK 直读
> 环境变量，红线由签名结构性保证而非运行时校验）。

**模块形态**：`agent/workbench/datasets/`，同组合模式；工具仅两只：

| 工具 | 说明 |
|------|------|
| `list_datasets` | 索引清单（id/名称/类别/双源 repo）+ 本地已下载状态（扫描 `workspace/datasets/` 下 `_dataset_manifest.json` 配对；索引外的本地下载如实列出）。只读，不出网 |
| `download_dataset` | 参数仅 name/source/revision/force；**下载前 ask_fn 确认**（等价 CLI 命令 + 来源 repo + 目标目录 + 已存在跳过/force 语义，二选一）；完成回执 manifest 路径与数据规模（目录字节量） |

**确认门槛（照 §6.10 run_eval 三段式，不可旁路）**：①`ask_fn is None` 即 `refused`
（`--trust-agent` 不旁路——非交互没有确认通道，直接拒绝而非静默执行）→ ③二选一确认，
拒绝则 `DatasetManager` 从未被调用。下载编排与 CLI 同源（`DatasetManager.download`），
经 `asyncio.to_thread` 防阻塞事件循环；失败字段化回执（缺 extras 给安装提示），不打穿会话图。
无 `TOOL_BUDGETS`——确认即预算（同执行域）。

**沙盒与网络边界**（§6.7 红线泛化「host 确认 + 磁盘限额」的实例化，D-CLI-10）：

- **受控出网**：与 SUTProbeToolServer 并列的**第二个网络面**——出网仅经 DatasetManager 单出口
  （HF / ModelScope 域名），域名白名单随 `source` 参数收窄；工具面其余部分维持无网络红线不动；
- **写路径白名单**：仅 `workspace/datasets/{name}/`——独立于包沙盒根的第二写域（包 confined
  会话根语义不变，两域写面互不可达）；工具不暴露 output 参数，落盘收敛由
  `DatasetManager._resolve_target` + `_SAFE_NAME` 结构性保证；
- **token 安全**：数据集访问 token 经 env 传入 DatasetManager（v4.13 起工具签名不暴露
  token 参数），禁止入对话消息、会话日志与工具回执（§6.4 凭证硬拒清单不新增项——token
  根本不进工具层）。

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
| `agent/workbench/execution/` + `agent/workbench/datasets/`（同形态） | 评测执行域（§6.10）与数据集域（§6.11）工具面：直通执行 / 受控出网下载 |
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
| v4.4 | 2026-09-10 | 既有场景包发现修复（用户实测「agent 找不到我创建的包」）：`list_packages` 三源工具（§6.2 新行，与 `scenario list` 同源）+ `read_reference` 纠偏为三源直读；工具面复位中间件（§6.1 新 bullet）剥除 deepagents 内置虚拟 FS 工具（ls/glob 永远为空致误判「没有包」）；prompts 域段包发现/改造规约按来源分流 + intro 示例（§3.5 同步） |
| v4.5 | 2026-09-10 | 变形报文发送前拦截（§6.5 红线 8，jxb-server 422 误诊事故驱动）：request 渲染后 JSON 语义校验（双重编码 str/标量与非法 JSON 拒发 + tojson/dict 指引；数组与非 JSON Content-Type 放行）+ 422 detail type 分诊 next_step（model_attributes_type 读 input 回显 / json_invalid / missing 按 loc）+ 工具描述补 body 单层对象纪律；discover_login 的 OpenAPI 阶梯去兜底门（form 与 schema 证据并列）+ 接口域 openapi 指引 |
| v4.6 | 2026-09-17 | Agent 交互可读性（用户实测反馈「markdown 裸奔」+ 复杂任务缺拆解）：流式正文 markdown-lite 行粒度渲染（§6.1 流式直播段，`console/markdown_lite.py` 新模块，TTY only、围栏保真、Text+span 防 markup 注入）+ TodoListMiddleware 任务清单（§6.1 新段，write_todos 并入工具面白名单、todos 事件提取与渲染、跨段续跑保留）；非流式兜底 `_render_turn` 升级完整 rich.markdown 渲染 |
| v4.7 | 2026-09-17 | 创建流程五阶段重设计（Plan-as-Artifact，jxb agent-safety 包 run 20260917_003025 11/11 run_error 事故驱动，§6.5 新段）：①**SKELETON.md 骨架契约**——事实槽/决策槽机器可检（`- [ ]` 开槽 / `- [x]`+「证据：」闭槽），探测期只写骨架不写配置，「进度即回填骨架」取代「进度即写盘」；开槽门禁（§6.3 新行）+ commit 排除出包、归档 `workspace/agent_sessions/`；②**fact_sink 机械事实行回填**——declare_token/probe_protocol 成功路径经构造注入回调把证据行落骨架（探测面零反向依赖 workbench）；③**`write_sut_config` 机械物化**（§6.2 新行）——auth 段从证据账本 verbatim 注入 + 内联执行器同款校验，「验证过了又来一遍登录实测」在机制上消失（§6.5 防线三环→四环）；④**未知键校验递归下钻 steps[i]/poll + `SUTRegistry.load` 装载卡口**（§6.3 门禁行更新，arch/03 v4.23 同步）；⑤提示词五阶段单线程重构——「工作流程 6 步」与「SUT 接入调试」两份并行指令合一，修复环查骨架不查记忆 |
| v4.8 | 2026-09-17 | 登录探测 422/事件循环/超时三根因修复（jxb 二轮实测事故驱动，§6.5 红线 6/8 更新 + 新段）：①**Content-Type 标签机械归一化**——显式非 JSON CT 旁路 auto 补齐与双重编码门禁，正确 JSON 报文顶着 text/plain 上 wire 致 FastAPI 422 `model_attributes_type`（input 原文回显形似双重编码，服务端排查见「json 不是 json、内容加了引号」）；JSON 对象 body 的标签机械改写（返回含 `content_type_normalized`），原始报文探测不收缩；同批修复渲染头整行回填缺口（wire 收到 `Key: Key: Value`）；②**共享 client 事件循环亲和**——REPL 每轮 `asyncio.run` 换循环 × 会话级 client 绑死旧循环 = 跨轮首请求 `Event loop is closed`，`client()` 按循环废弃旧实例换新、cookie jar 同步搬运；③**超时错误面代理指引**——本机代理把 0.3s 请求拖到 11.7s 顶爆 10s 探测超时，指引配 `NO_PROXY`；④**`declare_token` 静态注入通道**（`static_field`）——用户直接提供的 token 自密钥区挂载，解除「无实测记录即永远 auth_attached:false」死循环；不入证据账本、不生成 auth: 段（落盘对账的实测证据语义不被稀释） |
| v4.9 | 2026-09-17 | **落盘即归位**（用户实测反馈「确认后预告路径找不到包，须 Ctrl+C/空行退出才归位」，§6.3 重写）：首次确认落盘成功即把草稿挪到 `cwd/<id>-package/`——`PackageToolServer.rebind_root` 沙盒重定向（staging 内存态、root 无持久句柄，零残留）+ `WorkbenchAgent.relocate_root` 图重建（`{pkg_root}` 建图烘焙，对话消息宿主持有不丢）+ 归位注记进对话 + 会话记录文件随迁新 `session_key`（跨进程续作上下文不因归位断裂）；**同一会话可继续自然语言修改已归位的包**；`_finalize_new_package` 收窄为会话末兜底 + 改名同步（已归位未改名静默返回）；撞名红字报错留草稿位不打断会话；确认横幅/落盘提示同步新时序 |
| v4.10 | 2026-09-17 | **写包链路系统性修复**（jxb-agent 创建会话转录复盘，§6.3 门禁族表 +1 行、中断续作要点重写）：①`update_manifest` 结构修复——曾手拼 `"package:\n" + safe_dump(扁平dict)` 落盘零缩进损坏清单（read_manifest 的 get 回退把坏结构读回「自洽」致 bug 隐身），改为 dump `{"package": merged}` 嵌套结构自带缩进；②**YAML 全量解析双防线**——`write_file` 对 `.yaml/.yml` fail-fast 预检（截断当场拒写未入暂存）+ `validate_package` 全视图解析打回（曾只扫 `rules/`，截断的 task_sets 靠 Agent 自检才发现）；③**跨进程续跑**（五阶段计划推迟的 MR4 落地）——每轮会话记录同步写入进度快照（暂存 + SKELETON.md 留档 + 证据账本，凭证态绝不入快照），重启续作自动恢复并向对话注入进度注记——「重启会话续作」从进度陷阱变为真实承诺，write_sut_config 免重探跨进程成立 |
| v4.11 | 2026-09-20 | **评测执行域 + 数据集域 + 日志四档**（req/04 v1.6 用户需求四则，新 §6.10/§6.11/§4.4 + D-CLI-9/10）：①**评测执行域**——ExecutionToolServer（list_eval_targets/run_evaluation/list_runs/show_run/upload_run），统一会话内「执行→看结果→上传」闭环；**输出直通**（D-CLI-9）：执行期挂起 Agent 流式渲染、rich 直出与 CLI 同一渲染路径，LLM 只见紧凑摘要不转述；执行确认门槛永不被 `--trust-agent` 旁路、凭证缺失经 ask_fn 补录、Ctrl+C 按阶段路由、执行不计会话预算；②**数据集域**——DatasetToolServer（list_datasets/download_dataset 复用 DatasetManager），与 SUT 探测并列的**第二个受控出网域**（D-CLI-10 白名单制实例化）：域名白名单 + `workspace/datasets/` 写白名单 + token 不入对话/日志；③**`--log-level` 四档**（quiet/normal/verbose/debug）取代 `--verbose`，三形态（CLI/向导/Agent）同源，verbose 档补 SUT 请求响应摘要/judge 交互/重试事件埋点（只加事件不改指标逻辑）；会话机四工具面并列、横幅能力域/示例同步、`WorkbenchAgentConfig` 不变（新域零会话机改动，验证 §6.7 扩展机制） |
| v4.12 | 2026-09-20 | **14b 设计评审裁决（req/04 v1.7）**：①**编排单一真相源**——新增 `pipeline_core`（§6.10）无渲染编排纯函数 + `PipelineOutcome`（退出码返回而非 raise），`execute_pipeline` 薄壳化（CLI 行为零变化为重构验收），Agent 域 `run_evaluation` 只消费 pipeline_core——否决「直拼 `_stages` 阶段函数」（第三份编排拷贝，逐字节同源必漂移）；②**直通机制补注**——`asyncio.to_thread` 包裹同步执行内核（事件循环保活性）+ render_bridge 注入接口（host 每轮构造、ExecContext 持引用，与 ask_fn 同模式）+ 执行后日志档位恢复；③**Ctrl+C 降级**——`pipeline_core` 任务循环协作式取消检查点（cancel_event 任务边界粒度），F-C-EXEC-05 三选询问拆出 P2 独立立项（先落内核，三形态同步受益）；④预算豁免确认为天然成立（BudgetGuard 仅 on_llm_end），收敛为回归断言 |
| v4.12.1 | 2026-09-20 | **硬中断终局隔离（14b 验收实测事故修复）**：执行核心 `asyncio.to_thread` → daemon 单飞线程 + `wrap_future`（teardown 零 join，二按 KI 后 turn 即时收轮、worker 后台到任务边界收尾）；KI/取消保留 `active_event` 作僵尸 worker 取消通道（busy 守卫 `worker_alive` 双判据 + 下一轮入口 reap）；SIGINT handler 二按前置 `SIG_IGN`（teardown 期屏蔽按键风暴，退出复原）——三件套合围「Cannot close a running event loop」会话报废链（§6.10 硬中断终局条）；取消粒度维持任务边界不变 |
| v4.12.2 | 2026-09-20 | **既有包轻量编辑路由修复（用户验收反馈：加 1 条用例触发全建包流程）**：①新增 `edit_package` 会话目标切换工具（§6.2 新行）——非交互/builtin/staging 非空多级守卫 + ask_fn 确认 + 骨架归档/授权账本清账 + `relocate_root(note=…)` 切根（会话记录随迁，注记进对话）；②`relocate_root` 参数化注记（归位/切根同一机制、语义注记区分），`relocate_fn` 构造后注入（与 ledger 同风格解环）；③prompts「改造已有项目包」三档分流重写——**轻量修改默认档 = 会话内 edit_package 原位编辑**（不落骨架/不起五阶段/不 fork/不重测 SUT），fork 仅限明确要新版本/新包，删除「首选指引退出本会话」（`scenario edit` 降级为等价通道提及）；五阶段适用边界置顶（从零建新包 / 新接入在线 SUT）；④`list_packages` notes 同步改路由。`WorkbenchAgentConfig` 零改动（§6.7） |
| v4.12.3 | 2026-09-20 | **既有包编辑证据门禁豁免（用户验收反馈：只删一条用例仍触发凭证重验）**：①**对账门禁收窄至暂存增量**（§6.5 ③，回归文档原意）——`sut_evidence_gate` 遍历源 view() → staging，磁盘既有未动的 sut_config 不再重复对账；与磁盘基线逐字段全等的 auth（base_url+auth）/ 协议结论（通道+接口域+flavor 三元组）豁免，结构性错误与未排期通道无条件打回、磁盘无基线保守全量对账（新建包行为不变，安全属性不降）；②**切根保育**（§6.2）——`relocate_root` 目标记录已存在时不覆盖：目标对话并入 + 账本快照合并恢复（曾静默清零对话史+账本）；③横幅文案按草稿前缀区分「归位/原位落盘」（edit_package 原位场景曾误称归位）；④prompts 豁免规约——不因对账提示重探登录、不发起「允许/不允许」类确认（该询问无代码消费，属无效解锁动作）；⑤edit_package 尾部不可达残段清理（v4.12.2 编辑事故善后） |
| v4.12.4 | 2026-09-20 | **Ctrl+C 五态语义统一（用户验收反馈：凭证外发确认上 ^C 无法中断，空回车落默认「允许」放行真外发）**：①**交互桥 Abort→KI**（§6.6 新增五态状态机表）——ask_fn/_cli_confirm 桥把 click `Abort`（Exception 子类，曾被工具层 `except Exception` 吞成 `{"type":"Abort","message":""}` 回流 LLM 诱发重试、SIG_IGN 滞留整轮后 ^C 全面失效）转回 `KeyboardInterrupt` 穿透工具层直达 turn() 统一暂停语义；②turn() KI 归 reason=interrupted（曾落 error）；③`_json_tool` 空 message 回退类名；④空闲提示符 ^C 二按退出（首按 armed 提示不清场、输入即重置，曾一次 ^C 即退会话——对齐 Claude Code）；⑤授权/确认类选择器空回车不再默认放行（`select(no_default=True)`：提示改「输入编号」、空输入重问——隐式默认曾是安全纵伤）；⑥中断措辞去魔法词（「直接说下一步即可接着干」）。普通 CLI 命令 Abort→exit 130 语义零变化 |
| v4.13 | 2026-09-21 | **数据集域实施（Sprint 14c，§6.11 v4.11 设计稿落地，req/04 §4.12 F-C-DATA-01~04）**：`agent/workbench/datasets/` 第三域包（DatasetToolServer：list_datasets/download_dataset）——workbench 会话内「查 → 下」评测数据集（「下载 gsm8k 数据集」即用）；**第二受控出网域**兑现（D-CLI-10）：出网仅经 DatasetManager 单出口、写路径白名单 `workspace/datasets/{name}/`、下载确认照 run_eval 三段式不可旁路（ask_fn None 即 refused）；**较设计稿收紧**：工具签名不暴露 output/token 参数（写白名单与 token 红线由签名结构性保证，HF/MS SDK 直读环境变量）；equiv 单点新增 `dataset_argv`（子命令+位置参数形态）；prompts 增「## 数据集」段 + intro 示例；`WorkbenchAgentConfig` 零改动（§6.7 扩展机制第三次验证）。F-C-DATA-05（数据集驱动考卷生成）维持 P2 独立立项不承诺 |
| v4.13.1 | 2026-09-21 | **启动横幅 Markdown 渲染（用户验收反馈：横幅以纯文本透出 `**` 加粗符）**：`_render_intro` 渲染器 `Text` → `Markdown`（与非流式回复同源）——加粗/列表/链接生效；配套 `intro` 资产按 markdown 语义成稿（§6.8）：元信息与示例成列表条目、规则/控制独立段落，**句中不加硬换行**（rich 重排把软换行按空格拼接，句中断行会在拼接点注入空格；实测「当前任务对象/可用能力域」「规则/控制」并段）。回归测试守卫：标记不透出、列表成条目、两处不并段 |
