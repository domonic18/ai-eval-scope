/**
 * 只读浏览器详情视图：任务集（考卷）与 SUT 接入配置（arch/13 §四）。
 * 数据来自 /scenarios/:id/{task-sets,sut-configs}/:assetId/content（sut 为子树，无真凭证）。
 */
import { useEffect, useState } from "react"
import * as yaml from "js-yaml"
import { Badge } from "../../components/shadcn/badge"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { api } from "../../api/client"
import { CodeBlock, DetailHeader, LoadingCard } from "../RuleExplorer"

type Dict = Record<string, unknown>

interface TaskItem {
  id?: string
  input?: { instruction?: string; intent?: string }
  expected?: { answer?: unknown; reference?: string; must_mention?: string[] }
  constraints?: { max_turns?: number }
}

// ── 任务集（考卷）详情 ──

export function TaskSetDetail({ scenarioId, assetId }: { scenarioId: string; assetId: string }) {
  const [content, setContent] = useState<{ name?: string; description?: string; tasks?: TaskItem[] } | null>(null)
  useEffect(() => {
    api
      .assetContent(scenarioId, "task-sets", assetId)
      .then((c) => setContent(c as unknown as { name?: string; description?: string; tasks?: TaskItem[] }))
      .catch(() => setContent(null))
  }, [scenarioId, assetId])

  if (!content) return <LoadingCard />
  const tasks = content.tasks ?? []

  return (
    <div className="space-y-4">
      <DetailHeader
        title={content.name ?? assetId}
        sub={content.description ?? ""}
        meta={[
          { label: "考卷 ID", value: assetId },
          { label: "任务数", value: String(tasks.length) },
        ]}
      />
      <div className="space-y-2">
        {tasks.map((t, i) => (
          <TaskCard key={t.id ?? i} task={t} />
        ))}
      </div>
    </div>
  )
}

function TaskCard({ task }: { task: TaskItem }) {
  const exp = task.expected ?? {}
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{task.id}</span>
          {task.input?.intent && <Badge variant="outline" className="text-[10px]">{task.input.intent}</Badge>}
          {task.constraints?.max_turns != null && (
            <Badge variant="secondary" className="text-[10px]">≤{task.constraints.max_turns} 轮</Badge>
          )}
        </div>
        <p className="text-sm">{task.input?.instruction ?? "—"}</p>
        <div className="space-y-1.5 border-t pt-2">
          <ExpectRow label="精确答案" value={exp.answer} />
          {exp.reference && (
            <div>
              <span className="text-[11px] text-muted-foreground/70">参考回答</span>
              <pre className="scroll-area mt-1 max-h-[200px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-2 font-mono text-xs text-muted-foreground">
                {exp.reference}
              </pre>
            </div>
          )}
          {!!exp.must_mention?.length && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground/70">必须覆盖</span>
              {exp.must_mention.map((m, i) => (
                <Badge key={i} variant="secondary" className="max-w-[280px] truncate text-[10px] font-normal">
                  {m}
                </Badge>
              ))}
            </div>
          )}
          {!exp.answer && !exp.reference && !exp.must_mention?.length && (
            <p className="text-xs text-muted-foreground/60">（未声明期望）</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ExpectRow({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-[11px] text-muted-foreground/70">{label}</span>
      <span className="font-mono text-emerald-400">{String(value)}</span>
    </div>
  )
}

// ── SUT 接入配置详情 ──

export function SutConfigDetail({ scenarioId, assetId }: { scenarioId: string; assetId: string }) {
  const [content, setContent] = useState<Dict | null>(null)
  useEffect(() => {
    api
      .assetContent(scenarioId, "sut-configs", assetId)
      .then((c) => setContent(c as Dict))
      .catch(() => setContent(null))
  }, [scenarioId, assetId])

  if (!content) return <LoadingCard />
  const auth = (content.auth as Dict | undefined) ?? {}
  const login = (auth.login as Dict | undefined) ?? {}
  const extract = (auth.extract as Dict | undefined) ?? {}
  const configurable = (content.configurable as Record<string, unknown> | undefined) ?? {}

  return (
    <div className="space-y-4">
      <DetailHeader
        title={String(content.name ?? assetId)}
        sub="被测系统接入（端点与协议；凭证不入包）"
        meta={[
          { label: "channel", value: String(content.channel ?? "—") },
          { label: "protocol", value: String(content.protocol_flavor ?? "—") },
          { label: "timeout", value: `${String(content.timeout ?? "—")}s` },
        ]}
      />

      <Card>
        <CardHeader><CardTitle className="text-sm">接入端点</CardTitle></CardHeader>
        <CardContent className="space-y-1.5">
          <KV k="base_url" v={content.base_url} mono />
          <KV k="exec_mode" v={content.exec_mode} />
          {Object.keys(configurable).length > 0 &&
            Object.entries(configurable).map(([k, v]) => <KV key={k} k={`configurable.${k}`} v={v} mono />)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">鉴权（auth）</CardTitle></CardHeader>
        <CardContent className="space-y-1.5">
          <KV k="type" v={auth.type} />
          <KV k="credential_ref" v={auth.credential_ref} mono hint="真凭证存于平台 Secrets，此处仅为引用名" />
          {!!login.path && (
            <KV k="login" v={`${String(login.method ?? "POST")} ${String(login.path ?? "")}`} mono />
          )}
          {!!extract.token_path && (
            <KV k="extract" v={`${String(extract.token_path)} (${String(extract.token_type ?? "Bearer")})`} mono />
          )}
        </CardContent>
      </Card>

      <CodeBlock label="配置原文（sut: 子树）" content={yaml.dump(content, { sortKeys: false, lineWidth: 100 })} />
    </div>
  )
}

function KV({ k, v, mono, hint }: { k: string; v: unknown; mono?: boolean; hint?: string }) {
  if (v == null || v === "") return null
  return (
    <div className="flex items-start gap-3 border-t py-1.5 text-sm first:border-t-0">
      <span className="w-44 shrink-0 font-mono text-xs text-muted-foreground">{k}</span>
      <span className={`min-w-0 flex-1 break-all ${mono ? "font-mono text-xs" : ""}`}>{String(v)}</span>
      {hint && <span className="shrink-0 text-[10px] text-muted-foreground/60">{hint}</span>}
    </div>
  )
}
