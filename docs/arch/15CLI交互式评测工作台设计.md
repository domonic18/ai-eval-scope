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
| G2 场景包 Agent 化 | PackageAgent 复用 DeepAgents 底座 + 独立沙盒工具面 + 校验门禁（§六）；**v3.0 升维为工作台 Agent（WorkbenchAgent）**——场景包降为首个域，会话机与组织方式见 §6.7/§6.8 |
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
   WorkbenchAgent（DeepAgents，独立于执行侧 SUTToolServer；v3.0 原 PackageAgent 升维）
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
├── workbench_agent.py # 工作台 Agent 会话机（turn/流式/预算/分段/salvage，§6.7/6.8 已迁移）
├── workbench_tools.py # 暂存沙盒原语 + 包域工具面（§6.2；含泛化 read_file/list_files，§6.11.1）
├── probe/             # SUT 接入调试域工具面（§6.6）——fetch/discovery/protocol/login + server 组装壳（§6.11.2 P1）
└── assets/configs/workbench_agent_prompts.yaml # 提示词资产：base + domain_segments 分段装配（§6.8/§6.10）
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

### 3.5 主菜单 v3.0：工作台 Agent 一级入口（v3.1；**已落地** 2026-09-03 feat/agent-sut-debug）

> 背景：v3.0 将 CLI Agent 从「场景包工具」升维为 WorkbenchAgent（§六导语）——Agent 不再是
> 某个域里的一个动作，而是工作台的首选工作方式。`start` 菜单结构随定位调整。

主菜单（`WorkbenchSession.run`）目标态：

```
选择工作域
  1. 工作台 Agent（对话式）   ← 新增一级入口（推荐）：自然语言下需求，跨域任务
  2. 场景包管理
  3. 执行评测
  4. 查看结果
  5. 账号与配置
  6. 退出
```

- **一级入口 = 通用档位**：进入 WorkbenchAgent REPL（自我介绍横幅见 §6.10 + 会话循环），
  能力域如实标注当前装配范围（场景包工程 + SUT 接入调试；其余域随 §6.9 路线图增装）。
  `start --domain agent` 提供等价直达（与 `--domain auth` 别名惯例一致）。跨域会话内
  任务对象切换仍随数据集域落地（§6.8）；一级入口先行不等它——复用既有 REPL 宿主与
  既有工具面，横幅如实声明当前域。
  **直入对话，无前置菜单（v3.4，实测反馈修订）**：进入即横幅介绍能力与示例，
  随后直接 REPL——「新建 / 改已有包 / 排查」都是会话里的一句话，不由菜单分流
  （对标 claude：打开即对话，能力介绍先行）。默认任务对象 = 新包草稿
  （`workspace/.staging`，会话后按清单 id 归位 `cwd/<id>-package/`，空会话退出
  清理草稿）；改已有项目包由 Agent 经 `read_file` 读入现有内容后在草稿中改造
  （prompts 域段「改造已有项目包」规约），`scenario new/edit --mode agent` 命令
  与域内快捷方式保留为显式直达。
- **域内入口 = 档位快捷方式**：场景包域两项标签调整为「用 Agent 创建场景包」「用 Agent
  修改选中的包」——语义从「Agent 的功能」改为「预载对象上下文的快捷方式」（改包先经
  `select_editable_ref` 选定，选中对象注入首条上下文；对标在仓库目录里启动 claude，
  cwd 即上下文）。快捷方式进入的会话显示同一横幅（档位=包域，示例文案为包域档）。
- **preflight 差异**：Agent 入口前置检查 LLM 配置，未配置 → 指引 `models set` 并阻断进入
  （无模型 Agent 不可用，与首屏「只提示不阻断」的查看类检查语义不同）。

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

## 六、工作台 Agent（WorkbenchAgent）

> **v3.0 定位升维**（2026-09-02，用户判词：「CLI 的 agent 不只是进行场景包的创建或者修改，
> 还会进行数据的修改、开源数据的下载以及处理等更多复杂任务——应升维为与 Claude Code
> 类似的 agent」）：场景包工程只是工作台 Agent 的**首个域**。目标形态对标 Claude Code：
> **一个通用会话机 + 按域装配的工具面（profile）+ 统一红线策略**，域以工具面与提示词段
> 形式增装，会话机不动。本章结构：§6.1–6.6 为场景包域的落地记录（PackageAgent /
> PackageToolServer 等命名在该域语境与代码中沿用，组织方式迁移见 §6.8）；
> §6.7（会话机：长任务与失控防线）、§6.8（组织方式升维）、§6.9（域路线图）为 v3.0 新增，
> **本版为方案稿，代码迁移随会话机实施一次性切换（D-CLI-6）**。

#### 关键决策（D-WB）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D-WB-1 | 定位与命名 | PackageAgent → **WorkbenchAgent（工作台 Agent）**；场景包编辑降为首域 | 对标 Claude Code「一个通用终端 Agent」；与 `start` 工作台、ExecutionAgent/EvaluationAgent 命名同族；避免「package」锁死能力想象 |
| D-WB-2 | 会话机与域解耦 | turn/流式/预算/分段/salvage/持久化收进会话机；域 = 工具面 + 提示词段 + 门禁策略（档位注入） | 新域零改会话机；会话机的打磨（§6.7）全域受益 |
| D-WB-3 | 失控缰绳 | **预算为主（token/成本），步数为阀**（单段 recursion_limit + 分段上限），人工中断随时可达 | Claude Code 无步数硬上限；步数 ≠ 工作量（前端包分析正当长链路即撞线） |
| D-WB-4 | 失败语义 | **唯一的失败是用户放弃**；撞线/中断/瞬时错误/预算到界一律 = 暂停（salvage 保现场） | AgentCompass P0「失败语义分层 + 断点续跑」；实测回滚致全失忆是本轮事故直接根因 |
| D-WB-5 | salvage 机制 | MemorySaver 检查点（仅作事故现场保存器）+ 孤儿 tool_call 合成失败 ToolMessage | deepagents 0.7.8 原生支持；成功路径保持「宿主持有消息重放」架构不变；v4.6.3 摘除的是文件版检查器，内存版无 IO 问题 |
| D-WB-6 | 进度外置 | 验证结论即写暂存草稿（文件系统即记忆，deepagents/Anthropic context management） | 对话历史是最脆弱的存储；跨轮/跨进程续作都从文件恢复 |
| D-WB-7 | 组织方式 | 会话机与域工具面分文件（§6.8 迁移表）；暂存/网络红线泛化为工作台级策略 | 「一域一 server」既有形态（package_tools/sut_probe_tools）直接推广 |

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
- **会话记忆两修**（第六轮实测反馈「Agent 不知道前几轮讨论的评测地址」）：① 放弃轮原实现整段截断消息历史——ask_user 答案（评测地址就在其中）一并丢失，下一轮全失忆；改为**文件回滚 + 对话保留**，以显式回滚说明（「暂存已回滚磁盘未修改」）收尾防 Agent 误判文件已写入；② 历史只在进程内存——会话中断重开后草稿续作只有文件没有对话；对话要点（user/assistant 文本，≤40 条）持久化 `workspace/agent_sessions/<root 路径摘要>.json`，续作时注入此前记录（≤24 条、单条 400 字截断）+「勿重复追问已给信息；文件以包内实际为准」指引，CLI 显示「已续接 N 条对话」。Ctrl+C 中断轮仍整段截断（半途历史不完整，工具调用与结果不配对）。
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

### 6.6 SUT 接入调试（方案 v1.1；**P0 已落地** 2026-09-02 feat/agent-sut-debug）

> 背景：PyPI 直装用户实测反馈——PackageAgent 目前只生成场景包文件，而被测系统（SUT）接入信息
> （API 地址可达性、agent-protocol 符合性、登录 API 地址与关键字段）全靠用户手工提供；
> 实际用户只知道「带登录框的页面地址」，不知道登录 API 域与字段名。目标：**创建场景包时即由
> Agent 智能探测与调试 SUT，验证过的结论才写进 `sut_configs/`，需要用户决策的点经 ask_user 询问**。

