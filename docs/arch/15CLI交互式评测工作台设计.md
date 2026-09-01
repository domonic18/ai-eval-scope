# CLI 交互式评测工作台设计

> 本文档是 [04 CLI 交互式评测工作台需求](../requirement/04CLI交互式评测工作台需求.md) 的架构落地：向导式工作台（`start`）、命令体系重构（直接切换）、账号与浏览器联动（`auth` / `open`）、PackageAgent（场景包工程 Agent）、结果浏览（`runs`）。
>
> 定位为 **CLI 表现层 + 交互编排层** 设计：与 [02 编排调度层设计](./02编排调度层设计.md) 共用既有编排阶段（`cli/_stages.py`）；Agent 底座复用 [03 执行引擎设计](./03执行引擎设计.md) §3.2；配置面遵循 [06 数据管理与配置规范](./06数据管理与配置规范.md) §四；场景包规范遵循 [13 配置管理设计](./13配置管理设计.md)；平台账号对接 [09 Web 可观测平台架构设计](./09Web可观测平台架构设计.md)。

---

## 一、设计目标与范围

### 1.1 设计目标

| 需求目标 | 设计要点 |
|---------|---------|
| G1 全生命周期闭环 | 工作台四域（场景包/执行/结果/账号配置）统一入口；全部动作下沉到既有编排与内核 |
| G2 场景包 Agent 化 | PackageAgent 复用 DeepAgents 底座 + 独立沙盒工具面 + 校验门禁（§六） |
| G3 零门槛交互 | 向导原语库（选择/确认/输入）+ preflight 引导链 + 等价命令显示（§三） |
| G4 脚本/CI 友好 | 非 TTY 降级、`--no-input`、`--output-format json`、退出码集中映射（§4.3） |
| G5 单一事实源不变 | 配置仍落 llm.json / sut_credentials.json / platform.json（密钥区三文件）+ .env（开关与直供）；包结构仍走 13 规范 |
| G6 命名语义清晰 | `models set/clear`、`scenario *`、`auth *`、顶层 `doctor`；一次性切换无兼容层（§4.2） |

### 1.2 范围

- **含**：向导框架（workbench）、命令重命名落地清单、auth 浏览器配对与 `open` 的 CLI 侧实现、PackageAgent（组装/工具面/门禁/日志）、`scenario show` 与 `runs` 的本地数据读取、退出码与 JSON 输出规范、平台侧配对端点的**接口约定**（P2）。
- **不含**：平台侧 `/cli-auth` 授权页与设备码端点的实现（09 侧落地，本文仅约定契约）；评测内核与指标逻辑变更；全屏 TUI（远期）；`scenario push`（包发布通道）。

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
   PackageAgent（DeepAgents，独立于执行侧 SUTToolServer）
```

### 2.2 模块布局

CLI 目录按「**装配单点 / 命令薄壳 / 表现层基础设施 / 向导层**」四区组织，子命令组统一收入 `cmds/`，交互基础设施统一收入 `console/`：

```
agent_eval/cli/
├── __init__.py        # 唯一装配点：顶层命令 app.command()() + 子命令组 add_typer
├── main.py            # 引导（dotenv/评估器注册/app/全局 callback）+ 轻量命令
│                      #   version/start/open/doctor（~90 行，无业务体）
├── _stages.py         # 编排阶段（既有：解析/执行/评估/收尾；零交互，向导复用）
├── _common.py         # 跨组共享工具：LLM Judge 初始化 / 摘要 / 推送 / 凭证保障
│
├── console/           # 表现层基础设施（无业务语义，命令层与向导层双向复用）
│   ├── prompts.py     # 向导原语：select/confirm/ask/resolve_bypass + --no-input 旁路
│   ├── render.py      # rich 渲染：stage_progress（阶段级进度，stderr 绑定）/ 任务状态表
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
    ├── scenario.py    # 原 package.py 改名迁入：new/show/validate/list/pull
    ├── models.py      # set/list/test/clear（原 login/logout 改名）
    ├── runs.py        # list/show（无参交互选择）
    ├── open_url.py    # open <target>（平台 URL 构造 + webbrowser 单出口）
    ├── doctor.py      # doctor（检查项编排）
    ├── auth.py        # login/status/logout/register（Sprint 11）
    └── secrets.py / suite.py / dataset.py / knowledge.py / rule_set.py   # 既有迁入

