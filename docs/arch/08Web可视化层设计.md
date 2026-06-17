# Web 可视化层设计

> ⚠️ **已废弃（历史存档）**：本文档描述的 Sprint 7a 本地 workspace 查看 MVP（React + Express 读本地 JSON、`/api/projects`、`/api/index/rebuild` 等）已被推翻。可观测平台现采用 [09 Web 可观测平台架构设计](./09Web可观测平台架构设计.md)（PostgreSQL + 对象存储 + 多租户 + API Key 摄取）。遗留 MVP 的前端与后端路由已于 Sprint 7c 后统一移除，前端待 Sprint 7f 按 09 重建。**新功能请以 09 为准。**

> 本文档详细阐述 Web 可视化层的设计，包括技术选型、前后端架构、页面设计、API 定义、数据模型与腾讯云函数部署方案。属于 [01 整体架构设计](./01整体架构设计.md) §二中"Web 可视化层"的详细展开。数据管理与配置规范参见 [06 数据管理与配置规范](./06数据管理与配置规范.md)。

---

## 一、设计目标与范围

### 1.1 设计目标

| 目标 | 说明 |
|------|------|
| **项目级看板** | 以项目为维度聚合评估运行，展示最新状态与快速统计 |
| **趋势可追溯** | 展示 DR / CPR / Reward 等核心指标随时间的变化曲线 |
| **报告详情** | 支持查看单次评估运行的详细报告与任务级结果 |
| **零配置启动** | 通过 CLI 命令一键启动，无需额外配置 |
| **云端可部署** | 适配腾讯云函数部署，支持在线访问 |

### 1.2 范围

- **包含**：项目看板、趋势图、运行详情、任务详情、LLM 溯源展示
- **不包含**：规则编辑界面（P2）、人工仲裁界面（P2）、用户认证（远期）

---

## 二、技术选型

### 2.1 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18+ | 组件化 UI，社区生态丰富 |
| **UI 组件库** | Ant Design | 企业级 UI 组件，表格/图表/表单支持好 |
| **图表** | ECharts | 趋势折线图、柱状图、仪表盘 |
| **HTTP 客户端** | Axios | 前端 API 请求 |
| **后端** | Express (Node.js) | 轻量、适合 API 服务 |
| **数据读取** | 直接读取 workspace JSON 文件 | MVP 阶段无需数据库 |
| **构建** | Vite | 前端快速构建 |
| **部署** | 腾讯云函数 (SCF) | Serverless 部署，按需调用 |

### 2.2 选型理由

- **React + Express**：用户明确要求，团队有项目经验，适配腾讯云函数部署
- **文件读取而非数据库**：与现有 workspace 文件系统架构一致，MVP 阶段零额外依赖
- **ECharts**：中文文档完善，图表类型丰富，支持趋势图/雷达图/仪表盘等

---

## 三、前端页面设计

### 3.1 页面总览

| 页面 | 路由 | 功能 | 数据源 |
|------|------|------|--------|
| 项目列表 | `/` | 展示所有项目、最新运行状态、快速统计卡片 | `projects.json` + `runs_index.json` |
| 项目详情 | `/project/{id}` | 趋势图表、运行历史列表、阈值线 | `runs_index.json` 按 project_id 过滤 |
| 运行详情 | `/run/{id}` | 汇总卡片、维度分解、任务级结果表 | `reports/summary.json` + `results/` |
| 任务详情 | `/run/{id}/task/{task_id}` | 约束逐项结果、LLM Judge 溯源、输出预览 | `results/{task_id}/rule_results.json` + `scores.json` |
| 目录模式任务详情 | `/run/{id}/task/{task_id}` (同上) | 目录树可视化、模块级状态、文件级热力图 | `rule_results.json` + `output/_manifest.json` |

> 目录模式任务详情与普通任务详情共享同一路由，前端根据 `rule_results.json` 中是否存在 `module_results` 字段自动切换展示模式。

### 3.2 项目列表页

