/**
 * 产品落地页（公开 /）— 对应原型 docs/design/index.html。
 * 已登录访问 / 由 RootRedirect 直接跳 /dashboard，此页仅未登录访客可见。
 */
import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/shadcn/button"
import { Card, CardContent } from "@/components/shadcn/card"
import { loadSession } from "../store/auth"
import { APP_VERSION } from "../version"
import { SemPill, TierChip } from "../components/shared"
import { ArrowRight, Columns2, KeyRound, LineChart, ShieldCheck } from "lucide-react"

const FEATURES = [
  {
    icon: LineChart,
    color: "var(--primary)",
    title: "五维核心指标",
    desc: "DR / CPR / Soft / Pref / Reward 自动聚合，每项带阈值对照与环比趋势，运行健康度一眼可判。",
  },
  {
    icon: ShieldCheck,
    color: "var(--chart-2)",
    title: "约束级结论可追溯",
    desc: "format / commonsense / quality 三阶段、多项评估器逐条结论，附 LLM Judge 出处与原始证据。",
  },
  {
    icon: Columns2,
    color: "var(--info)",
    title: "结论 ↔ 原文 并置",
    desc: "样本详情左右分栏，左看约束结论、右看被评估文档与渲染截图，无需来回跳转即可核验。",
  },
  {
    icon: KeyRound,
    color: "var(--warning)",
    title: "API Key 安全接入",
    desc: "项目级单一 API Key（eval-…），HTTPS 下 Bearer 直传、免签名，密钥仅创建时明文展示一次。",
  },
]

const FLOW = [
  {
    n: "01 / 接入",
    title: "新建项目并创建 Key",
    desc: "在项目设置中新建 API Key，复制单一 Bearer Key（eval-…）备用。",
    code: "eval-<48hex>（单一 Bearer Key）",
  },
  {
    n: "02 / 运行",
    title: "提交内容评估",
    desc: "携带 Bearer Key 向 /v1/jobs 提交文件或文本，立即拿到 job_id，异步评估后结果自动入库。",
    code: "POST /v1/jobs",
  },
  {
    n: "03 / 洞察",
    title: "钻取定位问题",
    desc: "看板 → 趋势 → 失败分布 → 样本原文，逐级下钻定位每一次回归的根因。",
    code: "/run/:id",
  },
]

/** 预览用五维指标 —— 对齐真实概览卡（ProjectDetail）：阈值着色（达标绿 / 未达黄）+ 环比 delta。 */
const PREVIEW_METRICS = [
  { key: "DR", label: "交付率(DR)", value: "0.962", color: "var(--success)", delta: "+1.2%", deltaColor: "var(--success)" },
  { key: "CPR", label: "约束通过率(CPR)", value: "0.914", color: "var(--success)", delta: "+0.6%", deltaColor: "var(--success)" },
  { key: "Soft", label: "内容质量分(Soft)", value: "0.780", color: "var(--success)", delta: "+1.8%", deltaColor: "var(--success)" },
  { key: "Pref", label: "用户偏好分(Pref)", value: "0.720", color: "var(--success)", delta: "+0.4%", deltaColor: "var(--success)" },
  { key: "Reward", label: "综合评分(Reward)", value: "0.781", color: "var(--warning)", delta: "-2.1%", deltaColor: "var(--danger)" },
]