agent_eval/agent/
├── package_agent.py   # 新增：PackageAgent 组装（create_deep_agent + build_chat_model）
├── package_tools.py   # 新增：PackageToolServer（沙盒六工具，独立于 sut_tools.py）
└── assets/configs/package_agent_prompts.yaml   # System/Task Prompt 资产
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
| D-CLI-1 | **双前端同内核**：向导动作最终组装与命令行相同的参数对象，直接调 `_stages` 阶段函数；向导内不出现第二份业务逻辑 | P1 原则；等价命令显示天然成立（argv 即真相） |
| D-CLI-2 | **交互原语收口 `console/prompts.py`：P0 以编号选择落地（gcloud 同款，零新依赖）；questionary + rich 为 P1 可选升级**（分页/搜索需求出现时） | 零依赖先行 + 升级路径保留；原语签名不变，替换不动调用方 |
| D-CLI-3 | **PackageAgent 独立工具面**（`package_tools.py`），不复用 SUTToolServer | 两域工具语义无关（文件编辑 vs SUT 交互）；沙盒约束不同（包根 vs workspace） |
| D-CLI-4 | **平台身份落密钥区 `~/.agent_eval/platform.json`**（host/api_key/project，0600），CLI 启动注入 env **仅补缺**——env 直供（CI/云函数/executor/`.env`）优先；`.env` 归用户手工管理，残留旧值检测提示不代删 | 三域三文件与 `models`（llm.json）/`secrets`（sut_credentials.json）对齐（06 §4.7）；「登录 A 实际上报 B」的静默错乱由 env 优先 + 提示兜底 |
| D-CLI-5 | **浏览器打开统一走 `cmds/open_url.py`**：`webbrowser.open`（`$BROWSER` 可指定浏览器）+ 无浏览器环境（SSH/未设 `$BROWSER`）降级打印 URL | gh `pkg/browser` 同款行为；单一出口便于 mock 测试（NF-C-05） |
| D-CLI-6 | **重命名一次性直接切换**，无别名层 | 用户基数小（需求 v1.2 决策）；收尾要求 = 全仓引用同版本清理 |
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
| `select(options)` | 编号列表 + 回车（P0；P1 可升级 ↑↓ 键盘导航） | `--no-input` 下 env/default 旁路，缺失 → exit 2；管道输入正常提示 |
| `confirm(q)` | y/n | 读 `--yes`/env，缺省即错 |
| `input(hide=)` | 文本（可隐藏回显） | 读参数/env，缺省即错 |
| `stage_progress` | 阶段级 spinner（stderr 绑定，transient）| 单行阶段提示到 stderr；--json 下禁用 |
| `print_task_table` | 完成态逐任务状态表（进度视图回落摘要） | 正常输出（rprint） |

全部原语收口 `console/prompts.py`，签名统一带 `default`/`env_key` 旁路参数（P2 原则），测试经依赖注入 mock。

### 3.3 preflight 引导链

进入工作台与各域动作前按序检查，产出 `Guidance(label, fix_action)` 列表渲染为菜单项：

```
平台未登录 → auth login ／ 模型未配置 → models set ／
SUT 凭证缺失 → secrets set <ref>.<field> ／ 无项目包 → scenario new 或选内置包
```

### 3.4 等价命令显示

`console/equiv.py` 维护「动作 → argv 构造器」映射表；向导确认页渲染 `等价命令: agent-eval pipeline --package chat ...`。argv 由向导已收集的参数组装而成——与实际执行的参数对象同源（D-CLI-1），不会漂移。

---

## 四、命令体系与重命名落地

### 4.1 typer 应用结构（目标态）