#### 现状差距

| 现状 | 差距 |
|---|---|
| `PackageToolServer` 十工具为纯文件沙盒（§6.2 红线：无 shell、**无网络**） | Agent 对外部零感知，sut_configs 靠想象生成——生成即盲配 |
| `preflight` / `ensure_sut_credentials` 仅执行时发现地址不通/凭证缺失 | 调试后置到最贵环节（跑考卷时才炸） |
| 登录链路要求精确知道 `login.path`、`body_template` 字段、`token_path` | 用户只知道页面地址，且不知道登录域可与 API 域分离 |
| REPL 仅 diff 确认一种交互（§6.3） | Agent 无法会话中主动向用户要信息 |

可复用拼装件：`execution/auth/provider.py::_login_by_api`（body_template Jinja 渲染 + token_path 提取 + 自动重登）、
`execution/channels/thread_commands.py`（协议客户端，stream 端点已有多路径回退链）、`agent/protocol_tools.py::tool_guard`
（错误转 `{"error": ...}` 交 Agent 自修复）、REPL staging/confirm 门禁 + 流式直播。

#### 工具面：`SUTProbeToolServer`（与文件沙盒并列的独立 server，绑定同一 DeepAgents）

| 工具 | 职责 | 关键设计 |
|---|---|---|
| `probe_url(url)` | 可达性：状态码/耗时/content-type/重定向链 | 只读 GET；响应证据截断防上下文爆炸 |
| `discover_login(page_url)` | 登录 API 发现阶梯（**普通用户只需输入页面登录地址**）：① 解析页面 `<form>` 与字段名 → ② 扫 JS 中 XHR/fetch/baseURL 线索 → ②.5 OpenAPI 文档探测（`/openapi.json` 等固定清单，命中即得精确端点与字段 schema）→ ③ 常见路径存在性探测（GET，固定清单 ≤10 条，不发凭证）→ ④ 全失败只向用户问**登录接口地址**一项兜底 | SPA 无线索是常态，第④级是**预期路径**而非失败兜底；**字段名不问用户**（用户普遍不知道）——按候选 fields 或常见约定拟定，经 probe_login 脱敏预览交用户确认/纠正 |
| `probe_protocol(base_url, flavor)` | agent-protocol 符合性矩阵：agent info → POST /threads 建临时线程 → commands → GET state → stream 端点 | 逐项 ✅/❌ + 证据，不做二值判定（实现形态差异大，回退链先例）；临时线程收尾清理 |
| `probe_login(login_cfg, ref)` | 登录实测：secrets 旁路取凭证 → 渲染 body → **脱敏预览（URL + 掩码 body + 目标 host）经 `ask_user` 确认后发送** → 校验 token_path 可提取 | **凭证值不进 LLM 上下文**；缺凭证返回 missing fields 触发 `ask_user`；对齐 `terraform plan`→apply 先展示后执行惯例 |
| `ask_user(question, options?)` | 会话中主动提问：开放文本 / 单选 / 凭证录入（直写 secrets，隐藏输入） | 桥接 CLI `ask()`/`select()`；非 TTY（`--yes` CI 形态）返回「需交互」错误 |
| `parse_curl(text)`（**P1 可选加速器**） | 解析「Copy as cURL」文本 → login.path / body_template / 字段线索 | 仅面向熟悉接口的进阶用户，**不入 P0 必经路径**（2026-09-02 用户拍板：普通用户只提供页面登录地址） |

#### 流程整合（创建包时即调试）

system_prompt 增「SUT 接入调试」阶段：包骨架完成后，需求含被测系统 → 主动问入口地址（页面地址即可）→
逐层探测 → **只把验证过的结论**写进 `sut_configs/`（protocol_flavor、login.path、body_template 字段名、token_path）→
引导 `secrets set` 录凭证 → 全绿才视为 SUT 段完成。探测证据落 `workspace/agent_logs/`（包内只落最终 YAML）。

#### 安全红线增量（§6.4 之外新增，工程难点所在）

1. **凭证旁路**：probe_login/ask_user 凭证路径中，值只经 secrets store ↔ 工具内部，LLM 上下文只见
   成败 + 脱敏响应骨架——把「sut_configs 禁凭证明文」红线延伸到网络面
2. **host 边界（评审修订：升格凭证外发硬门禁）**：网络工具仅可访问「用户本轮提供 host + sut_configs
   已有 host」；**凭证只发往用户确认过的 host**（页面同源，或经 `ask_user` 明确认可的 API 域）——
   自动猜测/发现的 host 一律不得接收凭证，防阶梯误判即凭证外泄
3. **探测内容注入防护（评审新增）**：probe_url/discover_login 抓回的 HTML/JS/响应头一律视为
   **data 而非 instructions**——分隔标记包裹 + 截断 + 剥离指令样文本；最终防线仍是 staging→diff→
   用户确认门禁（劫持指令无法绕过确认直接落盘）
4. **登录防锁**：真实凭证打真实接口，每（ref, host, body_template）组合只试一次，失败即停交
   用户——防试错锁死账号；用户纠正接口/字段后模板变化视为新组合，允许再试一次
5. **总量约束**：单探测 10s 超时、轮内预算**按工具分池**（probe_url 15 / discover_login 5 /
   probe_protocol 3 / probe_login 6——额度从宽只兜失控循环，单工具暴力试探不得饿死发现链，
   达上限指引继续验证而非收尾）；阶梯③路径清单固定 ≤10 条（对用户自报 host 的定向检查，非扫描行为）
6. **探测副作用言明**：probe_protocol 建临时线程属对被测系统的写操作，探测前经 `ask_user` 言明
   （可与 probe_login 预览确认合并为一次交互）

#### CLI 配套与分期

- P1 配套：`agent-eval sut probe <包|url>`（无 Agent 纯规则快速自检）；doctor 增 SUT 连通性项
- **P0**（本分支首批）：四探测工具 + ask_user + host 边界 + 凭证旁路 + prompts 调试阶段 + 全 mock 测试
  ——最小闭环「给页面地址 → 智能探测 → 写 sut_configs → secrets 引导」
- **P1**：协议符合性细化（stream/错误语义分级）、OpenAPI 文档解析工具、`parse_curl` 粘贴解析加速器（进阶可选）、`sut probe` 命令、doctor 集成
- **P2**：探测经验模板化沉淀、多 SUT 候选对比

#### 待决问题（评审拍板）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | host 边界 | ✅ 已定（2026-09-02 评审）：严格项——仅「用户提供 + sut_configs 已有」；凭证外发升格硬门禁（红线 2） |
| 2 | 登录实测 | ✅ 已定（2026-09-02 评审）：会话内实测 + 发送前脱敏预览确认（terraform plan 式） |
| 3 | P0 范围 | ✅ 已定（2026-09-02 用户拍板）：**A 四件全量**——probe_protocol 入 P0（协议符合性为需求原文，复用 thread_commands 客户端增量可控） |
| 4 | `sut probe` 独立命令 | ✅ 已定（2026-09-02 用户拍板）：**P1**——P0 专注 Agent 会话内调试闭环，独立命令与 doctor 集成后置 |

> **评审记录（2026-09-02）**：其余评审结论用户均确认；**问题 3（cURL 导入）按用户意见调整**——普通用户
> 一般只提供页面登录地址 URL，主轴保持「页面地址 + 简单问答」，`parse_curl` 降为 P1 可选加速器、
> 不入 P0 必经路径。

#### P0 落地注记（2026-09-02，feat/agent-sut-debug）

- `agent/sut_probe_tools.py`：`SUTProbeToolServer` 五工具全量——probe_url（只读 GET + 证据截断）、
  discover_login（form 属性/字段解析 → 同 host JS XHR 线索 → OpenAPI 文档探测 → ≤10 常见路径定向检查 → 只问接口地址兜底）、
  probe_protocol（建线程→commands/state→stream 端点矩阵 + DELETE 清理，逐端点事实非二值）、
  probe_login（缺凭证报 missing_fields → ask_user(credential) 收集直写密钥区 → **脱敏预览经用户确认
  才发送**，响应 token 与账密一律掩码，值不回流 LLM 上下文）、ask_user（文本/单选/凭证三态，非交互
  返回需交互错误）