```
┌─────────────────────────────────────────────────────────────┐
│  Agent Eval System                              [新建项目]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  课件平台 Agent                    最新: 2026-06-08    │   │
│  │  ┌────┐  ┌────┐  ┌────┐  ┌────┐                     │   │
│  │  │DR  │  │CPR │  │Reward│ │运行 │                     │   │
│  │  │0.94│  │0.88│  │1.72 │ │ 5次│                     │   │
│  │  └────┘  └────┘  └────┘  └────┘                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  数据分析 Agent                    最新: 2026-06-07    │   │
│  │  ┌────┐  ┌────┐  ┌────┐  ┌────┐                     │   │
│  │  │DR  │  │CPR │  │Reward│ │运行 │                     │   │
│  │  │1.00│  │0.95│  │2.10 │ │ 3次│                     │   │
│  │  └────┘  └────┘  └────┘  └────┘                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件**：
- ProjectCard：项目卡片，显示名称、最新指标、运行次数
- StatCard：单个指标卡片（DR/CPR/Reward），带颜色状态

### 3.3 项目详情页（趋势）

```
┌─────────────────────────────────────────────────────────────┐
│  ← 返回项目列表    课件平台 Agent                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  趋势图 — DR / CPR / Reward                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  1.0 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─     │   │
│  │      │         ┌──┐                                    │   │
│  │  0.8 │    ┌──┐ │  │ ┌──┐ ┌──┐                        │   │
│  │      │ ┌──┘  └─┘  └─┘  └─┘  │  ← DR 趋势线           │   │
│  │  0.6 │ │                     │                        │   │
│  │      │ ─ ─ ─ ─ 阈值线 ─ ─ ─ │  ← DR≥0.95            │   │
│  │      └───────────────────────┘                        │   │
│  │       06/06  06/07  06/08  06/08                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  运行历史                                                    │
│  ┌──────┬──────────┬──────┬──────┬────────┬──────────┐     │
│  │运行ID│ 时间      │ DR   │ CPR  │ Reward │ 规则集版本│     │
│  ├──────┼──────────┼──────┼──────┼────────┼──────────┤     │
│  │run_4 │ 06-08 14:30│ 0.94 │ 0.88 │ 1.72  │ v1.2     │     │
│  │run_3 │ 06-08 10:00│ 0.92 │ 0.85 │ 1.58  │ v1.1     │     │
│  │run_2 │ 06-07 14:00│ 0.90 │ 0.82 │ 1.45  │ v1.1     │     │
│  │run_1 │ 06-06 09:00│ 0.85 │ 0.78 │ 1.20  │ v1.0     │     │
│  └──────┴──────────┴──────┴──────┴────────┴──────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件**：
- TrendChart：ECharts 折线图，X 轴为运行时间，Y 轴为指标值，叠加阈值参考线
- RunHistoryTable：运行历史列表，支持按日期/得分排序

### 3.4 运行详情页

