/**
 * 产品落地页（公开 /）— 对应原型 docs/design/index.html。
 * 已登录访问 / 由 RootRedirect 直接跳 /dashboard，此页仅未登录访客可见。
 */
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/shadcn/button"
import { Card, CardContent } from "@/components/shadcn/card"
import { loadSession } from "../store/auth"
import { APP_VERSION } from "../version"
import { ArrowRight, Columns2, KeyRound, LineChart, ShieldCheck } from "lucide-react"

const FEATURES = [
  {
    icon: LineChart,
    color: "var(--primary)",
    title: "四维核心指标",
    desc: "DR / CPR / Reward / CondR 自动聚合，每项带阈值对照与环比趋势，运行健康度一眼可判。",
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
    title: "HMAC 安全摄取",
    desc: "项目级 API Key + HMAC 签名，评估器一行配置即可推送，密钥仅创建时明文展示一次。",
  },
]

const FLOW = [
  {
    n: "01 / 接入",
    title: "新建项目并创建 Key",
    desc: "在项目设置中新建 API Key，复制 public_key / secret_key 到评估器环境。",
    code: "eval-<48hex>（单一 Bearer Key）",
  },
  {
    n: "02 / 运行",
    title: "评估器推送结果",
    desc: "经 HMAC 签名将运行 / 样本 / 约束 / 制品摄取入库，无需改动评估流程。",
    code: "POST /v1/jobs",
  },
  {
    n: "03 / 洞察",
    title: "钻取定位问题",
    desc: "看板 → 趋势 → 失败分布 → 样本原文，逐级下钻定位每一次回归的根因。",
    code: "/run/:id",
  },
]

const PREVIEW_METRICS = [
  { label: "DR", value: "0.962", color: "var(--success)", pct: 96, badge: "达标" },
  { label: "CPR", value: "0.914", color: "var(--chart-2)", pct: 91, badge: "达标" },
  { label: "Reward", value: "0.781", color: "var(--warning)", pct: 78, badge: "偏低" },
  { label: "CondR", value: "0.842", color: "var(--primary)", pct: 84, badge: "" },
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
          <div className="mb-12 text-center">
            <h2 className="mb-3 text-3xl font-bold tracking-tight">产品预览</h2>
            <p className="text-sm text-muted-foreground">仪器级暗色界面，数据优先</p>
          </div>
          <div className="overflow-hidden rounded-xl border shadow-2xl">
            <div className="flex h-10 items-center gap-2 border-b bg-card px-4">
              <span className="size-2.5 rounded-full bg-[var(--danger)]" />
              <span className="size-2.5 rounded-full bg-[var(--warning)]" />
              <span className="size-2.5 rounded-full bg-[var(--success)]" />
              <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                运行 #run_2f8a · 课件生成评估 — EvalScope
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 bg-background p-5 md:grid-cols-4">
              {PREVIEW_METRICS.map((m) => (
                <div key={m.label} className="rounded-lg border bg-card p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">{m.label}</span>
                    {m.badge && <span className="text-[10px] text-muted-foreground">{m.badge}</span>}
                  </div>
                  <div className="font-mono text-xl font-bold" style={{ color: m.color }}>
                    {m.value}
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${m.pct}%`, background: m.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
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
