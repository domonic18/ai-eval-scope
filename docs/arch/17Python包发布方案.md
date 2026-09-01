# Python 包发布方案（evaluator → PyPI）

> 本文档评估 evaluator（Python 包 `agent_eval`，CLI `agent-eval`）走向**公开发布**的完整方案：Jenkins 独立流水线（检查 / 单测 / 发布）+ 用户 `pip install` / `uv` 直装。包构建沿用 [06 数据管理与配置规范](./06数据管理与配置规范.md) 的资产布局（`agent_eval/assets/` 随包发布）；CI 形态对齐 [cicd/README.md](../../cicd/README.md) 的「单仓多流水线」架构；CLI 面见 [15 CLI 交互式评测工作台设计](./15CLI交互式评测工作台设计.md)。
>
> 本文为**方案评估**（2026-09-01）：不改代码、不建流水线；落地拆解见 §7 与 [01 迭代开发计划](../plan/01迭代开发计划.md)。

---

## 一、目标与范围

| # | 目标 | 衡量 |
|---|------|------|
| G1 | Jenkins **独立流水线**完成包检查、单测、发布 | PR 流水线守质量；发布流水线守制品，互不掺和 |
| G2 | 用户 `pip install` / `uv` 直装即用 | `pip install ai-eval-scope` 后 `agent-eval --help` 可跑，无需 clone 仓库 |
| G3 | 发布过程可演练、可回退 | TestPyPI 先行；版本纪律明确（PyPI 不可变） |
| G4 | 开源门面合规 | license/元数据符合 PyPI 现行政策（PEP 639）；无内部信息泄漏 |

**不含**：私有 PyPI 源建设（未来需要时经 `uv publish --publish-url` 补通道）；Web/executor 制品发布（已由 CCR 镜像流覆盖）。

## 二、现状盘点（2026-09-01）

### 2.1 包与构建