```
┌─────────────────────────────────────────────────────────────┐
│  ← 返回项目    课件平台 Agent / 运行 20260608_143000         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  汇总                                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │ 样本总数 │  │   DR    │  │   CPR   │  │ Reward  │       │
│  │   50    │  │  0.94   │  │  0.88   │  │  1.72   │       │
│  │         │  │ ⚠ BELOW │  │ ⚠ BELOW │  │  ✅ PASS│       │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘       │
│                                                             │
│  维度分解                                                    │
│  ┌──────────┬───────┬───────┬────────┬─────────┐           │
│  │ 维度      │ 得分   │ 权重  │ 状态   │ 详情    │           │
│  ├──────────┼───────┼───────┼────────┼─────────┤           │
│  │ 功能性    │ 1.00  │ 1.0   │ ✅ PASS│ [展开]  │           │
│  │ 效果性    │ 0.78  │ 1.0   │ ⚠ WARN │ [展开]  │           │
│  │ 安全性    │ 1.00  │ 1.0   │ ✅ PASS│ [展开]  │           │
│  │ 性能      │ 0.92  │ 0.5   │ ✅ PASS│ [展开]  │           │
│  └──────────┴───────┴───────┴────────┴─────────┘           │
│                                                             │
│  任务结果                                                    │
│  ┌──────────────┬────────┬───────┬────────┬───────┐        │
│  │ 任务ID       │ 状态    │ Reward│ 失败规则│ 操作  │        │
│  ├──────────────┼────────┼───────┼────────┼───────┤        │
│  │ math_g7_001  │ ✅ PASS│ 2.43  │ 0      │ [详情]│        │
│  │ math_g7_002  │ ✅ PASS│ 2.10  │ 0      │ [详情]│        │
│  │ physics_g8_001│ ❌ FAIL│ -2.00 │ 2      │ [详情]│        │
│  └──────────────┴────────┴───────┴────────┴───────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 任务详情页

```
┌─────────────────────────────────────────────────────────────┐
│  ← 返回运行    任务: math_grade7_001                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  约束结果                                                    │
│  ┌───────┬──────────────┬──────┬───────┬───────────────┐    │
│  │ 级联   │ 规则          │ 状态 │ 得分   │ 原因          │    │
│  ├───────┼──────────────┼──────┼───────┼───────────────┤    │
│  │ 格式   │ response_format│ ✅ │ 1.00  │ 有效HTML格式  │    │
│  │ 格式   │ document_count │ ✅ │ 1.00  │ 3个文档[1,20] │    │
│  │ 格式   │ html_validity  │ ✅ │ 1.00  │ 标签闭合正常  │    │
│  │ 常识   │ info_accuracy  │ ✅ │ 1.00  │ 知识点匹配    │    │
│  │ 质量   │ teaching_logic │ ✅ │ 0.85  │ 教学逻辑清晰  │    │
│  │ 质量   │ style_pref     │ ✅ │ 0.78  │ 风格简洁适当  │    │
│  └───────┴──────────────┴──────┴───────┴───────────────┘    │
│                                                             │
│  LLM Judge 溯源                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ teaching_logic                                        │   │
│  │  Provider: deepseek_judge    Model: deepseek-chat     │   │
│  │  置信度: 高 (std=0.05)        采样数: 3                │   │
│  │  Token: 450                                           │   │
│  │  [查看 JudgeRecord] → evidence/judge_soft.xxx.json    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.6 目录模式任务详情

> 当检测到 `module_results` 字段时，任务详情页自动切换为目录模式展示，增加目录树可视化和模块级状态。

```
┌─────────────────────────────────────────────────────────────┐
│  ← 返回运行    任务: courseware_unit_大单元学习总导            │
│  [目录模式]  24 个 HTML 文件 / 2 个模块 / 3 层深度            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  目录结构 + 评估状态                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 📁 大单元学习总导                          ✅ 全部通过 │   │
│  │ ├── 📁 M1 大单元概述 (6文件)               ✅ 通过    │   │
│  │ │   └── 📁 大单元概述                                 │   │
│  │ │       ├── 整体定位.html          (7KB)   ✅        │   │
│  │ │       ├── 建构性导学.html        (10KB)   ✅        │   │
│  │ │       ├── 模块定位画像.html       (18KB)   ✅        │   │
│  │ │       ├── 学习路径.html          (15KB)   ✅        │   │
│  │ │       ├── 五维导学.html          (28KB)   ✅        │   │
│  │ │       └── 解析性导学.html        (50KB)   ✅        │   │
│  │ └── 📁 M2 学习新知的新价值与新使命 (18文件)  ⚠ 部分警告│   │
│  │     ├── 📁 建构性导学 (3文件)             ✅         │   │
│  │     ├── 📁 模块定位   (2文件)             ✅         │   │
│  │     ├── 📁 解析性导学 (3文件)             ✅         │   │
│  │     └── 📁 脚手架     (9文件)             ⚠         │   │
│  │         ├── VR.html               (20KB)  ✅        │   │
│  │         ├── 工具库.html            (16KB)  ✅        │   │
│  │         ├── 名人名言.html          (14KB)  ✅        │   │
│  │         ├── 名著介绍.html           (8KB)  ❌ ←     │   │
│  │         └── ...                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  模块级评估得分                                              │
│  ┌──────────────────────────────┬────────┬────────┬──────┐ │
│  │ 模块                          │ Reward │ 状态   │ 文件 │ │
│  ├──────────────────────────────┼────────┼────────┼──────┤ │
│  │ M1 大单元概述                  │  2.21  │ ✅ PASS│  6   │ │
│  │ M2 学习新知的新价值与新使命    │  1.78  │ ⚠ WARN │ 18   │ │
│  └──────────────────────────────┴────────┴────────┴──────┘ │
│                                                             │
│  目录结构检查详情                                            │
│  ┌──────────────┬────────┬──────────────────────────┐      │
│  │ 检查项        │ 状态   │ 详情                      │      │
│  ├──────────────┼────────┼──────────────────────────┤      │
│  │ 模块数量      │ ✅ 2=2│ 实际2个模块，期望2个       │      │
│  │ 目录深度      │ ✅ 3≤3│ 实际3层，要求≤3层         │      │
│  │ 模块名称      │ ✅     │ 全部匹配                  │      │
│  └──────────────┴────────┴──────────────────────────┘      │
│                                                             │
│  [展开查看 LLM Judge 溯源...]                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件**：
- **DirectoryTree**：递归树形组件，基于 `_manifest.json` 渲染目录层级，节点颜色标识通过/失败/警告状态
- **ModuleScoreTable**：模块级得分对比表，数据来自 `rule_results.json` 的 `module_results` 字段

**数据流**：

```
rule_results.json
    ↓