```python
# cli/__init__.py —— 唯一装配点
from agent_eval.cli.cmds import (auth_app, dataset_app, knowledge_app, models_app,
                                 rule_app, runs_app, scenario_app, secrets_app, suite_app)
app.add_typer(scenario_app)   # 原 package_app：new/edit/show/validate/list/pull
app.add_typer(models_app)     # set/list/test/clear
app.add_typer(auth_app)       # login/status/logout/register
app.add_typer(runs_app)       # list/show
app.add_typer(secrets_app); app.add_typer(suite_app); app.add_typer(rule_app)
app.add_typer(dataset_app);  app.add_typer(knowledge_app)
# cli/main.py 顶层：eval/run/pipeline/pack/upload/version + start/open/doctor
```

### 4.2 重命名落地清单（一次性切换）

| 代码点 | 改动 |
|--------|------|
| `cli/package.py` → `cli/cmds/scenario.py`（随目录重组迁入） | 组名 `package`→`scenario`；`init` 并入 `new --mode skeleton` |
| `cli/models.py` → `cli/cmds/models.py` | `login`→`set`、`logout`→`clear`；内部逻辑不变，文案随动 |
| `packages/assets.py` 等报错文案 | `arch/13 §4.1` 字样与命令名同步 |
| 引用清理 | `docs/guide/CLI使用教程.md`、根/子项目 README 与 CLAUDE.md、`cicd/` Jenkins 片段、`web/` 调试台提示、`executor/` 内部调用、单测断言 |

验收口径：全仓 `grep -r "agent-eval package \|models login\|models logout"` 清零。

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

### 5.1 `auth login` 流程（P1 双通道）

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
- `auth status`：读 `.env` → 平台 ping → 身份回显；`auth logout`：清除 `.env` 三项（`--revoke` 吊销为 P2，需平台删除 Key 端点授权）。

> **Sprint 11 落地形态（2026-09-01）**：身份探测端点已实现——`GET /api/public/whoami`（Bearer API Key，返回 `{kind, key:{name,scopes}, project:{id,name,slug}, org:{id,name,slug}}`）；前端暂无独立 Keys 页与 `/cli-auth` 授权页：通道 A 打开 `{host}/login` 并引导至项目「设置 & API Key」页创建 Key，通道 B 待平台侧落地（P2）。CLI 对 404（旧平台无 whoami）回退 `GET /api/public/secrets` 轻探测——Key 有效但身份未知，回执降级不阻断登录。身份持久化于 `~/.agent_eval/platform.json`（0600，`AGENT_EVAL_PLATFORM_CONFIG` 可覆盖），CLI 启动 `apply_platform_env` 注入进程 env **仅补缺**（CI/云函数/executor env 直供与 `.env` 显式配置优先）；`.env` 归用户手工管理，登录/登出检测到残留平台配置即提示（env 优先将覆盖密钥区），不代为删改。

### 5.2 设备码流接口约定（P2，平台侧落地）