/** 预览用样本详情约束 —— 来自真实运行案例（contents）。 */
const PREVIEW_CONSTRAINTS: {
  stage: string
  chips: ("hard" | "soft" | "pref")[]
  scoreText: string
  tone: string
  items: {
    pass: boolean
    name: string
    cid: string
    score: string
    reason?: string
    meta?: { method?: string; judge?: string; durationMs?: number }
  }[]
}[] = [
  {
    stage: "格式 Format",
    chips: ["hard"],
    scoreText: "S_format = 1.00",
    tone: "var(--success)",
    items: [
      { pass: true, name: "HTML 有效性检查", cid: "format.html_validity", score: "1.00" },
      { pass: true, name: "文件格式检查", cid: "format.response_format", score: "1.00" },
    ],
  },
  {
    stage: "常识 Commonsense",
    chips: ["hard"],
    scoreText: "S_common = 0.00",
    tone: "var(--danger)",
    items: [
      { pass: true, name: "逻辑一致性检查", cid: "commonsense.logical_consistency", score: "1.00" },
      {
        pass: false,
        name: "知识准确性检查",
        cid: "commonsense.info_accuracy",
        score: "0.00",
        reason: "知识准确性（LLM + 规则）：factual_correctness=10.0, statement_accuracy=10.0；发现错误（经 LLM 二次确认）：原文中提到的计算是 12×2 + 7 + 3 + 5 + 18 = 100，但实际上 12×2 等于 24，24 + 7 + 3 + 5 + 18 等于 57，因此原文中的等式是错误的。",
        meta: { method: "LLM_JUDGE", judge: "kimi_judge / moonshot-v1-128k", durationMs: 10052 },
      },
      { pass: true, name: "时序正确性检查", cid: "commonsense.chronological_order", score: "1.00" },
    ],
  },
  {
    stage: "质量 Quality",
    chips: ["soft", "pref"],
    scoreText: "S_soft 0.80 · S_pref 0.88",
    tone: "var(--warning)",
    items: [
      { pass: true, name: "需求满足度", cid: "pref.request_fulfillment", score: "0.90" },
      { pass: true, name: "风格偏好", cid: "pref.style_preference", score: "0.90" },
      { pass: true, name: "深度偏好", cid: "pref.depth_preference", score: "0.83" },
      { pass: true, name: "教学逻辑", cid: "soft.teaching_logic", score: "0.87" },
      { pass: true, name: "内容多样性", cid: "soft.content_diversity", score: "0.73" },
    ],
  },
]

const STRIP = [
  { v: "0.962", c: "var(--success)", l: "交付率 DR" },
  { v: "0.914", c: "var(--chart-2)", l: "常识通过率 CPR" },
  { v: "0.781", c: "var(--foreground)", l: "平均 Reward" },
  { v: "14", c: "var(--foreground)", l: "内置评估器" },
]