检测 module_results 字段存在?
    ↓ 是
切换为目录模式展示
    ↓
DirectoryTree ← output/_manifest.json (目录结构)
ModuleScoreTable ← module_results (模块级得分)
StructureCheckDetail ← details.checks (结构检查明细)
```

### 4.1 API 端点

| 方法 | 路径 | 说明 | 数据源 |
|------|------|------|--------|
| `GET` | `/api/projects` | 列出所有项目 | `workspace/index/projects.json` |
| `GET` | `/api/projects/{id}` | 获取项目详情 | `projects.json` + `runs_index.json` 过滤 |
| `GET` | `/api/projects/{id}/runs` | 获取项目运行列表 | `runs_index.json` 按 project_id 过滤 |
| `GET` | `/api/projects/{id}/trends` | 获取趋势数据 | `runs_index.json` 聚合计算 |
| `GET` | `/api/runs/{id}` | 获取运行汇总 | `workspace/runs/{id}/reports/summary.json` |
| `GET` | `/api/runs/{id}/tasks` | 获取运行下所有任务结果 | `workspace/runs/{id}/results/` 遍历 |
| `GET` | `/api/runs/{id}/tasks/{task_id}` | 获取任务评估详情 | `results/{task_id}/rule_results.json` + `scores.json` |
| `GET` | `/api/runs/{id}/tasks/{task_id}/evidence/{file}` | 获取 LLM Judge 溯源记录 | `results/{task_id}/evidence/` |
| `GET` | `/api/runs/{id}/tasks/{task_id}/manifest` | 获取目录清单（目录模式） | `packages/{task_id}/output/_manifest.json` |
| `POST` | `/api/index/rebuild` | 重建 Workspace 索引 | 扫描 `workspace/runs/` |

### 4.2 响应格式

**GET /api/projects** — 项目列表

```json
{
  "projects": [
    {
      "id": "courseware-platform",
      "name": "课件平台 Agent",
      "description": "课件生成 Agent 的评估项目",
      "run_count": 5,
      "latest_run": {
        "run_id": "20260608_143000",
        "created_at": "2026-06-08T14:30:00Z",
        "dr": 0.94,
        "cpr": 0.88,
        "avg_reward": 1.72
      }
    }
  ]
}
```

**GET /api/projects/{id}/trends** — 趋势数据

```json
{
  "project_id": "courseware-platform",
  "metrics": ["DR", "CPR", "Reward"],
  "data_points": [
    {
      "run_id": "20260606_090000",
      "created_at": "2026-06-06T09:00:00Z",
      "DR": 0.85,
      "CPR": 0.78,
      "Reward": 1.20
    },
    {
      "run_id": "20260607_100000",
      "created_at": "2026-06-07T10:00:00Z",
      "DR": 0.92,
      "CPR": 0.85,
      "Reward": 1.58
    },
    {
      "run_id": "20260608_143000",
      "created_at": "2026-06-08T14:30:00Z",
      "DR": 0.94,
      "CPR": 0.88,
      "Reward": 1.72
    }
  ],
  "thresholds": {
    "DR": 0.95,
    "CPR": 0.90,
    "Reward": 0.70
  }
}
```

### 4.3 项目结构

前后端分离，独立开发、独立构建、统一部署：

```
web/
├── backend/                            # Express API 服务
│   ├── server.js                       #   Express 入口
│   ├── routes/                         #   API 路由
│   │   ├── projects.js                 #     项目管理 API
│   │   ├── runs.js                     #     运行历史 API
│   │   └── reports.js                  #     报告查看 API
│   ├── services/                       #   业务逻辑
│   │   ├── workspace-reader.js         #     Workspace 文件读取服务
│   │   ├── indexer.js                  #     索引构建与维护
│   │   └── trends.js                   #     趋势数据聚合计算
│   ├── scf_bootstrap.js                #   腾讯云函数入口适配
│   └── package.json                    #   后端依赖（express, cors 等）
│
├── frontend/                           # React SPA 前端
│   ├── src/
│   │   ├── App.tsx                     #   应用根组件 + 路由定义
│   │   ├── pages/                      #   页面组件（对应 §三 各页面）
│   │   │   ├── ProjectList.tsx         #     §3.2 项目列表页
│   │   │   ├── ProjectDetail.tsx       #     §3.3 项目详情/趋势页
│   │   │   ├── RunDetail.tsx           #     §3.4 运行详情页
│   │   │   └── TaskDetail.tsx          #     §3.5/3.6 任务详情页（含目录模式）
│   │   ├── components/                #   通用组件
│   │   │   ├── ProjectCard.tsx         #     项目卡片
│   │   │   ├── StatCard.tsx            #     指标卡片（DR/CPR/Reward）
│   │   │   ├── TrendChart.tsx          #     ECharts 趋势折线图
│   │   │   ├── RunHistoryTable.tsx     #     运行历史列表
│   │   │   ├── DirectoryTree.tsx       #     目录树可视化（目录模式）
│   │   │   └── ModuleScoreTable.tsx    #     模块级得分表（目录模式）
│   │   ├── api/                        #   API 客户端封装
│   │   │   └── client.ts              #     Axios 实例 + API 函数
│   │   └── types/                      #   TypeScript 类型定义
│   │       └── index.ts               #     §五 数据模型的 TS 类型
│   ├── public/
│   │   └── index.html
│   ├── vite.config.ts                  #   Vite 构建配置
│   ├── tsconfig.json                   #   TypeScript 配置
│   └── package.json                    #   前端依赖（react, antd, echarts, axios）
│
└── README.md                           # 开发指南（启动/构建/部署）
```

**前后端协作**：

```
frontend (Vite dev :5173) ───proxy /api──→ backend (Express :3000) ──→ workspace/
                                           │