- 红线实现：host 边界（`_ensure_host` 未授权 host 经 ask_user 征得同意，拒绝即拉黑）；凭证外发硬门禁
  （无 ask_fn 一律不发送）；防锁（(ref, host, body_template) 组合一次即停，用户纠正
  字段后模板变化视为新组合可再试）；轮内预算 `new_turn()` 挂 `PackageAgent.turn`
  （按工具分池：probe_url 15 / discover_login 5 / probe_protocol 3 / probe_login 6）；注入防护
  （`_wrap_evidence` data 区块声明 + 截断）；探测证据随会话日志落 `workspace/agent_logs/`
- 集成：`PackageAgent` 双 server 组装（文件沙盒 + 探测面），`_describe_tools` 汇总；CLI
  `scenario_agent._make_ask_fn()` 桥接 `ask()/select()/hide` 交互原语（`--yes` CI 形态不装配）；
  prompts 增「SUT 接入调试」阶段（纯包内语境，无 docs/ 引用——prompts 随包发布）
- 测试：`tests/unit/test_sut_probe_tools.py` 43 项全 mock（httpx MockTransport，禁止联网红线）——host
  边界/授权拉黑、注入包裹与截断、form 发现（无语义过滤）、自拟路径定向检查、OpenAPI 阶梯命中、
  缓存检索、前端包分析原语组合（真实 SPA 形态：主包分块映射→页面分块→登录契约）、无候选兜底指引
  不问字段名、凭证缺失不发送、非交互硬门禁、确认发送且 token 不回流、防锁一次即停 + 按路径区分 +
  改模板可重试、占位符语法拒发、协议矩阵含清理、预算分池重置、ask_user 凭证直写不回流

风险与对策：SPA 登录静态发现成功率低 → 阶梯第④级引导为预期路径，话术顺滑；登录实测副作用 → 单次尝试 +
直播 + 证据留存；探测轮次烧 token → 调用上限 + 流式直播可随时 Ctrl+C（草稿续作已具备）。

#### 泛化重构：前端包分析原语（2026-09-02，实测迭代六/七后定稿）

> 迭代七的用户判词：「不是 hardcode 正则/关键字，而是让 CLI 具备泛化的分析能力，应对未来各种登录场景」。
> 排查依据是对真实站点的完整人工分析：1.7MB 前端主包 `users/login` 字面量为 0，登录契约
> `POST /users/login {phone, captcha, platform}` 位于路由级异步分块（35KB），分块 URL 由主包内
> webpack 映射（名字表 + hash 表 + 后缀）拼出；接口域以 axios interceptor `baseURL` 形态出现、
> 与页面域分离——逐站点写死的正则/路径清单/分块解析器对下一个站点必然失效。

**能力分层**（什么进代码、什么进 LLM 的边界）：

| 层 | 内容 | 归属 |
|---|---|---|
| 机械原语 | 抓取入缓存（probe_url/discover_login，完整响应体存服务端不进 LLM 上下文，单文件 3MB/总量 8 个、轮内有效）、子串检索（search_content：Agent 自拟模式、大小写不敏感、带上下文摘录 ≤12 条、数据区声明）、HTML 结构解析（stdlib html.parser：全部 form + 脚本清单，**无语义过滤**）、OpenAPI/规范文档挂载点探测（工具规范约定，POST 端点原样列出）、定向路径检查（≤10 条，**路径由 Agent 经 `paths` 参数自拟**） | 代码 |
| 分析知识 | 搜什么（业务词/请求构造痕迹/分包机制痕迹）、分块命名规则解读与 URL 推算、接口基址与相对路径组合、form 判读（哪个是登录表单——按密码字段过滤会漏短信验证码登录）、登录路径候选拟定 | Agent 推理 + prompts 方法论 |
| 字段语义 | 凭证字段实际要输入什么（如 captcha 实际承载密码） | Agent 经 `ask_user(desc=…)` 传入 |

- 新工具 **`search_content(pattern, context)`**：已缓存内容检索原语，非正则（防 ReDoS）、摘录
  带数据非指令声明；预算独立分池 15。`probe_url` 增缓存旁注（cached_bytes/search_hint）；
  `new_turn()` 同步清缓存。
- 删除的硬编码：XHR/绝对 URL/登录字段名三类关键字正则、`pass|captcha` 登录表单判定、
  常见登录路径清单（`_COMMON_LOGIN_PATHS` → Agent 自拟 `paths`）、OpenAPI 端点 login 关键字过滤、
  外链脚本 ≤5 自动 JS 阶梯。
- prompts 增**前端包分析法**方法论（发现→检索→读摘录→分块跟随→基址组合→实测验证，
  假设-验证循环）；ask_user credential 增 `desc` 必带（录入提示直达字段语义，实测反馈「只显示
  `请输入 ref.field` 用户不知道在输入什么」）；probe_login 预览从 host 改**完整 URL**（路径抄错
  只有在预览里用户才看得见）并在结果中携带 url。

### 6.7 会话机：长任务执行与失控防线（v3.0 方案；**P0–P3 已落地** 2026-09-03 feat/agent-sut-debug）

> 实测复盘（2026-09-02，bj33 包创建会话）：Agent 独立走完前端包分析最难的一段（模块映射
> `9258:"login__teacher__index"` → 分块命名 `{id}.{hash}.async.js` → 接口域 baseURL）后撞上
> `recursion_limit = max_turns × 2 = 80`，异常回滚——**暂存清空 + 本轮对话截断**；用户输入
> 「请你继续」后 Agent 全失忆（包是空的、对话是空的、探测缓存无人知晓）。两层根因：
> ①**步数安全阀被误用为任务预算**——`recursion_limit` 本是防死循环的阀，但前端包分析这类
> 正当长链路（30+ 次检索/抓取 + 分块跟随）legitimate 就会撞线；②**撞线 = 销毁现场**——
> `except BaseException` 一刀切回滚（当年为防孤儿 tool_call 破坏图而截断半途历史），把
> 「历史不完整」处理成了「丢弃一切」，连用户刚给的入口地址一起陪葬。

#### 语义转变（D-WB-4）：唯一的失败是用户放弃

| 事件 | 现行为 | 目标行为 |
|---|---|---|
| recursion_limit 撞线 | 异常 → 回滚 + 全失忆 | **暂停**：salvage 保现场 →（P1）自动续跑 / 交还用户 |
| Ctrl+C 中断 | 回滚 + 全失忆 | **暂停**：salvage 保现场，提示「说继续接着干 / 放弃改动回滚」 |
| LLM 瞬时错误（断流等） | 回滚 + 全失忆 | **暂停**：salvage 保现场，可直接重试 |
| 预算到界（P2 新增） | 无预算 | **暂停**：交还用户，进度完整 |
| 用户确认时放弃 | 回滚文件、保留对话 | 不变——**唯一回滚触发器** |

#### P0 salvage：撞线保现场（根治失忆）

- `create_deep_agent(..., checkpointer=MemorySaver())`（deepagents 0.7.8 支持，已核实签名；
  langgraph `MemorySaver` 纯内存——v4.6.3 摘除的是**文件版**检查器全量读写 IO 空转，内存版
  无此问题；会话级生命周期，检查点容量有界，Agent 实例销毁即释放）；
- `_invoke` 每次以独立 `thread_id` 调用：**成功路径行为不变**（宿主持有消息重放的既有架构
  不动，checkpointer 仅作事故现场保存器）；
- 撞线/中断时 `aget_state` 捞半途消息 → **孤儿 tool_call 修复**（无结果的调用合成
  「（会话在此被打断，未执行完）」失败 ToolMessage——当年截断的真实原因就此解决）→
  并入宿主历史；暂存区保留（跨轮本就保留）。

#### P1 自动分段续跑：干完为止（Claude Code 式）

- `recursion_limit` 降格为**单段安全阀**：撞线不再交还用户，自动开新段续跑（同一对话、
  同一预算池、同一暂存），直到——任务完成 / 分段数上限（默认 3）/ 用户 Ctrl+C；
