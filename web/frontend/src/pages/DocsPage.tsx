/**
 * 第三方接入 API 文档页（公开 /docs）。
 * 左侧 TOC（章节锚点 + 滚动高亮）+ 概述区（JSX 精美链路图）+ react-markdown 渲染 integration.md。
 */
import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import "highlight.js/styles/github-dark.css"
import { Button } from "@/components/shadcn/button"
import { cn } from "@/lib/utils"
import { loadSession } from "../store/auth"
import { APP_VERSION } from "../version"
import { ArrowRight, CornerLeftDown } from "lucide-react"
import integrationMd from "../content/integration.md?raw"

interface Heading {
  text: string
  id: string
}

export default function DocsPage() {
  const loggedIn = !!loadSession()
  const [active, setActive] = useState("")

  // 从 markdown 提取 ## 标题作为 TOC（与下方 h2 组件的 toSlug 保持一致）
  const headings: Heading[] = useMemo(() => {
    const lines = integrationMd.match(/^## .+$/gm) ?? []
    return lines.map((line) => {
      const full = line.replace(/^## /, "")
      return { text: full.replace(/^\d+\.\s*/, ""), id: toSlug(full) }
    })
  }, [])

  // 滚动时高亮当前章节
  useEffect(() => {
    const els = headings
      .map((h) => document.getElementById(h.id))
      .filter((el): el is HTMLElement => !!el)
    if (!els.length) return
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive((visible[0].target as HTMLElement).id)
      },
      { rootMargin: "-90px 0px -70% 0px", threshold: 0 },
    )
    els.forEach((el) => obs.observe(el))
    return () => obs.disconnect()
  }, [headings])

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <div className="scanlines" aria-hidden />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          background: "radial-gradient(ellipse 80% 50% at 50% 0%, var(--primary), transparent)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          background: "radial-gradient(ellipse 60% 40% at 100% 100%, var(--chart-2), transparent)",
        }}
      />

      {/* 顶部导航 */}
      <header className="relative z-10 border-b backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link to="/" className="inline-flex items-center gap-2.5 text-[15px] font-medium">
            <span className="flex size-7 items-center justify-center">
              <img src="/logo.svg" alt="EvalScope" className="h-full w-full" />
            </span>
            <span className="text-foreground">
              Eval<b>Scope</b>
            </span>
            <span className="ml-1 rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-tight text-muted-foreground">
              v{APP_VERSION}
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              返回首页
            </Link>
            <Button variant="outline" size="sm" asChild>
              <Link to={loggedIn ? "/dashboard" : "/login"}>
                {loggedIn ? "进入控制台" : "登录"}
              </Link>
            </Button>
          </div>
        </div>
      </header>

      {/* 内容 + 左侧 TOC */}
      <div className="relative z-10 mx-auto flex max-w-6xl gap-10 px-6 pb-24">
        <aside className="hidden w-52 shrink-0 md:block">
          <div className="sticky top-24">
            <div className="mb-3 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              本页内容
            </div>
            <nav className="space-y-0.5 border-l">
              {headings.map((h) => (
                <a
                  key={h.id}
                  href={`#${h.id}`}
                  className={cn(
                    "-ml-px block border-l-2 px-3 py-1.5 text-sm transition-colors",
                    active === h.id
                      ? "border-primary font-medium text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {h.text}
                </a>
              ))}
            </nav>
          </div>
        </aside>

        <main className="min-w-0 max-w-3xl pt-10">
          {/* 概述 */}
          <h1 className="mb-4 text-3xl font-bold tracking-tight">第三方接入 EvalScope 评估器</h1>
          <p className="text-sm leading-7 text-muted-foreground">
            通过 <strong className="text-foreground">eval-gateway</strong>，第三方系统（课件平台、Agent
            编排等）一行 HTTP 请求即可把待评估内容提交给 EvalScope；平台异步运行评估器，并回传
            <strong className="text-foreground"> 可量化的指标</strong> 与
            <strong className="text-foreground"> 可追溯的证据</strong>。
          </p>
          <FlowDiagram />

          {/* markdown 正文 */}
          <article>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                h1: ({ children }) => (
                  <h1 className="mb-4 text-3xl font-bold tracking-tight">{children}</h1>
                ),
                h2: ({ children }) => {
                  const id = toSlug(children)
                  return (
                    <h2
                      id={id}
                      className="mb-4 mt-12 scroll-mt-20 border-b pb-2 text-2xl font-semibold tracking-tight"
                    >
                      {children}
                    </h2>
                  )
                },
                h3: ({ children }) => {
                  const id = toSlug(children)
                  return (
                    <h3 id={id} className="mb-2 mt-7 scroll-mt-20 text-lg font-semibold">
                      {children}
                    </h3>
                  )
                },
                p: ({ children }) => (
                  <p className="my-3 text-sm leading-7 text-muted-foreground">{children}</p>
                ),
                a: ({ children, href }) => (
                  <a
                    href={href}
                    target={href?.startsWith("#") ? undefined : "_blank"}
                    rel="noreferrer"
                    className="font-medium text-primary underline-offset-4 hover:underline"
                  >
                    {children}
                  </a>
                ),
                ul: ({ children }) => (
                  <ul className="my-3 list-disc space-y-1.5 pl-6 text-sm leading-7 text-muted-foreground">
                    {children}
                  </ul>
                ),
                ol: ({ children }) => (
                  <ol className="my-3 list-decimal space-y-1.5 pl-6 text-sm leading-7 text-muted-foreground">
                    {children}
                  </ol>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="my-4 rounded-r border-l-2 border-primary/50 bg-muted/30 px-4 py-2 text-sm italic leading-7 text-muted-foreground">
                    {children}
                  </blockquote>
                ),
                hr: () => <hr className="my-8 border-border" />,
                pre: ({ children }) => (
                  <pre className="my-4 overflow-x-auto rounded-lg border bg-card p-4 text-xs leading-relaxed">
                    {children}
                  </pre>
                ),
                code: ({ className, children }) => {
                  if (/language-/.test(className || "")) {
                    return <code className={className}>{children}</code>
                  }
                  return (
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-primary">
                      {children}
                    </code>
                  )
                },
                table: ({ children }) => (
                  <div className="my-4 overflow-x-auto rounded-lg border">
                    <table className="w-full border-collapse text-sm">{children}</table>
                  </div>
                ),
                thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                th: ({ children }) => (
                  <th className="border-b border-border px-3 py-2 text-left font-medium text-foreground">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="border-b border-border/60 px-3 py-2 align-top text-muted-foreground">
                    {children}
                  </td>
                ),
              }}
            >
              {integrationMd}
            </ReactMarkdown>
          </article>
        </main>
      </div>
    </div>
  )
}