export default function Landing() {
  const nav = useNavigate()
  const goConsole = () => nav(loadSession() ? "/dashboard" : "/login", { replace: true })
  const [previewTab, setPreviewTab] = useState<"overview" | "detail">("overview")

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <div className="scanlines" aria-hidden />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          background: "radial-gradient(ellipse 80% 50% at 50% 0%, var(--primary), transparent)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          background: "radial-gradient(ellipse 60% 40% at 100% 100%, var(--chart-2), transparent)",
        }}
      />

      {/* Nav */}
      <header className="relative z-10 border-b backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Link to="/" className="inline-flex items-center gap-2.5 text-[16px] font-semibold">
            <span className="flex size-7 items-center justify-center">
              <img src="/logo.svg" alt="EvalScope" className="h-full w-full" />
            </span>
            <span>
              Eval<b>Scope</b>
            </span>
            <span className="ml-1 rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-tight text-muted-foreground">
              v{APP_VERSION}
            </span>
          </Link>
          <nav className="flex items-center gap-6">
            <Link to="/docs" className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
              接入文档
            </Link>
            <Button variant="outline" size="sm" asChild>
              <Link to="/login">登录</Link>
            </Button>
          </nav>
        </div>
      </header>

      <div className="relative z-10 mx-auto max-w-5xl px-6">
        {/* Hero */}
        <section className="pb-16 pt-24 text-center">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-medium text-primary">
            <span className="size-1.5 rounded-full bg-[var(--chart-2)] shadow-[0_0_8px_var(--chart-2)]" />
            多租户评估可观测平台 · v1.0
          </div>
          <h1 className="mx-auto mb-5 max-w-2xl bg-gradient-to-b from-foreground to-muted-foreground bg-clip-text text-5xl font-extrabold leading-[1.1] tracking-tight text-transparent">
            量化每一次
            <br />
            Agent 评估的信号
          </h1>
          <p className="mx-auto mb-9 max-w-xl text-base leading-7 text-muted-foreground">
            从评估器实时摄取运行数据，按 组织 / 项目 / 运行 / 样本 / 约束 五级钻取，把交付率、约束结论与原始证据一站式对照、可追溯。
          </p>
          <div className="flex justify-center gap-3">
            <Button size="lg" onClick={goConsole}>
              进入控制台 <ArrowRight className="size-4" />
            </Button>
            <Button size="lg" variant="outline" asChild>
              <a href="#preview">查看演示</a>
            </Button>
          </div>

          <div className="mx-auto mt-16 grid max-w-3xl grid-cols-2 overflow-hidden rounded-xl border md:grid-cols-4">
            {STRIP.map((m) => (
              <div
                key={m.l}
                className="border-b border-r border-border p-6 text-center last:border-r-0 md:border-b-0"
              >
                <div className="font-mono text-2xl font-bold" style={{ color: m.c }}>
                  {m.v}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{m.l}</div>
              </div>
            ))}
          </div>
        </section>

        {/* 能力特性 */}
        <section id="features" className="scroll-mt-20 pt-20">
          <div className="mb-12 text-center">
            <h2 className="mb-3 text-3xl font-bold tracking-tight">为评估而生</h2>
            <p className="text-sm text-muted-foreground">
              不是又一个日志工具，而是面向 Agent 评估语义构建的可观测层
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {FEATURES.map((f) => (
              <Card key={f.title} className="transition-all hover:-translate-y-0.5 hover:border-primary/40">
                <CardContent className="p-7">
                  <div
                    className="mb-4 flex size-11 items-center justify-center rounded-lg"
                    style={{ background: `${f.color}1a` }}
                  >
                    <f.icon className="size-5" style={{ color: f.color }} />
                  </div>
                  <h3 className="mb-2 text-base font-semibold">{f.title}</h3>
                  <p className="text-sm leading-6 text-muted-foreground">{f.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* 三步接入 */}
        <section id="flow" className="scroll-mt-20 pt-20">
          <div className="mb-12 text-center">
            <h2 className="mb-3 text-3xl font-bold tracking-tight">三步接入</h2>
            <p className="text-sm text-muted-foreground">从创建密钥到看见首个运行，几分钟完成</p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {FLOW.map((s) => (
              <Card key={s.n}>
                <CardContent className="p-7">
                  <div className="mb-4 font-mono text-xs font-semibold text-primary">{s.n}</div>
                  <h3 className="mb-2 text-base font-semibold">{s.title}</h3>
                  <p className="mb-3 text-sm leading-6 text-muted-foreground">{s.desc}</p>
                  <code className="font-mono text-xs text-[var(--chart-2)]">{s.code}</code>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* 产品预览 */}
        <section id="preview" className="scroll-mt-20 pt-20">
          <div className="mb-8 text-center">
            <h2 className="mb-3 text-3xl font-bold tracking-tight">产品预览</h2>
            <p className="text-sm text-muted-foreground">仪器级暗色界面，数据优先</p>
            <div className="mt-6 inline-flex rounded-md border bg-secondary p-0.5 text-sm">
              <button
                onClick={() => setPreviewTab("overview")}
                className={`rounded px-4 py-1.5 font-medium transition-colors ${
                  previewTab === "overview"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                概览
              </button>
              <button
                onClick={() => setPreviewTab("detail")}
                className={`rounded px-4 py-1.5 font-medium transition-colors ${
                  previewTab === "detail"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                样本详情
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border shadow-2xl">
            {/* 浏览器/应用窗口栏 */}
            <div className="flex h-10 items-center gap-2 border-b bg-card px-4">
              <span className="size-2.5 rounded-full bg-[var(--danger)]" />
              <span className="size-2.5 rounded-full bg-[var(--warning)]" />
              <span className="size-2.5 rounded-full bg-[var(--success)]" />
              <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                {previewTab === "overview"
                  ? "课件生成评估 · 概览 — EvalScope"
                  : "样本 contents — EvalScope"}
              </span>
            </div>

            {previewTab === "overview" ? (
              <div className="space-y-3 bg-background p-5">
                {/* 五维指标卡：对齐真实概览（阈值着色 + 环比） */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                  {PREVIEW_METRICS.map((m) => (
                    <div key={m.key} className="rounded-lg border bg-card p-4">
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {m.label}
                      </div>
                      <div
                        className="mt-2 font-mono text-2xl font-bold tabular-nums"
                        style={{ color: m.color }}
                      >
                        {m.value}
                      </div>
                      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                        <span style={{ color: m.deltaColor }}>
                          {m.delta.startsWith("+") ? "▲" : "▼"} {m.delta}
                        </span>
                        <span>较上次</span>
                      </div>
                    </div>
                  ))}
                </div>
                {/* 指标趋势 */}
                <div className="rounded-lg border bg-card">
                  <div className="flex items-center justify-between border-b px-4 py-2.5">
                    <span className="text-sm font-semibold">指标趋势</span>
                    <span className="text-xs text-muted-foreground">近 8 周</span>
                  </div>
                  <div className="p-4">
                    <svg viewBox="0 0 320 120" className="h-28 w-full" preserveAspectRatio="none">
                      <line x1="0" y1="30" x2="320" y2="30" stroke="var(--border)" strokeDasharray="3 4" />
                      <line x1="0" y1="60" x2="320" y2="60" stroke="var(--border)" strokeDasharray="3 4" />
                      <line x1="0" y1="90" x2="320" y2="90" stroke="var(--border)" strokeDasharray="3 4" />
                      <polyline
                        points="0,28 46,24 91,26 137,20 182,22 228,16 274,18 320,12"
                        fill="none"
                        stroke="var(--success)"
                        strokeWidth="2"
                      />
                      <polyline
                        points="0,52 46,55 91,48 137,50 182,44 228,46 274,40 320,38"
                        fill="none"
                        stroke="var(--chart-2)"
                        strokeWidth="2"
                      />
                      <polyline
                        points="0,80 46,76 91,82 137,74 182,84 228,78 274,86 320,82"
                        fill="none"
                        stroke="var(--primary)"
                        strokeWidth="2"
                      />
                    </svg>
                    <div className="mt-2 flex justify-center gap-5 text-[11px] text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <span className="inline-block h-0.5 w-3" style={{ background: "var(--success)" }} />
                        DR
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="inline-block h-0.5 w-3" style={{ background: "var(--chart-2)" }} />
                        CPR
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="inline-block h-0.5 w-3" style={{ background: "var(--primary)" }} />
                        Reward
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 bg-background lg:grid-cols-2">
                {/* 左：约束结论 */}
                <div className="border-b p-5 lg:border-b-0 lg:border-r">
                  <div className="mb-4 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">contents</span>
                    <SemPill tone="danger">fail</SemPill>
                    <SemPill tone="neutral">
                      综合评分(Reward) <b className="ml-1 font-mono text-[var(--danger)]">0.669</b>
                    </SemPill>
                    <SemPill tone="danger" dot>
                      1 项约束失败
                    </SemPill>
                  </div>
                  {PREVIEW_CONSTRAINTS.map((s) => (
                    <div key={s.stage} className="mb-5">
                      <div className="mb-2 flex items-center gap-2">
                        <span className="block h-3 w-1 rounded-full" style={{ background: s.tone }} />
                        <span className="text-sm font-semibold">{s.stage}</span>
                        <div className="flex items-center gap-1">
                          {s.chips.map((c) => (
                            <TierChip key={c} tier={c}>
                              {c === "hard" ? "HARD_GATE" : c === "soft" ? "SOFT" : "PREFERENCE"}
                            </TierChip>
                          ))}
                        </div>
                        <span className="ml-auto font-mono text-xs text-muted-foreground">{s.scoreText}</span>
                      </div>
                      <div className="space-y-1.5">
                        {s.items.map((it) => (
                          <div
                            key={it.cid}
                            className={`rounded-md border px-3 py-2 ${
                              it.pass ? "border-border" : "border-[var(--danger)]/40 bg-[var(--danger-soft)]"
                            }`}
                          >
                            <div className="flex items-center gap-2 text-sm">
                              <SemPill tone={it.pass ? "success" : "danger"}>
                                {it.pass ? "PASS" : "FAIL"}
                              </SemPill>
                              <span className="min-w-0 flex-1 truncate">
                                {it.name}
                                <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                                  {it.cid}
                                </span>
                              </span>
                              <span
                                className="font-mono text-xs tabular-nums"
                                style={{ color: it.pass ? "var(--success)" : "var(--danger)" }}
                              >
                                {it.score}
                              </span>
                            </div>
                            {!it.pass && it.reason && (
                              <div className="mt-2 space-y-2 border-l-2 border-[var(--danger)] pl-3 text-xs leading-5 text-muted-foreground">
                                <div>{it.reason}</div>
                                {it.meta && (
                                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                    <span>
                                      <b className="text-foreground">方法</b> {it.meta.method}
                                    </span>
                                    <span>
                                      <b className="text-foreground">Judge</b> {it.meta.judge}
                                    </span>
                                    <span>
                                      <b className="text-foreground">耗时</b> {it.meta.durationMs}ms
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                {/* 右：原文预览（真实案例 contents） */}
                <div className="bg-inset p-5">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex rounded-md border bg-secondary p-0.5">
                      <span className="rounded bg-card px-3 py-1 text-xs font-medium text-foreground">原始文档</span>
                      <span className="px-3 py-1 text-xs text-muted-foreground">执行 Trace</span>
                    </div>
                    <span className="rounded border border-border bg-secondary px-2 py-1 text-xs text-muted-foreground">
                      大单元学习总纲 / M2 学习单
                    </span>
                  </div>
                  <div
                    className="mx-auto max-w-lg rounded p-6 text-[#1a1a1a] shadow-lg"
                    style={{ background: "#fff", fontFamily: "var(--sans)" }}
                  >
                    <div className="mb-4 text-sm font-semibold text-sky-700">情境挑战</div>
                    <p className="mb-4 text-sm leading-7">
                      妈妈的购物卡原有200元，先充值了50元，又买了水果用去75元，现在卡里还剩多少元？
                    </p>
                    <div className="mb-4 rounded-lg bg-[#f0f9ff] p-4">
                      <div className="mb-2 text-xs font-semibold text-sky-700">解题思路</div>
                      <p className="text-sm leading-6">充值后：200 + 50 = 250 元</p>
                      <p className="text-sm leading-6">消费后：250 - 75 = 175 元</p>
                    </div>
                    <div className="mb-4 rounded-lg bg-[#fffbeb] p-4">
                      <div className="mb-2 text-xs font-semibold text-amber-700">思维进阶</div>
                      <p className="text-sm leading-6">
                        理解“充值”是加法操作，“消费”是减法操作，建立收支平衡的概念。
                      </p>
                    </div>

                    <div className="mb-3 flex items-center gap-2">
                      <span className="flex size-6 items-center justify-center rounded-full bg-sky-600 text-xs font-bold text-white">
                        七
                      </span>
                      <span className="text-base font-bold">设计购物方案</span>
                    </div>
                    <div className="mb-4 text-sm leading-7">
                      你有100元，要买以下物品中的几样，使得刚好花完或者剩余最少：铅笔5元/支，橡皮3元/个，尺子7元/把，笔记本12元/本，彩笔18元/盒。你会怎么买？
                    </div>
                    <div className="mb-4 rounded-lg bg-[#f0f9ff] p-4">
                      <div className="mb-2 text-xs font-semibold text-sky-700">方案示例</div>
                      <p className="text-sm leading-6">方案一（刚好花完）：18 + 12 + 7 + 3 + 5 = 45 元 → 剩余55元</p>
                      <p className="text-sm leading-6">方案二（剩余最少）：100 - (18 + 12 + 7 + 3 + 5) = 55 元</p>
                      <p className="text-sm leading-6">
                        最优方案：12×2 + 7 + 3 + 5 + 18 ={" "}
                        <span
                          className="rounded px-0.5 underline decoration-2 underline-offset-2"
                          style={{ background: "#ffe9e9", textDecorationColor: "var(--danger)" }}
                        >
                          100
                        </span>{" "}
                        元（刚好花完）
                      </p>
                    </div>
                    <div className="rounded-lg bg-[#fffbeb] p-4">
                      <div className="mb-2 text-xs font-semibold text-amber-700">思维进阶</div>
                      <p className="text-sm leading-6">
                        开放性问题，培养组合思维与优化意识，鼓励孩子多角度思考不同方案。
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* CTA */}
        <section className="pb-16 pt-24 text-center">
          <h2 className="mb-3 text-3xl font-bold tracking-tight">开始观测你的 Agent 评估</h2>
          <p className="mb-8 text-sm text-muted-foreground">
            连接评估器，把每一次运行变成可量化、可追溯的信号
          </p>
          <Button size="lg" asChild>
            <Link to="/register">免费创建组织</Link>
          </Button>
        </section>

        <footer className="border-t py-8 text-center">
          <div className="flex items-center justify-center gap-3 text-xs text-muted-foreground">
            <span>EvalScope · Agent 能力评估可观测平台</span>
            <span className="font-mono">v{APP_VERSION}</span>
          </div>
        </footer>
      </div>
    </div>
  )
}