- 段边界发 `phase: checkpoint` 事件，CLI 显示「已自动续跑 N/上限」；交还用户时进度完整，
  「继续」即接着跑；`probe.new_turn()` 仍只在**用户轮**开始时调用（域预算按用户轮计，
  不随段重置）。

#### P2 预算缰绳 + 配置化（失控控制的单位从「步数」换成「钱」）

- 接入 `BudgetGuard` 会话级 token/成本预算（§6.5 在案偏差「BudgetGuard 待接入」正式收账，
  复用执行侧组件）：到线 = 暂停交还（salvage 保进度），不是失败；
- 轮数去 hardcode：`scenario new/edit --max-turns / --max-segments / --budget-usd`
  （缺省值只是安全阀，不是天花板）。

#### P3 进度外置：进度活在文件里，不活在对话里

- prompts 规约：**每验证一条结论立即 `write_file` 更新暂存草稿**（sut_configs/task_sets
  随探测渐进成形，不攒到最后一次性写）——暂存跨轮保留，故任何暂停/崩溃后进度都在文件里；
- 配合 agent_sessions 对话持久化与草稿目录（§6.5），跨进程断点续作成立。

#### 失控缰绳盘点（改后）

| 缰绳 | 语义 |
|---|---|
| 工具级预算分池 | probe_url 20 / search_content 30 …（§6.6，防单工具空转，不变） |
| 单段步数阀 | recursion_limit（防单段死循环——阀，非任务预算） |
| 分段数上限 | 默认 3 段（总工作量封顶） |
| token/成本预算 | BudgetGuard 会话级（真实经济缰绳） |
| 人工控制 | 随时 Ctrl+C（进度保留）+ ask_user 交互点 + staging→diff→确认门 |

#### 落地注记（2026-09-03，feat/agent-sut-debug）

- **Tunables 单点**：`WorkbenchAgentConfig`（frozen slots dataclass）承载 max_turns=40 /
  max_fix_rounds=3 / max_segments=3 / budget_usd=None / max_dialogue_entries=40 / resume
  截断参数 / probe 档位（budgets+timeout_s 注入 `SUTProbeToolServer`）；CLI 三旗标同载体。
- **P0**：`create_deep_agent(..., checkpointer=MemorySaver())` + `_invoke` 每次独立
  `thread_id`；异常路径 `aget_state` 捞半途消息 → `repair_orphan_tool_calls`（尾部孤儿
  tool_call 合成「（会话在此被打断…）」失败 ToolMessage）→ 全线程替换宿主历史；成功路径
  宿主持有消息重放不变。langgraph 缺席（无 `[agent]` extra）try/except 优雅降级。
- **P1**：recursion_limit=max_turns×2 单段阀；撞线自动开新段续跑（同一对话/预算池/暂存），
  段边界发 `phase: checkpoint` 事件（CLI：「⏭ 已自动续跑（第 N / M 段，进度保留）」）；
  `probe.new_turn()` 仍只在用户轮调用。分段耗尽 = 暂停（`aborted_reason=segment_limit`）。
- **P2**：`BudgetGuard` 经 runtime `callbacks` 注入；`BudgetExceededError` = 暂停
  （`aborted_reason=budget_exceeded`），暂存与历史完整。
- **P3**：prompts「进度即写盘」规约成稿（域段工作流程第 6 步：每验证一条结论立即
  `write_file` 更新暂存草稿）。
- **REPL 处置闭环**：中断/瞬时错误上抛 → CLI 打印「⏸ 已暂停（进度已保留…）」；「继续」
  重跑；「放弃」= 唯一回滚触发器（`abandon_pending()`，磁盘不受影响）。
- 测试：`TestSessionMachine` 覆盖撞线自动续跑（checkpoint segment=2）/ 分段耗尽暂停 /
  瞬时错误保现场 / 预算到界暂停 / budget guard 装配 / 孤儿修复 / salvage 全线程替换。

### 6.8 组织方式升维（v3.0；**已落地** 2026-09-03 feat/agent-sut-debug，D-CLI-6 一次性切换）

**分层原则**：会话机（通用，零域语义）/ 域工具面（一域一 server）/ 域门禁（档位策略）。
会话机对应 Claude Code 的「主循环」，域对应「工具 + 上下文」——新域 = 新 tool server +
prompt 段 + 档位登记，**不改会话机**。

| 现文件 | 目标 | 说明 |
|---|---|---|
| `agent/package_agent.py` | `agent/workbench_agent.py` | 会话机：turn/流式/预算/分段/salvage/对话持久化/门禁编排（门禁策略由档位注入）；包域语义全部下沉 |
| `agent/package_tools.py` | `agent/workbench_tools.py` | 暂存沙盒原语（staging/view/commit/diff、路径与扩展名守卫）+ 包域工具（validate/manifest/reference）；原语/域的文件拆分留待第二域落地时按需切开（YAGNI） |
| `agent/sut_probe_tools.py` | `agent/probe/` 包（§6.11.2 P1 已落地） | 五域 mixin（fetch / discovery / protocol / login）+ `server.py` 组装壳；「一域一 server」形态不变（D-WB-7），拆的是实现不是边界 |
| `cli/cmds/scenario_agent.py` | `cli/cmds/workbench_agent.py` | REPL 宿主（流式渲染/ask 桥/中断提示）本就是通用的，随域名修正 |
| `assets/configs/package_agent_prompts.yaml` | `workbench_agent_prompts.yaml` | 提示词资产随会话机更名；包域段落保持独立小节（域提示词分段装配） |

**域装配档位（profile）**：`WorkbenchAgent(root, profile=<域档位>)` = 工具面清单 + 提示词段
+ 门禁策略。**域命令是档位快捷方式**——`scenario new/edit` 预置包域档位；通用入口
`agent-eval agent`（跨域 REPL，会话内可切换任务对象）随数据集域一起落地（§6.9）。

**红线泛化**：§6.3 staging 门禁（磁盘只见「用户确认 + 校验通过」的内容）与 §6.6 网络四红线
（host 边界 / 凭证旁路 / 防锁 / 注入防护）升格为**工作台级工具面策略**——任何新域的网络面 /
落盘面工具必须以策略形式接入（如数据集下载 = host 确认 + 磁盘限额），不得绕过。

> **落地形态（2026-09-03）**：迁移表五行全部完成（无兼容层）；原「sut_probe_tools 不动」
> 按 §6.11.2 P1 修正为 `agent/probe/` 包拆分。**D-WB-2 分段装配成稿**：prompts 资产结构
> `system_prompt_base`（会话机段——身份/红线/控制，零域语义）+ `domain_segments.<域>`
> （域方法论与输出规范）+ `domain_labels.<域>`（域展示名，与横幅 `{domains}` 同源）；
> `_build_system_prompt` = base + 装配域段拼接后统一字面 replace（`{domain}/{tools}/
> {pkg_root}/{assets_root}`），未装配域抛 `AgentError`——新域上线只改资产 + 登记档位，
> 会话机零改。

### 6.9 域路线图

| 域 | 工具面（增量） | 门禁 / 红线 | 依赖 |
|---|---|---|---|
| 场景包（✅ 已落地 §6.1–6.6） | 文件沙盒 + validate/reference + SUT 探测 | staging 门禁 + 凭证明文拦截 | — |
| 数据集（P1 候选） | 检索 / 下载 / 处理 / 抽检（复用 DatasetManager，[10 数据集下载设计](./10数据集下载设计.md)） | 下载 host 确认 + 磁盘用量限额 + 来源记录 | 会话机 v3.0 |
| 包内数据修改 | 复用暂存沙盒，扩展可写路径（datasets/、knowledge） | 同 staging 门禁 | — |
| 运行 / 结果 | runs 查询 / 失败诊断 / 补评估触发 | 只读优先，写操作走确认 | — |

> 需求侧同步待办：req/04 增补「工作台 Agent 通用域」需求条目与验收口径（本版仅架构侧）。

### 6.10 启动横幅与自我介绍（v3.1；**已落地** 2026-09-03 feat/agent-sut-debug）