| 端点 | 契约（对齐 [RFC 8628](https://www.rfc-editor.org/info/rfc8628) 设备授权语义） |
|------|------|
| `POST /api/v1/cli/pair` | 无鉴权（限流）；返回 `{user_code, verification_uri, interval, expires_in}`（≤600s，一次性） |
| `GET /api/v1/cli/pair/{user_code}` | CLI 按 `interval` 轮询（默认 2s；返回 `slow_down` 时 interval +5s）；状态机：`authorization_pending` / `slow_down` / `expired_token` / 成功一次性返回 `{api_key, org, project}`（再查 404） |
| `verification_uri` 授权页 | 登录态 + 展示 `user_code` 供核对 + 确认按钮 → 调内部授权完成接口 |

> 语义对齐 RFC 8628 的价值：未来平台接入标准 OAuth/OIDC 设备流（或复用现成服务端实现）时，CLI 端轮询状态机无需重写。

安全约束：配对码短时效、一次性、绑定发起会话 IP 提示展示；Key 首次返回后不可再查。

### 5.3 `open <target>` 与 `--web`

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

## 六、PackageAgent

### 6.1 组装

```python
def create_package_agent(pkg_root: Path, *, budget_usd: float = 0.5) -> PackageAgent:
    model = build_chat_model(llm_role="agent")        # 回退 text（llm_resolution 既有语义）
    tools = PackageToolServer(pkg_root).to_langchain_tools()
    prompts = load_package_agent_prompts()            # assets/configs/*.yaml，fail-fast
    agent = create_deep_agent(model=model, tools=tools,
                              system_prompt=prompts.system, checkpointer=None)
```

- 一次性会话不挂 checkpointer；BudgetGuard 会话级预算（默认低于执行 Agent）；tool_guard 范式沿用（工具异常转 failed 结果交 Agent 决策，不中断图）。

### 6.2 工具面与沙盒（PackageToolServer）

| 工具 | 实现要点 |
|------|---------|
| `list_package_files` / `read_file` | 限包根；read 截断长文件（防上下文爆炸） |
| `write_file` / `delete_file` | **先写暂存区**（内存/临时目录），不直接落盘——diff 确认与校验门禁通过后才由宿主提交（§6.3） |
| `read_manifest` / `update_manifest` | manifest 读写同样走暂存 |
| `validate_package` | 对暂存后的包快照执行 Schema + 语义校验，返回结构化 errors |
| `search_reference` | 检索内置包（courseware/chat/code）+ [14 指南](./14场景扩展指南.md)要点 |
| `read_reference` | 只读内置包文件内容（ref + 包内 path）——Agent 参照真实格式的**合法通道**（`read_file` 限本包，曾实测 Agent 试图借它读包外路径被拒后反复试探） |
| `preview_diff` | 暂存区 vs 磁盘原文的统一 diff |

**沙盒规则**：路径 `resolve()` 后必须 `is_relative_to(pkg_root.resolve())`（防 `..` 与 symlink 逃逸）；写操作扩展名白名单 `.yaml/.yml/.json/.md`；无 shell、无网络、无包外路径。

### 6.3 会话状态机

```
用户需求 → [计划] Agent 输出改动计划（文件清单+意图）→ 用户确认
        → [生成] Agent 调工具写暂存区 → preview_diff 展示
        → [确认] 全部 / 逐文件 / 放弃（放弃=清空暂存，磁盘未动）
        → [门禁] validate_package(暂存快照)
             ├─ 通过 → 宿主提交暂存到磁盘（原子替换）→ 记录会话日志
             └─ 失败 → errors 注入 Agent 自修复（≤3 轮）→ 仍失败交还用户
```

关键不变量：**磁盘上的包在任何时刻都只见过「用户确认 + 校验通过」的内容**。

### 6.4 安全红线实现

- sut_config 内容扫描：出现 `password/token/api_key` 值字段且非 `credential_ref` 引用 → 拒绝写入并提示 `secrets set`（启发式 + System Prompt 双保险）。
- `scenario edit --instruction ... --yes --trust-agent`：非交互模式必须双重显式旗标；默认关闭。
- 会话日志 `workspace/agent_logs/package_agent_<ts>.jsonl`：消息、工具调用与参数（凭证字段脱敏）、token、耗时。

### 6.5 落地注记（2026-08-31，feat/package-agent）

- 实现：`agent/package_tools.py`（§6.2 工具面十工具，staging 暂存 dict）+ `agent/package_agent.py`（`turn()` 会话 / 门禁回改 / jsonl 日志）+ 提示词资产 `assets/configs/package_agent_prompts.yaml`（字面 replace 渲染——模板内大括号均为字面内容，非 format 占位）。
- **流式直播**（用户实测反馈补齐）：`_invoke` 改走 `astream(messages/updates/values)` 三模，事件流（`thinking` / `token` / `tool_start` / `tool_end` / `phase` / `tool_args`）实时回调，CLI 按 claude code 式渲染（✻ 思考 dim、🤖 正文直出、🔧 工具行带关键参数）；输入后立即显示 ⏳ 工作中提示。兼容两形态：KIMI/Claude 系增量 chunk 的 `type` 为 `AIMessageChunk`（非 `"ai"`）且 content 为 blocks（thinking/text 段分列）——真机实测两坑。
- **流式观感两修**（第二轮实测反馈）：① 模型 text/thinking 段常以 `\n\n` 开头，直接拼接会出现「🤖 后空行」——段首空白吞掉，段内换行保留；② 大文件内容在 tool_call args 里增量生成（不走 text 流），数十秒无输出形同「卡住」——`tool_args` 事件以 `\r` 单行进度实时显示「⏳ write_file 生成参数中 · N 字」（仅 TTY；非 TTY 静默）。
- **中断语义**：Ctrl+C 中断当前轮——暂存清空 + 历史截断（磁盘从未见过本轮内容），会话不退出可继续输入；协内以 `CancelledError` 呈现（测试勿直抛 `KeyboardInterrupt`，Runner 的 SIGINT 机制会死循环）。
- 偏差：预算暂以 `recursion_limit = max_turns × 2` 约束，BudgetGuard 会话级预算待逐任务预算需求出现接入；确认粒度为「全部应用/放弃」整轮确认，逐文件确认（§6.3）未做。
- **首轮错误遏制**：REPL 首轮（`--instruction`）与后续轮同走 `_attempt()` 防护——瞬时错误（LLM 网关断流等）打印失败原因 + 回滚提示后会话不退出，可直接重发上一条需求（真机曾因首轮回溯击穿整会话）。
- **YAML 资产门禁**：Agent 曾把提示词写成 README 式 `.md`（加载器只认 `.yaml`，静默失效 `prompts=0`）——`validate_package` 与 `scenario validate` 双端要求 `rules/` 与 `prompts/` 各含 ≥1 个 `.yaml`，错误交 Agent 会话内自修复；真机复测 `rules=1, prompts=1` 通过。
- **生成即发现**（第三轮实测反馈「执行评测选择器只见预置包」）：`PackageStore` 增第三来源 **project**——项目根（默认 cwd，`AGENT_EVAL_PROJECT_DIR` 覆盖）与 `workspace/scenario-packages/` 双根一级子目录扫描（含 `agent_eval.yaml` 即项目包，source=`project`；仅扫一层防内置包经 `assets/packages/` 重复发现；Agent 生成包默认落 scenario-packages——**该默认已于 2026-09-01 修订为 cwd 直出，见下**）。`PackageManager.list/find` 单点打通：工作台执行域与 `scenario show/edit` 选择器、`eval/run/pipeline` 的 `--package` 解析全部直达刚生成的包；单测 conftest 钉 env 隔离开发者 cwd 实包。
- CLI：`scenario new --mode agent`（REF 可省——用户实测反馈「先问包名不友好」：省略时 Agent 按需求拟定引用并在计划首行给出，会话中自然语言可改，会话结束按**最终清单 id** 归位 `workspace/scenario-packages/<id>-package/`——**该落点已于 2026-09-01 修订，见下**）；给了 REF 则钉入模板不得自拟、默认同上）与 `scenario edit`（内置包只读拒绝，指引 `new --instruction "参照 <ref> 定制…"`；交互选择器过滤内置包并给路径输入入口）；workbench 场景域两项入口（生成新包不再前置询问包名）；REPL 缺省 + `--instruction --yes --trust-agent` 非交互双开关。
- **落盘位置改 cwd 直出**（2026-09-01，PyPI 直装用户实测反馈「包写到了 /tmp、最终位置与预期不符」——形态 B）：场景包是**源资产**（考卷/规则/SUT 配置，用户要编辑、可团队共享），与 `workspace/`（运行产物区，gitignore）归属不同；行业脚手架惯例（cargo/npm/create-vite）一律 cwd 直出。落地：
  - Agent 会话在 `workspace/.staging/agent-eval-pkg-<rand>/` 草稿区进行（同卷 `shutil.move` 原子归位），结束后按最终清单 id 归位 **`cwd/<id>-package/`**——与 skeleton 模式 `./<id>/` 方向一致；给了 REF 直接定址 `cwd/<id>-package/`
  - **中断 ≠ 放弃**：异常退出不清理草稿（原逻辑清单未落盘即 rmtree），提示 `scenario new --mode agent --output <草稿路径>` 续作；`--output` 显式指定时非空目录放行（续作场景），默认路径仍要求空目录
  - **归位冲突报错保留草稿**（原逻辑静默留在生成位置）：目标已存在 → Exit(1) + 交用户处置（换名/手动 mv）；清单未落盘同理保留草稿不再删除
  - **git 视野**：仓库 `.gitignore` 加 `/*-package/` 与 `evaluator/*-package/`（实验态默认忽略；转正式资产 `git add -f` 或迁 `assets/packages/` 随包发布）；工具不改用户 .gitignore，仅在收尾提示建议行
  - `scenario_packages_root()` 降级为兼容扫描根（旧包不搬家仍可见），`list_project` 双根发现不变
- 验证：单测 mock `_invoke` 回放状态机 + `_FakeGraph` 流式事件（沙盒逃逸/凭证明文/门禁回改/放弃回滚/原子落盘/中断回滚/blocks 解析）；真机 KIMI 端到端冒烟（一句话生成合法包、一句话改字段，思考/正文/工具全程直播）。

---

## 七、查看与结果浏览

### 7.1 `scenario show`

`PackageManager` 只读解析（内置/项目/本地仓库三源统一）→ 分区渲染：结构树（`tree`）、规则集表（`rules`：id/评估器/tier/weight/enabled）、考卷预览（`tasks`：任务数 + 首 N 条）、SUT 概览（`sut`：通道/端点/鉴权策略/`credential_ref` + 凭证就绪态，不显示值）、清单（`manifest`）。数据零新解析器，复用 ConfigLoader 与 manifest 模型。

### 7.2 `runs list / show`

- `list`：直接扫描 `workspace/runs/` 目录（manifest + summary 即读）→ 表格（run_id/模式/**状态**/包/任务数/Reward）。状态推导：`已评估`（有 summary）→ `已执行⚠/已执行`（有清单，⚠=日志含错误）→ `执行失败`（无清单但 agent_logs 有 error 事件）→ `中断`（无产物）。
- `show <run_id>`：直读 run 目录 → 指标卡按 `metric_definitions` 动态渲染（不硬编码）；失败 breakdown TopN。**无报告时不再是干巴巴一句「无 summary.json」**：展示状态 + 从 `agent_logs/*.jsonl` 提取最后一条 error 的失败原因；凭证类错误附 `secrets set <ref>.<field>` 录入指引；已执行未评估给出补评估命令。
- 配套（2026-08-31 实测反馈修复）：执行前**凭证预检**（`preflight_sut_credentials`，按 `auth.type` 逐字段 require）——缺凭证立即失败并给出录入命令，不再进 Agent 循环换通道试探烧完 `max_turns` 才以「超过轮次限制」收场；`run`/`suite` 的 workspace 根统一走 `paths.default_workspace`（`WORKSPACE_DIR` 生效），消除与 `runs list`/`pipeline` 各读各的漂移（此前还把 pytest 执行段漏进真实 workspace）。
- **缺失自动补录**（req/04 §3.5，S11）：`ensure_sut_credentials`（落 `_common.py`，跨组共享）挂在 **run/pipeline/suite 命令层、进度视图启动前**（`execute_stage` 保留纯 `preflight_sut_credentials` fail fast 兜底）——探测走非抛错的 `missing_credential_fields`（与预检同源 `required_credential_fields`，数据驱动），缺失时交互终端列出缺失项 → 确认 → 逐字段隐藏输入 → **一次落盘**（空输入整体取消，不留半截状态）→ 复检通过即继续执行；取消/`--no-input`（CI）退回原 fail fast（SUTAuthError 带 `secrets set` 引导），云端 executor 不经此路径（env 注入，`orchestrator.eval_packages` 独立编排）。**挂点必须在 stage_progress 之外**（实测反馈）：进度转轮单行重绘会把输入提示行刷掉——补录提示被「执行 N 个任务」掩盖，用户不知该输入；同时补录前置于 run_id 生成，取消时不留半截运行目录。

---

## 八、非功能实现要点

| 项 | 实现 |
|----|------|
| 性能 | `start` 惰性导入（questionary/deepagents 按域加载）；进度视图 rich 单行重绘 |
| 安全 | `.env` 0600；配对码一次性短时效；凭证不进对话/diff/日志（脱敏钩子在工具层） |
| 可靠性 | LLM 不可用：执行路径零影响（既有 SKIP 降级），PackageAgent 报错并指引模板路径；浏览器不可用降级打印 URL |
| 可测试 | console/prompts 原语 mock 注入；退出码/JSON 契约测试；PackageAgent 以 mock LLM 回放（禁联网）；open_url mock（测试不开真浏览器） |
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
| 浏览器登录 | P1 配对码粘贴；P2 设备码轮询 | gcloud / gh / stripe：RFC 8628 设备授权（user_code + verification_uri + 轮询状态机） | ✅ P2 契约对齐 RFC 8628 语义（§5.2） |
| 机器可读输出 | `--output-format text\|json` + stderr 分流 + 退出码 0/1/2/3/130 | kubectl `-o` 打印器族；gh `--json` 类型化字段；sysexits 传统 | ✅ 双格式够用，需要 yaml/表格再扩 |
| 查看即网页 | `--web` / `open` | `gh <entity> view --web`、`vercel open` | ✅ 一致 |
| 首用引导 | preflight 引导链 | gh 主动 auth 提示；`gcloud init` 向导 | ✅ 一致 |
| 命令插件化 | 不做（评估器插件在 evaluation 层） | oclif plugins、gh extensions | ➖ YAGNI，出现需求再议 |

其他沿用范式：`flutter doctor` / `npm doctor`（顶层自检）、Claude Code / Aider（会话式 Agent：计划先行、diff 确认、工具透明）、`create-next-app` / cookiecutter（模板 scaffold）、12-factor CLI（非交互可旁路、stdout/stderr 分离、稳定退出码）。

---

## 十、关键文件清单

| 文件 | 类型 | 职责 |
|------|------|------|
| `cli/__init__.py` / `cli/main.py` | 重组 | 唯一装配点 / 顶层命令薄壳 |
| `cli/console/{prompts,render,output,equiv}.py` | 新增 | 表现层基础设施（原语/渲染/JSON+退出码/等价命令） |
| `cli/workbench/session.py` + `workbench/domains/*` | 新增 | 向导框架与四域动作 |
| `cli/cmds/`（scenario/models/auth/runs/open_url/doctor + 既有五组迁入） | 重组+新增 | 子命令组（typer 绑定 + 纯函数动作） |
| `agent/package_agent.py` / `agent/package_tools.py` | 新增 | PackageAgent 组装与沙盒工具面 |
| `agent_eval/assets/configs/package_agent_prompts.yaml` | 新增 | Agent 提示词资产 |
| 平台侧 `/cli-auth` 页（P1 增强）与 pair 端点（P2） | 09 侧 | 见 §5.1/§5.2 接口约定 |

---

## 十一、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-08-31 | 初稿：对齐 requirement/04 v1.2——双前端同内核分层、workbench 向导框架（session/原语/降级/preflight/等价命令）、命令重命名一次性切换落地清单、退出码集中映射、auth 双通道登录与设备码流 P2 接口约定、open/--web URL 规则、PackageAgent（暂存区状态机 + 沙盒六工具 + 校验门禁 + 安全红线）、runs/scenario show 数据来源 |
| v1.1 | 2026-08-31 | **CLI 目录组织 Review 优化**（§2.2）：子命令组收拢 `cmds/`、表现层基础设施收拢 `console/`（prompts/render/output/equiv）；确立六条组织约定（装配单点 / 命令薄壳与纯函数动作分离 / 双前端同构 / 依赖单向禁横向 import / 交互与业务分离 / 粒度守恒）；全文路径引用同步 |
| v1.2 | 2026-08-31 | **行业实践对照校准**：新增 §九「行业实践对照」表（gh project-layout / oclif topics / RFC 8628 / kubectl printers）；P2 设备码流契约对齐 RFC 8628 语义（user_code / verification_uri / interval / slow_down / expired_token）；`open_url` 补 `$BROWSER` 覆盖；标注两项刻意不采纳（显式 Factory 依赖束、命令插件化）及理由 |
| v1.3 | 2026-08-31 | **Sprint 10 P0 实现同步**：目录重组落地（cmds/console/workbench）；交互原语 P0 采用编号选择（gcloud 同款，零新依赖），questionary 为 P1 可选升级；P1 配对码粘贴通道与 doctor/secrets 就绪态留待 Sprint 11 |
| v1.4 | 2026-08-31 | **main.py 模块化拆分**（889 → 88 行）：pack/evaluate/execute/upload 四命令模块迁入 `cmds/`（顶层与子命令组同构：绑定 + 纯函数动作）；装配点扩展 `app.command()()` 注册顶层命令；`_write_run_manifest` 无引用转发壳删除；引用随迁（workbench exec 域 + 3 个测试文件） |
| v1.5 | 2026-08-31 | **Sprint 10 收尾同步**：console/render.py 落地（阶段级 stage_progress——stderr 绑定 + transient + 非 TTY 降级，逐任务实时态待 ExecutionAgent 回调；print_task_table 完成态摘要）；--json 覆盖 run/pipeline/eval（emit_json 机器可读 payload；rich console 动态分流——json 模式 stderr 代理、text 模式 None 动态解析，不钉死流对象） |
| v1.6 | 2026-09-01 | **Sprint 11 auth 组落地**：`cmds/auth.py`（login/status/logout/register 四命令 + `auth_wizard` 子向导，纯函数动作双前端复用）；身份探测 `GET /api/public/whoami`（平台侧已实现，404 回退 `/api/public/secrets` 轻探测）；`.env` 写入走 `_env_file.py`（保序保注释 + 0600）；账号域新增「平台账号」入口（登录后 `_refresh` 平台态）、`start --domain auth` 别名、preflight 平台未连接提示 auth login；§5.1 补落地形态注记 |
| v1.7 | 2026-09-01 | **D-CLI-4 修订：平台身份迁密钥区 `~/.agent_eval/platform.json`**（用户评估反馈——与 llm.json / sut_credentials.json 三域三文件统一）；`config/platform_file.py`（0600 + `apply_platform_env` 启动注入仅补缺，env 直供优先）；`.env` 归用户手工管理：`_env_file.py` 收缩为只读残留检测，登录/登出提示不代删；conftest 钉 `AGENT_EVAL_PLATFORM_CONFIG` 隔离真实密钥区 |
| v1.8 | 2026-09-01 | **S11 secrets 执行前缺失自动补录**：`ensure_sut_credentials` 挂 `execute_stage`（run/pipeline/suite 同一挂点）——非抛错探测 `missing_credential_fields`（与预检同源数据驱动）→ 列缺失项确认 → 逐字段隐藏输入一次落盘 → 复检继续；取消/`--no-input` 退回原 fail fast；conftest 增 `AGENT_EVAL_SUT_CREDENTIALS` autouse 隔离（§7.2、复用清单同步） |
| v1.9 | 2026-09-01 | **补录挂点实测反馈修复**：`ensure_sut_credentials` 由 `execute_stage` 内移至 run/pipeline/suite 命令层**进度视图启动前**——stage_progress 转轮单行重绘会刷掉输入提示行（提示被「执行 N 个任务」掩盖，用户不知所措）；`execute_stage` 恢复纯 preflight fail fast（组织约定 5「_stages 零交互」+ 依赖方向修正）；动作上提 `cli/_common.py`（跨组共享，消除 cmds 横向 import）；补录前置于 run_id 生成，取消不留半截运行目录 |