| 项 | 现状 | 发布视角的问题 |
|----|------|---------------|
| 构建后端 | hatchling；`[tool.hatch.build.targets.wheel] packages = ["agent_eval"]` | ✅ assets（1.7M/50 文件）随包打入，无需额外配置 |
| 包名 | `agent-eval`（pyproject L6） | ❌ **PyPI 已被占用**（[allenai agent-eval](https://pypi.org/project/agent-eval/)，Inspect 格式评测工具），必须改名 |
| 版本 | `version = "0.1.0"`（pyproject）与 `agent_eval/__init__.py:__version__` **双处维护**；`[tool.commitizen] version_provider = "scm"` 已配但未收敛 | ❌ 双处漂移风险；发布流水线需要「tag == 包版本」断言 |
| dev 依赖 | `[project.optional-dependencies].dev`（ruff/pytest/commitizen…+ 自引用 `[llm][vision]`） | ❌ **会随发布进 PyPI 元数据**——行业惯例 dev 依赖不入发布；另有 PEP 735 `[dependency-groups].dev`（仅 types-pyyaml）与之并存 |
| license | `license = {text = "MIT"}` + classifier；根目录有 LICENSE，**evaluator/ 无** | ❌ sdist/wheel 不含 LICENSE 文件；PyPI 现行政策要求 PEP 639 SPDX 声明 |
| README | evaluator/README.md 无安装章节 | ❌ PyPI 项目页缺安装指引 |
| executor 联动 | executor/pyproject.toml 以 `[tool.uv.sources] agent-eval` **editable path 依赖**复用 ../evaluator | ⚠️ 改名须同步（依赖名 + sources 键） |

### 2.2 CI 现状

- `cicd/Jenkinsfile.eval.groovy`：setup-python.sh（腾讯镜像装 python3+uv）→ `uv sync --extra dev` → ruff（非阻塞）→ mypy（非阻塞）→ pytest（阻塞，JUnit+覆盖率）。**无 build/publish 阶段、无凭证引用**（凭证惯例：git 凭据在 Job 配置、registry 凭据在使用点 `docker-build.groovy::docker.withRegistry`）。
- `.github/workflows/ci.yml`（GitHub Actions）：开源仓库门面质量门禁，与 Jenkins 并存。
- 发布工具链：uv 已在两个 CI 环境可用；`uv build` / `uv publish` 零新依赖。

### 2.3 名称核查（2026-09-01 实查）

| 名 | PyPI 状态 | 结论 |
|----|-----------|------|
| `agent-eval` | ❌ 已占用（allenai，Inspect 格式评测） | 不可用 |
| `ai-eval-scope` | ✅ 未占用（且与 pyproject 已填的 GitHub 仓库名 domonic18/ai-eval-scope 一致） | **采用** |

## 三、关键决策

| # | 决策 | 理由 |
|---|------|------|
| D-PKG-1 | **distribution 改名 `ai-eval-scope`**；import 名 `agent_eval` 与 CLI 名 `agent-eval` **不变** | 旧名被占用；命令名与包名解耦是行业惯例（pip 之于 pip-tools）；用户代码与全部文档零改动 |
| D-PKG-2 | **公开 PyPI 为主**：tag `v*` 触发 Jenkins 发布；TestPyPI 先行演练 | 符合「CLI 为开源门面」定位；Jenkins 在内网但发布仅需出网到 `upload.pypi.org:443` |
| D-PKG-3 | **版本单源 = commitizen**：`version_provider = "pep621"` + `tag_format = "v$version"` + `version_files = ["agent_eval/__init__.py:__version__"]`，`cz bump` 一次改两处并打 annotated tag | 顺承现状零新依赖；构建时版本在源码里（确定性构建）。~~原配 `scm` provider~~ **落地时纠正为 pep621**：scm provider 只读（git describe 派生、不写任何文件），且本仓历史无 tag 基线——wheel 版本将恒停 0.1.0。备选 hatch-vcs 动态版本**不采用**：构建依赖 git 元数据（clone 缺 tag 即失败），且与 commitizen 职责重复 |
| D-PKG-4 | **独立发布流水线** `cicd/Jenkinsfile.pypi.groovy`，不扩展 eval 流水线 | 职责分离：PR 流水线守质量（每次 push）、发布流水线守制品（仅 tag）；对齐「单仓多流水线，每交付物一条」既有架构 |
| D-PKG-5 | **dev 依赖迁出发布元数据**：`[project.optional-dependencies].dev` → `[dependency-groups].dev`（PEP 735）；全仓 `uv sync --extra dev` → `--group dev` | 发布的包元数据只含用户可用的 extras（llm/agent/vision/datasets）；dev 组 uv 原生支持且不入 wheel |
| D-PKG-6 | **license 合规**：LICENSE 复制入 evaluator/ + `license = "MIT"`（SPDX 字符串，PEP 639）+ `license-files` | PyPI 现行政策；hatchling 原生支持 SPDX 表达式 |

## 四、版本与发布物策略

- **发布物**：sdist + wheel 双产物（`uv build` 默认）；纯 Python wheel（通用），vision extra 的 playwright 由用户侧安装。
- **版本节奏**：PEP 440；`cz bump`（Conventional Commits 驱动）→ 改 pyproject + `__init__.py` → 生成 CHANGELOG → 打 annotated tag `v$version` → 推 tag 触发发布流水线。
- **不可变性纪律**：PyPI 同版本号不可重传——发布失败修复合后**必须 bump 版本**；重大问题可 yank（隐藏不删除）。这是把 TestPyPI 演练前置为强制步骤的原因。

## 五、Jenkins 发布流水线设计

### 5.1 Job 与凭证

| 项 | 值 |
|----|----|
| Jenkinsfile | `cicd/Jenkinsfile.pypi.groovy`（新增） |
| Job 形态 | Pipeline Job，tag 触发（工蜂 tag webhook 或参数 `TAG`）；`disableConcurrentBuilds` |
| 凭证 | 新增 `pypi-upload-token`（Secret text，**project-scoped API token**，见 §8 准备清单）——注入 `UV_PUBLISH_TOKEN` |

### 5.2 阶段草案

```groovy
pipeline {
  agent any
  options { timestamps; timeout(time: 20, unit: 'MINUTES'); disableConcurrentBuilds() }
  environment {
    PYPI_MIRROR = 'https://mirrors.cloud.tencent.com/pypi/simple'
    PYPI_HOST   = 'mirrors.cloud.tencent.com'
  }
  stages {
    stage('环境准备') { steps { sh 'bash cicd/scripts/setup-python.sh' } }
    stage('质量门禁') {   // 复用 eval 流水线命令：ruff + mypy（非阻塞）+ pytest 全量（阻塞）
      steps { dir('evaluator') {
        sh 'uv sync --group dev --default-index ${PYPI_MIRROR}'
        sh 'uv run ruff check agent_eval/ tests/ && uv run mypy agent_eval/ --ignore-missing-imports'
        sh 'uv run pytest tests/ -v --tb=short --junitxml=report/test-results.xml'
      } }
    }
    stage('构建') { steps { dir('evaluator') { sh 'uv build' } } }  // dist/ 下 sdist+wheel
    stage('校验') {   // 版本一致性 + 双产物冒烟（uv 官方范式）
      steps { dir('evaluator') {
        sh '''#!/bin/bash
          set -euo pipefail
          TAG="${TAG:-${GIT_REF#v}}"
          VER="$(uv run python -c "import agent_eval; print(agent_eval.__version__)")"
          [ "v${VER}" = "${TAG}" ] || { echo "tag(${TAG}) != 包版本(${VER})，禁止错发"; exit 1; }
          uv run --isolated --no-project --with dist/*.whl  agent-eval --version
          uv run --isolated --no-project --with dist/*.tar.gz agent-eval --version
        ''' }
      }
    }
    stage('发布') {
      when { buildingTag { comparator: 'REGEXP', pattern: 'v.*' } }  // 仅 tag 构建发布
      steps { dir('evaluator') {
        withCredentials([string(credentialsId: 'pypi-upload-token', variable: 'UV_PUBLISH_TOKEN')]) {
          sh 'uv publish'   // TestPyPI 演练期改：uv publish --publish-url https://test.pypi.org/legacy/
        }
      } }
    }
  }
}
```

要点：

- **校验段的版本断言**是防错发核心：tag 与 `__version__` 不一致立即失败（D-PKG-3 双处版本由 `cz bump` 保证同步，此处为兜底断言）。
- **冒烟即验收**：wheel 与 sdist 各自在隔离环境装包跑 `agent-eval --version`（uv 官方发布指南同款范式），不通过不发布。
- **分支构建只验不发**：`when buildingTag` 保证非 tag 触发时流水线退化为「构建演练」。
- **Jenkins vs GHA 分工**：Jenkins（内网）为主发布通道（用户要求，凭证集中管理）；GHA 保留公网质量门禁，未来若要免 token 可切 PyPI **Trusted Publishing**（OIDC，仅 GHA 支持）——Jenkins 不适用，走 API token 是行业标准做法。

### 5.3 TestPyPI 演练步骤（首发前必做，落到操作序列）

草案已落地为 [`cicd/Jenkinsfile.pypi.groovy`](../../cicd/Jenkinsfile.pypi.groovy)（以入库文件为准：`RELEASE_TAG` 兼容 tag 触发/`TAG` 参数、`TEST_PYPI` 演练开关、冒烟加 `--refresh`）。演练序列：

1. **TestPyPI 侧**（§8-P3）：注册 + 2FA + 生成 token → Jenkins 新建 credential `pypi-upload-token`（演练期先存 TestPyPI token）+ Pipeline Job（Script Path `cicd/Jenkinsfile.pypi.groovy`）。
2. **本地起版**：`cd evaluator && uv run cz bump --dry-run --increment PATCH --yes` 核对 → 去掉 `--dry-run` 实跑（改 pyproject + `__init__` + CHANGELOG + 打 tag）→ `git push origin <branch> --tags`。
3. **触发**：Jenkins Job 带 `TAG=v0.1.0`、`TEST_PYPI=true` 构建 → 观察「校验」段版本断言与双产物冒烟 →「发布」段上传 TestPyPI。
4. **验收安装**：`uv run --isolated --no-project --with ai-eval-scope --index-url https://test.pypi.org/simple/ agent-eval --version`（注意 TestPyPI 依赖不全时需 `--index-strategy unsafe-best-match` 或混合官方源）。
5. **转正**：Jenkins credential 换 PyPI project-scoped token（§8-P2），`TEST_PYPI=false` 重跑即正式发布。

## 六、用户安装体验（目标态）

```bash
# 基础：规则评估 + CLI 工作台（无 LLM 依赖）
pip install ai-eval-scope

# 常用：执行引擎（DeepAgents）+ LLM Judge
pip install "ai-eval-scope[agent]"          # run/pipeline 需此 extra

# uv 用户（推荐，秒装）
uv tool install "ai-eval-scope[agent,vision]"
uvx --from "ai-eval-scope[agent]" agent-eval --help   # 免安装试用
```

| extras | 语义 | 关键依赖 |
|--------|------|----------|
| （基础） | 规则评估 / `eval` / `scenario` / `runs` / 工作台 | typer、pydantic、rich… |
| `llm` | LLM Judge（文本评估） | openai、anthropic、langfuse |
| `agent` | 执行引擎 `run/pipeline`（DeepAgents 底座，惰性导入） | deepagents、langgraph |
| `vision` | 截图视觉评估 | `agent-eval[llm]` + playwright==1.60.0 |
| `datasets` | 数据集下载 | huggingface_hub、modelscope |

环境要求 Python ≥3.11。装包后的配置路径（LLM `models set` / SUT 凭证 `secrets set` / 平台身份 `auth login`，密钥区三文件）不变，指引链接 [CLI 使用教程](../guide/CLI使用教程.md)。

## 七、发布前置改造清单（落地拆解）

| # | 改造 | 影响文件 | 量级 | 状态 |
|---|------|----------|------|------|
| 1 | 改名 `ai-eval-scope`：pyproject `name`、extras 自引用 `agent-eval[llm]` → `ai-eval-scope[llm]`、executor 的 dependencies + `[tool.uv.sources]` 键、重锁 `uv.lock` | evaluator/pyproject.toml、executor/pyproject.toml、uv.lock ×2 | 小 | ✅ 已落地（双端重锁，make check 全绿） |
| 2 | 版本单源：commitizen `version_provider = "pep621"` + `version_files` 覆盖 `__init__.py::__version__`；演练 `cz bump --dry-run`（0.1.0 → 0.1.1 + tag v0.1.1 ✓） | evaluator/pyproject.toml | 小 | ✅ 已落地 |
| 3 | dev extras 收敛（D-PKG-5）：合并两组 dev 依赖至 `[dependency-groups]`（组内自引用 `[llm]`/`[vision]` 拉起测试依赖）；全仓 `uv sync --extra dev` → `--group dev`（Makefile / Jenkinsfile.eval / GHA ci / CONTRIBUTING / CLAUDE.md / README；executor 的 dev extras 属其自身，不动） | pyproject、Makefile、cicd/Jenkinsfile.eval.groovy、CLAUDE.md ×2、evaluator/README.md、CONTRIBUTING.md、.github/workflows/ci.yml | 中 | ✅ 已落地 |
| 4 | license 合规（D-PKG-6）：LICENSE 入 evaluator/、SPDX 字符串 + license-files（PKG-INFO 实测 `License-Expression: MIT` + `License-File`，Metadata 2.5） | evaluator/LICENSE、pyproject | 小 | ✅ 已落地 |
| 5 | README 补安装章节（§6 内容）+ PyPI 徽章；另补 CLI `--version` 旗标（eager，发布冒烟口令，此前仅有 `version` 子命令） | evaluator/README.md、cli/main.py | 小 | ✅ 已落地 |
| 6 | Jenkins：`cicd/Jenkinsfile.pypi.groovy` 入库（含 TEST_PYPI 演练参数 + 冒烟 `--refresh` 防缓存假通过）；控制台侧 credential `pypi-upload-token` + 发布 Job 待建 | cicd/Jenkinsfile.pypi.groovy、cicd/README.md | 运维 | ◐ 文件已入库，控制台操作待用户 |
| 7 | TestPyPI 全流程演练 → 正式发 `v0.1.0`（首个版本即占名，§8-P6） | — | 半天 | ⬜ 待用户执行（§5 末演练步骤） |
| 8 | **开源内容审查**（见 §9 风险 R1/R2）：内部域名、数据集版权、git 历史密钥扫描 | assets/packages/chat、git 历史 | **必须** | ◐ R1 域名占位化已落地（§9 行内更新）；R2 gitleaks 全史扫描已跑；数据集版权待复核 |

## 八、发布前准备清单（账号与凭证）

| # | 事项 | 说明 |
|---|------|------|
| P1 | **PyPI 账号** | [pypi.org](https://pypi.org/account/register/) 注册，**建议团队公共邮箱**；完成邮箱验证（未验证不能上传）；**强制开启 2FA**（TOTP/硬件 key），recovery codes 妥善保存。建议创建 **PyPI Organization** 挂项目（人员变动不影响所有权） |
| P2 | **API Token** | Settings → Add API token，`pypi-` 开头**只显示一次**。顺序：首个版本用 account-scoped token（或先 TestPyPI）→ 项目创建后**立即换 project-scoped**。token 即入 Jenkins `pypi-upload-token`。PyPI 已停用账号密码，上传只认 token（uv 的 `UV_PUBLISH_TOKEN` 已封装） |
| P3 | **TestPyPI 账号** | [test.pypi.org](https://test.pypi.org) 与主站**账号不通用**，单独注册 + 2FA + token；首次发布在此演练全流程（主站版本不可重传，没有后悔药） |
| P4 | **GitHub 侧** | `domonic18/ai-eval-scope` 已确认为**个人仓库**——个人仓库可直接发布（包名归属以 PyPI 侧为准，与仓库归属独立）；若后续团队化，再迁移 GitHub Organization（仓库 Transfer）+ PyPI Organization（项目 owner 可转移），PyPI 项目名不受影响；未来切 GHA Trusted Publishing 时在 PyPI 项目 → Publishing 配置 publisher（须与发布仓库归属一致） |
| P5 | **网络策略** | 确认 Jenkins 构建机**出公网可达 `upload.pypi.org:443`**（内网常见卡点，提前申请） |
| P6 | **名称占位** | PyPI 无「预订名」机制，首个版本成功上传即占住 `ai-eval-scope`；准备期可先占 GitHub 侧命名 |

## 九、风险与开放问题

| # | 风险 | 缓解 |
|---|------|------|
| R1 | **内部信息随 wheel 公开**：内置 chat 包 sut_configs 曾含内部 staging 域名（`agent-server.staging.bj33smarter.com`、`sasan-server.staging.bj33smarter.com`）与内部 modelId/userId 注释 | ✅ **已缓解（落地）**：sut_config 新增 `${VAR}` / `${VAR:-默认值}` env 展开（`registry.expand_env_refs`，未配回退 `*.example.com` 占位 + 报错优于硬编码），sasan-agent.yaml 三处占位化并有测试锁死（`test_builtin_chat_package_has_no_internal_domain`）；真实端点走 `.env`（`.env.example` 有模板）。数据集版权仍待复核 |
| R2 | **git 历史泄漏**：开源 = 全历史公开 | ✅ **已扫描（gitleaks 8.30.1，598 提交全史 + 工作区）**：现役零真实泄漏——`.env`/`.claude` 被 .gitignore 正确拦截，测试命中均为 dummy key（`eval-abcdefgh1234`/`sk-test-…`），设计稿 stripe 串为编造展示值（开源前可换明显占位）。**历史 1 条真实格式平台 API Key**（`4469eb2f` DebugPage.tsx 曾硬编码 `eval-…` 完整 Key，后已删）→ **处置：平台侧吊销该 Key 即可废掉历史风险**（无需重写历史）；另 arch/12 历史版本含内部域名与截断 JWT 示例 → 开源门面仓库按本表原预案走干净基线初始化即可规避（发布 wheel 不受影响） |
| R3 | CLI 命令 `agent-eval` 与 allenai 包同名（两者都提供同名 entry point，共存安装冲突） | 文档注明；冲突真实发生时再评估改命令名（改动面大：全部 docs/scripts） |
| R4 | Jenkins 出口网络不通 | §8-P5 提前申请；兜底方案本地 `uv publish`（token 在本机环境变量） |
| R5 | executor 改名联动遗漏（path 依赖） | §7-1 同一提交内改齐 + executor CI 验证 |
| R6 | wheel 体积（内置三场景包；实测 sdist 1.0MB / wheel 804KB） | 可接受（纯文本资产）；未来膨胀再评估拆分 `ai-eval-scope-packages` |
| O1 | 开放：私有源需求是否会出现（内网用户装不了公网包） | 预留：`uv publish --publish-url` 双通道，或 CCR 制品库 pypi 能力 |
| O2 | 开放：CHANGELOG 是否对外发布 | `cz bump` 已生成，随仓库发布即可 |

## 十、行业实践对照

| 实践 | 来源 | 本方案落点 |
|------|------|-----------|
| build → 隔离冒烟 → publish 三段式 | [uv 官方发布指南](https://docs.astral.sh/uv/guides/package/) | §5 构建与校验段 |
| API token 替代账号密码（PyPI 已强制） | PyPI 官方 | §8-P2 |
| project-scoped token 最小权限 | PyPI 官方 | §8-P2 |
| TestPyPI staging 演练 | PyPI 官方 | §8-P3 |
| Trusted Publishing（OIDC 免 token） | PyPI + GitHub Actions | Jenkins 不适用，列为 GHA 演进项（§5） |
| dev 依赖不入发布元数据（PEP 735 dependency-groups） | packaging 生态 | D-PKG-5 |
| PEP 639 SPDX license 声明 | PyPI 现行政策 | D-PKG-6 |
| 命令名与包名解耦 | pip 生态惯例 | D-PKG-1（CLI 保持 `agent-eval`） |
| tag 驱动发布 + 版本断言 | setuptools-scm/hatch-vcs 生态通行 | D-PKG-3 + §5 校验段 |

## 十一、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-01 | 初稿：现状盘点（agent-eval 名称占用实查）、决策 D-PKG-1..6、Jenkins 发布流水线草案（`Jenkinsfile.pypi.groovy`）、安装体验与 extras 矩阵、前置改造清单、账号/凭证准备清单、风险与开放问题 |
| v1.1 | 2026-09-01 | §7 八项落地：改名/重锁、版本单源（**D-PKG-3 纠正 scm→pep621**，scm 只读且无 tag 基线）、dev 迁 PEP 735 组、LICENSE PEP 639（Metadata 2.5 实测）、README 安装章 + `--version` 旗标、`Jenkinsfile.pypi.groovy` 入库（+§5.3 TestPyPI 演练步骤）、R1 域名占位化（env 展开机制）；本地构建 + 隔离冒烟 + make check（683+56）全绿 |