> 用户诉求：Agent 定位升维后，新用户进入会话需要一段自我介绍——我是谁、能做什么、
> 怎么用。对标 Claude Code 首屏（欢迎框 + cwd + tips）。现状：REPL 启动只有会话日志
> 路径一行（`scenario_agent.py::_session`），用户不知道 Agent 的能力边界与正确用法。

**内容要素（五件，顺序固定）**：

| # | 要素 | 来源 |
|---|---|---|
| 1 | 身份一句话 | 资产文案（固定） |
| 2 | 当前任务对象 + 可用能力域 | `{root}`（包根/新包草稿路径）+ `{domains}`（档位装配的能力域清单） |
| 3 | 使用示例 2–4 条 | 资产文案按档位选取（示例必须与档位真实能力一致，不得宣传未装配域） |
| 4 | 红线与确认方式 | 资产文案（暂存→diff→确认落盘 / 凭证不回流——与 §6.3/§6.6 红线同源） |
| 5 | 控制方式 | 资产文案（Ctrl+C 暂停、空行退出、中断续作） |

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

- 文案落提示词资产独立 `intro` 小节（§6.8 迁移目标 `workbench_agent_prompts.yaml`），
  模板变量 `{root}`/`{domains}` 走既有字面 replace 渲染；CLI（REPL 宿主）只渲染不写死
  ——新域上线改资产即更新介绍，不改代码。
- 渲染：rich Panel，REPL 启动时、会话日志行之前；续作会话在横幅后追加既有「已续接 N
  条对话」提示；`--json` 与非 TTY（`--yes --instruction` CI 形态）静默跳过横幅。
- §3.5 主菜单一级入口与域内快捷方式共用同一横幅（档位不同 → `{domains}`/示例文案不同）。

> **落地形态（2026-09-03；v3.4 实测反馈修订）**：五要素文案落
> `workbench_agent_prompts.yaml::intro` 资产，`WorkbenchAgent.intro_text()` 字面 replace
> 渲染；CLI `_render_intro`（rich Panel 定宽 ≤100 列——超宽终端不拉满整行，防 CJK 双宽
> 渲染截断 + `is_json() or not sys.stdout.isatty()` 静默）。**横幅先于任何输入**：
> §3.5 一级入口渲染横幅后直入 REPL（`_session(show_intro=False)` 抑制重复，直连命令
> `scenario new/edit --mode agent` 仍由 `_session` 渲染）——实测反馈曾先问需求后显横幅，
> 顺序颠倒。样例四条（创建+探测主轴 / 改已有项目包 / 参照内置包新建 / 执行报错排查）
> 与档位真实能力一致；LLM preflight 阻断仍在横幅之前（无模型 Agent 不可用）。

### 6.11 代码质量与开源规范优化（v3.2；**已落地** 2026-09-03 feat/agent-sut-debug）

> 开源前置 review（2026-09-02，用户两点要求：①场景包结构知识不 hardcode 在提示词，
> 改为「Agent 读规范文档 + 看内置样例」；②常量归集与命名/分层符合行业规范）。
> 本节为方案稿，随 §6.7/§6.8 会话机切换一并实施；**PACKAGE_ROOT 修正与 ToolSpec 描述
> 修正无依赖，可独立先行**。

#### 6.11.1 结构知识外置：随包 Markdown 规范 + read_guide 工具

**现状问题**——包结构知识四源并存，Agent 只读得到 hardcode 那份：

| 来源 | 内容 | 随 pip 包发布 | Agent 可达 |
|---|---|---|---|
| `docs/arch/13 §四` | 包结构设计规范（人读） | ❌ 仓库文档 | ❌（运行时禁引 docs/） |
| `assets/schemas/*.json` | task_set / rule_set JSON Schema | ✅ | ❌（工具面未暴露） |
| 内置包 chat / code / courseware | 权威样例 | ✅ | ✅ read_reference / search_reference |
| `package_agent_prompts.yaml`「内容规范」段 + `generate_new_package` 模板 | 上述的蒸馏硬编码副本 | ✅ | ✅ **唯一实际生效** |

硬编码副本与真相源之间漂移无门禁；结构字段描述混在行为规约里，system_prompt 约 133 行。

**设计**：

1. **新资产 `assets/guides/scenario-package-format.md`**——面向 LLM 阅读的运行时速查，
   大纲对齐 arch/13 §四：目录结构总览 / 清单 `agent_eval.yaml` 字段表 / rules 规则集 /
   prompts 判官提示词 / task_sets 考卷 / datasets / metrics policy / sut_configs（仅
   credential_ref 引用，红线重申）。每小节：字段表 + 最小内联示例 + **「权威样例」指引**
   （如 `read_reference("chat", "rules/chat-quality.yaml")`——规范与真实样例串接）+
   关联 JSON Schema 文件名。随包发布（prompts 同款红线：**运行时资料禁止引用仓库
   docs/ 路径**——pip 安装用户没有 docs/）。
2. **通用文件工具泛化（评审修订：不做 read_guide 专用工具）**——「按文档逐个封装专用
   工具」正是 §6.6 泛化原则反对的 hardcode 形态，且未来通用入口需要读**用户提供的
   文件**。`read_file` / `list_files` 泛化为 **Claude Code 式分级授权**：会话根内
   （暂存视图优先）→ 随包资源 `assets/`（自动授权只读）→ 外部路径经 `ask_fn` 向用户
   申请授权（允许记账放行 / 拒绝即拉黑，与 §6.6 host 边界同款机制）；**凭证类路径
   硬拒**（密钥区 / sut_sessions / .env——先于授权逻辑，凭证不回流 LLM 上下文）。
   写路径不泛化：write/delete 仍硬沙盒 confined 会话根 + staging 门禁（§6.3 不变量
   不动）——读写不对称正是 Claude Code 的形态（读宽松、写有门）。
3. **prompts 瘦身**：「内容规范」段退役 → 沙盒边界改读写分级表述 + 工作流程第 3 步
   指路规范文档路径（新增 `{assets_root}` 模板变量）；`generate_new_package` 模板的
   目录清单删除。行为规约（工作流程 / SUT 调试方法论 / ask_user 规约 / 输出规范）
   全部保留。
4. **真相源分层（关键不变式）**：`validate_package` 门禁（代码）= **硬真相**——Agent
   照 guide 写错仍会被打回自修复，漂移的最坏后果是多一轮回改，**不产生坏包**；guide
   为运行时速查（受众是 Agent 与开源用户），arch/13 §四为设计真相源，变更 arch/13 时
   须同步 guide（文档侧纪律）。
5. **顺带修正（review 发现）**：`search_reference` ToolSpec 描述声称返回「场景扩展
   方法论要点」，实现只返回文件树——改描述对齐行为（方法论已由 prompts 前端包分析法
   承载）；`_load_prompts` 资产结构校验随 `intro`（§6.10）/ guide 段扩充。

#### 6.11.2 常量归集与命名规范

**分层原则**（行业实践：**按可变性分层，而非物理集中成全局 constants.py**——大杂烩
常量文件掩盖影响面，改一处全仓重审）：

| 层 | 判据 | 归宿 |
|---|---|---|
| 可调参数（tunables） | 随场景 / 用户 / CLI 变 | frozen dataclass 配置对象，构造器注入，默认值单点——与 §6.7 P2 CLI 旗标（`--max-turns/--max-segments/--budget-usd`）**同一载体合流** |
| 固定阈值（invariants） | 行为不变式（安全红线、截断上限、超时） | 就近具名模块常量，统一 `_MAX_*` 私有风格 + 注释写明依据；跨模块复用才上提共享模块 |

**`WorkbenchAgentConfig` 草案**（§6.8 迁移后的载体，取代散装构造参数与模块常量）：