/* ── 链路图组件 ────────────────────────────────────── */
function FlowDiagram() {
  return (
    <div className="my-8 overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-col items-stretch gap-3 p-6 lg:flex-row lg:items-center">
        <FlowNode title="第三方系统" desc="提交待评估内容" tone="primary" />
        <FlowArrow label="POST /v1/jobs" />
        <FlowNode title="eval-gateway" desc="HMAC 验签 · 异步调度" tone="signal" />
        <FlowArrow label="调用" />
        <FlowNode title="评估器" desc="运行评估 · 产出指标" tone="info" />
      </div>
      <div className="flex items-start gap-2 border-t bg-background/40 px-6 py-3 text-xs leading-6 text-muted-foreground">
        <CornerLeftDown className="mt-0.5 size-3.5 shrink-0" />
        <span>
          评估完成后，结果经 Web 摄取链路回传；第三方通过{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-primary">
            GET /v1/jobs/{"{job_id}"}
          </code>{" "}
          轮询获取指标与{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-primary">web_run_url</code>。
        </span>
      </div>
    </div>
  )
}

function FlowNode({
  title,
  desc,
  tone,
}: {
  title: string
  desc: string
  tone: "primary" | "signal" | "info"
}) {
  const color =
    tone === "primary" ? "var(--primary)" : tone === "signal" ? "var(--chart-2)" : "var(--info)"
  return (
    <div className="flex-1 rounded-lg border p-4" style={{ borderColor: `${color}55` }}>
      <div className="mb-2 size-2 rounded-full" style={{ background: color }} />
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{desc}</div>
    </div>
  )
}

function FlowArrow({ label }: { label: string }) {
  return (
    <div className="flex shrink-0 items-center gap-1.5 self-center font-mono text-xs text-muted-foreground">
      <span>{label}</span>
      <ArrowRight className="size-4 rotate-90 lg:rotate-0" />
    </div>
  )
}

/* ── helpers ── */
function toSlug(children: unknown): string {
  const text = extractText(children)
  return text
    .toLowerCase()
    .replace(/[\s.。，、：:（）()/]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
}

function extractText(node: unknown): string {
  if (typeof node === "string") return node
  if (typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(extractText).join("")
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: unknown } }).props.children)
  }
  return ""
}