frontend build → backend/public/ ──────────┘  (生产模式: Express 同时托管静态资源)
```

---

## 五、数据模型

### 5.1 Project

```typescript
interface Project {
  id: string;                    // 项目标识
  name: string;                  // 项目名称
  description: string;           // 项目描述
  default_rule_set: string;      // 默认规则集
  default_task_set: string;      // 默认任务集
  created_at: string;            // 创建时间 ISO 8601
  latest_run_id: string | null;  // 最新运行 ID
  run_count: number;             // 运行次数
}
```

### 5.2 RunSummary

```typescript
interface RunSummary {
  run_id: string;                // 运行 ID
  project_id: string;            // 所属项目
  created_at: string;            // 运行时间
  total_samples: number;         // 样本总数
  dr: number;                    // 交付率
  cpr: number;                   // 常识通过率
  avg_reward: number;            // 平均 Reward
  cond_r: number;                // 条件奖励
  rule_set_version: string;      // 规则集版本
  sut_version: string | null;    // SUT 版本
}
```

### 5.3 TrendDataPoint

```typescript
interface TrendDataPoint {
  run_id: string;
  created_at: string;
  DR: number;
  CPR: number;
  Reward: number;
}
```

---

## 六、数据索引与存储

### 6.1 索引文件

索引文件存储在 `workspace/index/` 目录下，由后端 indexer 服务维护：

| 文件 | 内容 | 更新时机 |
|------|------|----------|
| `projects.json` | 项目注册列表 | `project.yaml` 变更时 / 首次运行时 |
| `runs_index.json` | 扁平化运行摘要 | 每次 eval 运行完成 / 手动 `agent-eval index` |

### 6.2 索引构建流程

```
agent-eval eval 完成
       ↓
读取 reports/summary.json
       ↓
提取 DR/CPR/Reward 等指标
       ↓
关联 project_id（来自 --project 参数或默认 "default"）
       ↓