```python
@dataclass(frozen=True, slots=True)
class WorkbenchAgentConfig:
    # 会话机（§6.7 P2 CLI 旗标直通）
    max_turns: int = 40              # 单段安全阀基数（recursion_limit = max_turns × 2）
    max_fix_rounds: int = 3          # 校验门禁回改轮上限
    max_segments: int = 3            # 自动分段续跑上限（P1）
    budget_usd: float | None = None  # 会话预算（P2；None = 不启用）
    # 对话持久化
    max_dialogue_entries: int = 40
    resume_max_entries: int = 24
    resume_max_chars: int = 400
    # 探测域档位默认（域档位可覆盖——D-WB-2 域 = 工具面 + 提示词段 + 门禁策略）
    probe_budgets: dict[str, int] = field(default_factory=lambda: dict(TOOL_BUDGETS))
    probe_timeout_s: float = 10.0
```

**常量盘点（现状 → 目标）**：

| 现状位置 | 常量 | 目标 |
|---|---|---|
| `package_agent.py` 构造参数 | max_turns=40 / max_fix_rounds=3 | config（上表） |
| `package_agent.py` 模块常量 | `_MAX_DIALOGUE_ENTRIES` / `_RESUME_MAX_ENTRIES` / `_RESUME_MAX_CHARS` | config（上表） |
| `package_agent.py:40` | `_PROMPTS_PATH` **手拼 `parent.parent/assets`** | **修违规**：改用 `config/paths.PACKAGE_ROOT`（evaluator/CLAUDE.md 自家约定；execution_agent / summary 均已用，唯此文件手拼） |
| `sut_probe_tools.py` | `TOOL_BUDGETS` / `PROBE_TIMEOUT_S` / `MAX_DISCOVER_PATHS`（公开）与 `_MAX_EVIDENCE` 等 8 项（私有）命名风格混用 | 预算 / 超时入 config；文件级阈值统一 `_MAX_*` 私有具名 |
| `package_tools.py` | `read_file(8000)` / `read_reference(6000)` 签名 magic number | 提 `_DEFAULT_READ_CHARS` 等具名常量（工具签名默认值仍可被 LLM 传参覆盖，语义不变） |
| `scenario_agent.py` | `_render_diff(max_lines=80)`、question 60 字等 | 具名常量；随文件拆分（下）归位 |

**命名与文件组织**（开源可读性；§6.8 迁移表的细化）：

- `cli/cmds/scenario_agent.py`（514 行）超仓库「粒度守恒 ~300 行」约定（组织约定 6），
  四类职责混居：流式渲染（`_make_stream_emitter`）→ **`console/agent_stream.py`**
  （表现层基础设施，与 prompts/render 同层）；REPL 循环、ask 桥、落盘归位留 cmds
  （随 §6.8 改名 `workbench_agent.py`）。
- `agent/sut_probe_tools.py`（883 行）**P1** 拆分：抓取缓存与证据包裹原语 / 登录发现 /
  登录实测（防锁）/ 协议探测各自成模块，`SUTProbeToolServer` 保持组装壳——「一域一
  server」形态不变（D-WB-7），拆的是实现不是边界。
  **落地（2026-09-03）**：`agent/probe/` 包——`fetch.py`（抓取缓存 + 证据包裹 + `_host_of`
  共享原语 + probe_url/search_content）、`discovery.py`（`_PageStructureParser` +
  discover_login 阶梯）、`protocol.py`（协议矩阵 + `protocol_hosts`）、`login.py`
  （probe_login 防锁 + ask_user + 凭证旁路）、`server.py`（组装壳：共享状态 + 红线设施
  `_budget/_ensure_host/_client/_log` + TOOL_SPECS）；mixin 组装，协作契约由壳提供、
  mixin 顶部注解声明；每文件 ≤300 行，`__init__.py` 重导出三公共符号，引用一次性切换。
- `PackageAgent.__init__` 内非可选依赖的惰性 import（`config.paths` /
  `CredentialStore`）上提模块顶层；`deepagents` 保持惰性（`[agent]` extra 红线）。
