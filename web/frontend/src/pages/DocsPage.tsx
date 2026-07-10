/**
 * 第三方接入 API 文档页（公开 /docs）。
 * 左侧 TOC（章节锚点 + 滚动高亮），正文统一由 integration.md 维护并通过 react-markdown 渲染。
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
import integrationMd from "../content/integration.md?raw"

interface Heading {
  text: string
  id: string
  level: 2 | 3
}

export default function DocsPage() {
  const loggedIn = !!loadSession()
  const [active, setActive] = useState("")

  // 从 markdown 提取 ## / ### 标题作为 TOC（与下方 h2/h3 组件的 toSlug 保持一致）
  const headings: Heading[] = useMemo(() => {
    const lines = integrationMd.match(/^#{2,3} .+$/gm) ?? []
    return lines.map((line) => {
      const m = line.match(/^(#{2,3}) (.+)$/)!
      const full = m[2]
      return {
        text: full.replace(/^\d+\.\s*/, ""),
        id: toSlug(full),
        level: m[1].length as 2 | 3,
      }
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
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
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
      <div className="relative z-10 mx-auto flex max-w-7xl gap-10 px-6 pb-24">
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
                    "-ml-px block border-l-2 py-1.5 pr-3 transition-colors",
                    h.level === 3 ? "pl-8 text-xs" : "pl-3 text-sm",
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

        <main className="min-w-0 max-w-4xl pt-10">
          {/* 正文全部由 integration.md 维护，避免页面 hardcode */}
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