追加到 runs_index.json
       ↓
更新 projects.json 的 latest_run_id 和 run_count
```

### 6.3 全量重建

当索引文件丢失或损坏时，通过 `agent-eval index` 全量重建：

1. 扫描 `workspace/runs/` 下所有运行目录
2. 读取每个运行的 `reports/summary.json` 和 `run_manifest.json`
3. 读取 `assets/projects/` 下所有 `project.yaml` 构建项目列表
4. 将运行摘要与项目关联（通过 run_manifest 中的 project_id）
5. 写入 `projects.json` 和 `runs_index.json`

---

## 七、CLI 集成

### 7.1 新增 CLI 命令

```bash
# 启动 Web Portal
agent-eval serve [--port 3000] [--workspace ./workspace]

# 重建 Workspace 索引
agent-eval index [--workspace ./workspace]
```

### 7.2 CLI 与 Web Portal 的协作

```
CLI（Python）                    Web Portal（Node.js）
┌───────────────┐                ┌──────────────────┐
│ agent-eval    │                │ Express Server    │
│ eval / run    │                │                   │
│               │  写入 JSON     │  读取 JSON        │
│ workspace/    │───────────────→│ workspace/        │
│ runs/         │                │ index/            │
│ index/        │                │                   │
└───────────────┘                └──────────────────┘
```

- Python CLI 负责评估执行与索引更新
- Node.js Express 负责读取 JSON 文件并提供 API
- 前端 React 通过 API 获取数据渲染页面
- 两者通过 workspace 文件系统解耦

---

## 八、腾讯云函数部署方案

### 8.1 架构

```
┌──────────────────────────────────────────┐
│            腾讯云 API 网关                │
│         (自定义域名 + HTTPS)              │
└────────────────┬─────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│         腾讯云函数 (SCF)                  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Express 应用                      │  │
│  │  ├─ /api/*  → 后端 API 路由        │  │
│  │  └─ /*     → React 静态资源        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  数据源：COS 挂载 / 本地存储              │
└──────────────────────────────────────────┘
```

### 8.2 部署步骤

1. **构建前端**：`cd web/frontend && npm run build`，产物输出到 `web/frontend/dist/`
2. **复制前端产物**：将 `web/frontend/dist/` 复制到 `web/backend/public/`
3. **打包函数**：将 `web/backend/` 目录打包为 ZIP
4. **创建云函数**：选择 Node.js 运行时，上传 ZIP
5. **配置 API 网关**：绑定自定义域名，配置路由转发
6. **数据同步**：将本地 `workspace/` 上传到 COS，或配置 NAS 挂载

### 8.3 云函数入口适配

```javascript
// web/backend/scf_bootstrap.js
const express = require('express');
const path = require('path');
const app = express();

// 静态资源
app.use(express.static(path.join(__dirname, 'public')));

// API 路由
const projectsRouter = require('./routes/projects');
const runsRouter = require('./routes/runs');
const reportsRouter = require('./routes/reports');

app.use('/api/projects', projectsRouter);
app.use('/api/runs', runsRouter);
app.use('/api/reports', reportsRouter);

// SPA 回退
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// SCF 入口
const serverless = require('serverless-http');
module.exports.main_handler = serverless(app);
```

### 8.4 数据持久化策略

| 方案 | 适用场景 | 说明 |
|------|----------|------|
| **COS 挂载** | 推荐方案 | 将 workspace 目录挂载为 COS 存储桶，评估结果自动同步 |
| **NAS 挂载** | 高性能场景 | 使用腾讯云 NAS 文件存储，低延迟读写 |
| **API 回写** | 简化方案 | 云函数直接通过 API 调用 Python CLI 写入结果 |

---

## 九、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-08 | 初始版本：React + Express 技术选型、页面设计、API 定义、数据模型、腾讯云函数部署方案 |
| v1.1 | 2026-06-08 | 新增 §三.6 目录模式任务详情（目录树可视化、模块级状态表、结构检查明细）；API 新增 manifest 端点；页面路由表增加目录模式说明 |
| v1.2 | 2026-06-08 | 前后端分离重构：web/ 拆分为 web/backend/（Express API）+ web/frontend/（React SPA），独立 package.json；更新项目结构、部署步骤、云函数入口路径 |