- **ToolSpec 描述即对外契约**（开源用户与 LLM 同读）：描述与行为一致性纳入 review
  检查项（本案：`search_reference` 描述漂移，§6.11.1-5）。

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
| `agent/workbench_agent.py` / `agent/workbench_tools.py` | 已迁移（§6.8） | 工作台 Agent 会话机（turn/流式/预算/分段/salvage）与暂存沙盒工具面；原 `package_agent.py` / `package_tools.py` |
| `agent/probe/`（fetch/discovery/protocol/login/server） | 拆分（§6.11.2 P1） | SUT 接入调试域工具面：域 mixin 实现 + `server.py` 组装壳（原 `sut_probe_tools.py`） |
| `cli/cmds/workbench_agent.py` + `cli/console/agent_stream.py` | 已迁移/新增（§6.11.2） | REPL 宿主（ask 桥/中断提示/落盘归位）与流式渲染基础设施；原 `cli/cmds/scenario_agent.py` |
| `agent_eval/assets/configs/workbench_agent_prompts.yaml` | 已更名 | 提示词资产：`system_prompt_base` + `domain_segments` 分段装配（§6.8）；`intro` 自我介绍段（§6.10）；原 `package_agent_prompts.yaml` |
| `agent_eval/assets/guides/scenario-package-format.md` | 新增（v3.2） | 随包发布的包结构规范——Agent 经 `read_file` 直读（assets 自动授权域，§6.11.1） |
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
| v2.0 | 2026-09-02 | **新增 §6.6 SUT 接入调试方案稿（待评审）**：用户反馈「创建场景包时应由 Agent 智能探测调试 SUT（地址可达性 / agent-protocol 符合性 / 登录 API 发现与字段），验证结论写进 sut_configs，缺信息经 ask_user 询问」——新增 `SUTProbeToolServer` 五工具（probe_url / discover_login / probe_protocol / probe_login / ask_user）、流程整合（创建即调试）、安全红线增量（凭证旁路 / host 边界 / 登录防锁 / 总量约束）、P0-P2 分期与四项待决问题；本版仅方案，未实施 |
| v2.1 | 2026-09-02 | **§6.6 评审修订并入（方案 v1.1）**：①新增红线「探测内容注入防护」——抓取内容视为 data，分隔 + 截断 + 剥离指令样文本，diff 确认为最终防线；②host 边界升格**凭证外发硬门禁**——凭证只发用户确认过的 host，自动发现 host 不得接收凭证；③discover_login 明确「页面登录地址 + 简单问答」为普通用户主轴，`parse_curl` 降 P1 可选加速器（用户拍板：普通用户不提供 cURL）；④probe_login 增发送前脱敏预览确认（terraform plan 惯例）；⑤阶梯③路径清单 ≤10 条上限、probe_protocol 建临时线程写操作言明；待决问题 1/2 落定，3/4 待拍板 |
| v2.2 | 2026-09-02 | **§6.6 待决问题全部落定**：决策 3 = A（probe_protocol 入 P0，四件全量）；决策 4 = P1（`sut probe` 独立命令与 doctor 集成后置）。P0 范围冻结：SUTProbeToolServer 五工具 + ask_user 桥 + 四条安全红线 + prompts 调试阶段 + 全 mock 测试 |
| v2.3 | 2026-09-02 | **§6.6 P0 落地**（feat/agent-sut-debug）：`agent/sut_probe_tools.py` 五工具 + 四条红线实现（host 授权/凭证外发门禁/防锁/轮内预算 12 + 注入防护）+ PackageAgent 双 server 组装 + CLI ask 桥 + prompts「SUT 接入调试」阶段（无 docs/ 引用，prompts 随包发布）+ 23 项全 mock 单测；详见 §6.6 P0 落地注记 |
| v2.4 | 2026-09-02 | **§6.6 P0 实测迭代（用户不知道字段名场景）**：①discover_login 新增 OpenAPI 文档探测阶梯（`/openapi.json` 等固定清单，命中即得精确端点与字段 schema）、兜底指引改为**只问登录接口地址一项**（字段名不问用户——用户普遍不知道，由 Agent 按候选 fields 或常见约定拟定，probe_login 脱敏预览即用户确认/纠正环节）；②登录防锁键从 (ref, host) 扩为 **(ref, host, body_template)**——配置未变不重试，用户纠正字段后模板变化视为新组合可再试一次；③prompts 补「用户回答不知道」行为链（Agent 自行拟定 → 实测 → 证据交用户核对）；测试 23 → 27 项 |
| v2.5 | 2026-09-02 | **§6.6 P0 实测迭代二（预算饿死与未验证落盘）**：真机会话暴露——probe_url 逐路径猜接口烧光共享预算 12 → 用户提供登录页地址后 discover_login 被预算拒绝，页面分析整段跳过，Agent 又按预算报错「汇总现有证据收尾」的指引把猜测接口直接写进 sut_configs。修复：①预算从共享池改**按工具分池**（8/3/2/4，后按用户意见放大至 15/5/3/6）；②预算报错文案重写——呈现证据 + 请用户开新轮重置预算 + 未验证结论不得写入；③probe_url ≥400 返回 next_step 指向 discover_login、禁止逐路径猜；④discover_login 阶梯②扩展 JS **绝对 URL 扫描**（登录页域 ≠ 接口域的跨域端点）；⑤prompts 三红线（404 处置 / 预算达上限行为 / 用户给的接口也要实测、不推 DevTools）；测试 27 → 29 项 |
| v2.6 | 2026-09-02 | **§6.5 会话记忆两修（上下文断链）**：用户实测 REPL 中 Agent 不知道前几轮讨论的评测地址——①放弃轮整段截断消息历史（ask_user 答案一并丢失）；②历史只在进程内存，中断重开后草稿续作只有文件没有对话。修复：①放弃改「文件回滚 + 对话保留 + 显式回滚说明」；②对话要点持久化 `workspace/agent_sessions/<root 摘要>.json`（≤40 条），续作注入（≤24 条、单条 400 字）+ 勿重复追问指引，CLI 显示续作提示；Ctrl+C 中断轮仍整段截断；详见 §6.5 落地注记 |
| v2.7 | 2026-09-02 | **§6.6 P0 实测迭代三（凭证录入断链与字段分析）**：真机会话暴露——①Agent 把两个字段打包进一次 credential 调用（`field="username,password"` 整串存成一个键名），probe_login 逐字段查不到报 missing_fields，Agent 又按 hint 里「或提示用户 secrets set」的岔路让用户**另开终端跑命令**录入（用户反馈：应会话内直接帮用户录入）；②Agent 未用真实表单字段而用常见约定（SPA 表单 JS 渲染，静态 HTML 无 form 可解析）。修复：①ask_user(credential) 硬门禁一次只录一个字段（多字段打包拒绝）；②missing_fields hint 改单通道指引（会话内逐字段 ask_user 直接收集，删「secrets set」岔路——那是非交互/CI 备用通道）；③discover_login 增 **field_hints**——从前端包 JS 提取真实登录字段键名（account/password/captcha 等，按首次出现 ≤10），字段拟定优先级改为 fields/field_hints（真实提取）> 常见约定（兜底）；④prompts 三处同步（credential 规约/④步/hint 优先级）；测试 29 → 32 项（含 ask_user 录入 → probe_login 立即可读的会话内闭环回归） |
| v2.8 | 2026-09-02 | **§6.6 P0 实测迭代四（POST-only 接口被 GET 探测误杀）**：用户直接提供登录 API 地址 `…/users/login`，probe_url（GET）得 404（POST-only 接口 GET 即 404，Express 系未匹配方法回 404 而非 405），next_step 指引只覆盖「路径未匹配→要页面地址」分支——Agent 怀疑用户地址，逐路径重猜 + 对接口地址空跑 discover_login。修复：①probe_url ≥400 next_step 补语义（POST-only 接口 GET 404 属正常；用户给的登录 API 直接 probe_login POST 实测）；②discover_login 识别传入地址疑似接口（响应非 HTML）→ 返回 note 指引直接构建 login_cfg 走 probe_login、无需页面发现；③prompts 增「用户提供的登录 API 地址是权威输入」红线 + ②步跳过发现分支；测试 32 → 34 项 |
| v2.9 | 2026-09-02 | **§6.6 P0 实测迭代五（指引并存致滑回 + probe_login 存在性探测）**：复测发现 discover_login 已正确提示「疑似接口→直接 probe_login」、Agent 也复述认可——但仍退回 probe_url 逐路径猜，始终未发起 probe_login。根因：①返回里 note 与 next_step **并存且方向相反**（note=直接实测，next_step=无候选→问用户），Agent 权衡后滑回旧习惯；②probe_login 无低门槛入口（没字段没凭证时构建模板+收凭证门槛高，probe_url 便宜）。修复：①接口场景**直接覆盖 next_step**（单一权威指引，删并存 note）；②probe_login 增**存在性探测**语义——最小 login_cfg（body_template `'{}'`）POST 空体：404=路径不存在、400/401/422=接口存在（路由已匹配校验/鉴权未过），next_step 按状态分支给动作（404 交用户核对 / 4xx 收集更正凭证重测 / 成功落配置）；③新凭证录入解锁该 ref 防锁（一次录入换一次实测，循环被录入交互天然限流）；④prompts 同步（勿再用 probe_url 试路径 / 权威输入即时实测 / 两条解锁重试通道）；测试 34 → 37 项 |
| v2.10 | 2026-09-02 | **§6.6 泛化重构：前端包分析原语（迭代六/七定稿）**：实测暴露两类问题——①交互断链：凭证录入提示只有「请输入 ref.field」（用户不知道在输入什么）、probe_login 预览只显示 host（Agent 抄错路径 `/us/login` 用户在预览里看不见）；②能力硬编码：Agent 对「登录契约藏在路由级异步分块、接口域以 axios baseURL 形态分离」的真实 SPA 无能为力，而既有 JS 阶梯全是逐站点失效的关键字正则。修复按用户判词「不要 hardcode，要泛化分析能力」执行：代码收缩为机械原语（抓取入缓存 + search_content 检索 + stdlib HTML 结构解析无语义过滤 + paths 由 Agent 自拟），分析知识上移 LLM + prompts 方法论（前端包分析法：检索→读摘录→分块跟随→基址组合→实测）；ask_user credential 增 desc 必带、probe_login 预览改完整 URL；详见 §6.6 泛化重构节；测试 37 → 41 项（全套 735 绿） |
| v2.11 | 2026-09-02 | **§6.6 实测迭代八（模板语法无校验 + 防锁键缺路径，复现实验定谳）**：会话日志取证 + chat 包真机对照（chat 契约 POST /users/login 200+token 提取成功，服务端与地址无责）定位三层根因：①Agent 写 `${var}`（shell 风格）占位符，probe_login 用 Jinja2 渲染后原样发出，服务端报「格式不是手机号」被 Agent 误归因用户输入、让用户重输两次（复现：同报文 400 `格式不是手机号`）；②防锁键 `(ref, host, template)` 缺路径维度——猜错的 `/api/auth/login` 失败连坐用户随后给出的正确 `/users/login`，只能靠录入凭证旁路解锁；③Agent 从路由字符串猜分块文件名（真名在主包映射里，检索词清单无 `async.js`）、滑回路径猜测被 catch-all 全 200 误导。修复：①防锁键改 `(ref, 完整URL, template)`；②probe_login 渲染后残留占位符（`${...}`/`{{...}}`/`{%...%}`）一律拒发并返回 Jinja2 语法纠正（含常量字段写字面值指引）；③prompts 三红线（预览即最终报文、见占位符即语法错误；分块名从主包映射检索读取禁止凭路由猜；probed_path 非 404 即存在在 catch-all 上不可信、存在性以实测为准）；测试 41 → 43 项（全套 737 绿） |
| v2.12 | 2026-09-02 | **§6.6 实测迭代九（预算耗尽在分块映射读出的前一步）**：复测会话里 Agent 已走对分块跟随方法（检索出路由映射 `9258:"login__teacher__index"`），但 search_content 15 次/轮在含噪检索（post/user/token 命中 axios 库代码）与 js/css 双 hash 表分辨中被烧光，差最后一步达上限。修复（用户要求放大额度）：①预算 probe_url 15 → 20、search_content 15 → 30（发现是分析主循环，从宽只兜空转）；②**抓取缓存改跨轮保留**——原 `new_turn()` 连缓存清空，预算报错指引的「回复任意消息开新轮续查」实际要先重抓重搜 1.7MB 主包回到原地，放大的预算也会先耗在重复劳动上；改后缓存会话内有效（容量有界 8 文件 × 3MB），新轮直接检索续查，prompts 同步；测试同步（new_turn 保留缓存断言） |
| v2.13 | 2026-09-02 | **§6.6 实测迭代十（协议配置未验证即落盘，执行评测 404）**：创建会话把全部预算花在登录攻克（登录实测 200+token ✅）后，**probe_protocol 调用 0 次**就把入口页面域写进 `base_url`、`protocol_flavor: commands` 从 chat 参照包继承——执行时 commands 端点 404（该域只有网页）。修复：**红线从提示升级为落盘门禁**——`PackageAgent._gate_and_commit` 增 `_sut_protocol_gate`，sut_configs 声明 `channel: agent_protocol` 而 base_url 主机未经本会话 `probe_protocol` 实测（`SUTProbeToolServer.protocol_hosts` 记录）→ validation error 注入回改轮，未过不落盘；prompts ③ 步同步门禁存在与「接口域 ≠ 页面域」。配套执行侧修复见 arch/03 v4.6.7（本地模拟标注 / 导出层兜底 / host 边界 / 停止即兴引导） |
| **v3.0** | 2026-09-02 | **§六 定位升维：PackageAgent → WorkbenchAgent（工作台 Agent），方案稿**（用户判词：「CLI 的 agent 不只是场景包创建/修改，还有数据修改、开源数据下载处理等复杂任务——应升维为与 Claude Code 类似的 agent，方案与代码组织方式一并优化」）。①定位分层：对标 Claude Code = **通用会话机 + 按域装配工具面（profile）+ 统一红线策略**，§六更名「工作台 Agent」、§6.1–6.6 保留为场景包域落地记录；②新增 **§6.7 会话机方案**（实测复盘：80 步撞线回滚致全失忆——语义转变 **D-WB-4「唯一的失败是用户放弃」**，上限=暂停；P0 salvage（MemorySaver 检查点 + 孤儿 tool_call 修复，成功路径架构不变）/ P1 自动分段续跑（单段阀 + 分段上限 + checkpoint 事件）/ P2 BudgetGuard 预算缰绳 + `--max-turns/--max-segments/--budget-usd` 配置化 / P3 进度外置（验证结论即写暂存草稿））；③新增 **§6.8 组织方式**（package_agent→workbench_agent 等一次性迁移表 + 域装配档位 + staging/网络红线泛化为工作台级策略）；④新增 **§6.9 域路线图**（数据集复用 arch/10 DatasetManager / 包内数据修改 / 运行域；需求侧同步待办标注）。本版仅方案，代码迁移随会话机实施 |
| **v3.1** | 2026-09-02 | **工作台 Agent 入口与首屏 UX 方案**（用户诉求：start 菜单项随 Agent 定位调整 + 启动后给自我介绍）：①新增 **§3.5 主菜单一级入口「工作台 Agent」**——Agent 从域内动作升为工作台首选工作方式；域内两项入口降格为「档位快捷方式」（预载选中包上下文，对标 cwd 启动 claude）；`--domain agent` 直达；Agent 入口 preflight 阻断未配模型（区别于查看类「只提示不阻断」）；②新增 **§6.10 启动横幅与自我介绍**——五要素（身份/任务对象与能力域/使用示例/红线与确认/控制方式）+ 场景包域成稿文案；文案资产化（prompts 资产 `intro` 段按档位字面 replace 渲染，CLI 只渲染不写死，新域上线改资产不改代码）；rich Panel 渲染、`--json`/非 TTY 静默。随 §6.8 会话机切换一并实施 |
| **v3.2** | 2026-09-02 | **§6.11 代码质量与开源规范优化，方案稿**（开源前置 review：①结构知识 hardcode ②常量散落）。**§6.11.1 结构知识外置**：新资产 `assets/guides/scenario-package-format.md`（随包发布、与 arch/13 §四同步）+ `read_guide(topic)` 工具 + prompts 瘦身（「内容规范」段退役、参照指引收敛到工具返回、结构字段表全部移出）+ 真相源分层（validate 门禁=硬真相，guide 漂移最坏多一轮回改不产生坏包）；**§6.11.2 常量归集与命名**：按可变性分层（tunables → `WorkbenchAgentConfig` frozen dataclass，与 §6.7 P2 CLI 旗标同载体合流；固定阈值就近具名统一 `_MAX_*`）+ 常量盘点表 + `PACKAGE_ROOT` 违规修正 + `scenario_agent.py` 拆分（流式渲染迁 `console/agent_stream.py`）+ `sut_probe_tools.py` 拆分（P1）+ ToolSpec 描述漂移修正。随 §6.7/§6.8 切换实施；PACKAGE_ROOT / 描述修正可独立先行 |
| **v3.3** | 2026-09-03 | **v3.0–v3.2 全案落地收官**（feat/agent-sut-debug，9 提交，单测 735 → 777 绿）：**①§6.8 组织迁移**——`package_agent.py→workbench_agent.py`、`package_tools.py→workbench_tools.py`、`cli/cmds/scenario_agent.py→cmds/workbench_agent.py`、prompts 资产更名 `workbench_agent_prompts.yaml`（D-CLI-6 一次性切换，无兼容层）；**②D-WB-2 分段装配**——prompts 拆 `system_prompt_base`（会话机段零域语义）+ `domain_segments` + `domain_labels`，`_build_system_prompt` 统一字面 replace，未装配域报错，凭证明文红线升格域无关泛化表述；**③§6.7 会话机 P0–P3**——MemorySaver salvage + 孤儿 tool_call 修复（D-WB-4/5）、撞线自动分段续跑 + checkpoint 事件（P1）、BudgetGuard 预算缰绳 + `WorkbenchAgentConfig` tunables 单点 + `--max-turns/--max-segments/--budget-usd`（P2）、prompts 进度即写盘规约（P3）、REPL「继续/放弃」处置闭环（落地注记见 §6.7）；**④§6.10 横幅**——intro 资产五要素 + rich Panel + `--json`/非 TTY 静默 + §3.5 一级入口/`--domain agent`/preflight 阻断；**⑤§6.11 质量**——结构知识外置 `assets/guides/scenario-package-format.md` + 泛化 `read_file/list_files` 分级授权（read_guide 专用工具否决，泛化为 Claude Code 式读写机制）、流式渲染拆 `console/agent_stream.py`、**P1 probe 拆分** `agent/probe/` 包五模块（fetch/discovery/protocol/login mixin + server 组装壳，D-WB-7 一域一 server 不变）、ToolSpec 描述修正。langgraph 缺席优雅降级；需求侧同步待办（req/04 通用域条目）仍开放 |
| **v3.4** | 2026-09-03 | **§3.5/§6.10 实测反馈修订：入口直入对话，横幅先于输入**（用户反馈：①横幅在需求输入之后才显示，顺序反了；②「工作台 Agent」入口不应再有「新建/改包」菜单——这些能力应在对话中实现，介绍时说明能力并给样例即可）。①`agent_workbench_entry` 去前置菜单：`_guard_llm_ready` → 横幅（能力+示例四条）→ 直入 REPL；默认任务对象 = 新包草稿（归位提示保留），会话结束按清单 id 归位 `cwd/<id>-package/`、空会话退出清理草稿、中断保留草稿（`--output` 指回续作）；②改已有项目包为会话内能力——prompts 域段新增「改造已有项目包」规约（read_file 读入→草稿改造→归位冲突不覆盖交用户处置）；③`_session(show_intro=False)` 抑制重复横幅，`scenario new/edit --mode agent` 直连命令仍自带横幅；④`_render_intro` Panel 定宽 ≤100 列（超宽终端防 CJK 双宽渲染截断——实测贴图丢行即此因，内容本体三档宽度渲染零缺失）；⑤样例改写：创建+探测主轴 / 改 `./study-trip-package` / 参照 chat 新建 / 执行报错排查。`scenario new/edit` 命令与域内快捷方式保留为显式直达 |
