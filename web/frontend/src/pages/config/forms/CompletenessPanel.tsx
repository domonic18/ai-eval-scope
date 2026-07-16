/**
 * 配置完整度面板（对齐原型 rule-set-editor.html 的「配置完整度」）。
 * 纯前端从规则集数据 + 场景指标/策略派生清单与百分比，无需后端。
 */
import type { RuleSetData } from "./RuleSetForm"

interface CompletenessItem {
  ok: boolean
  label: string
  fix?: string
}

export function CompletenessPanel({
  data,
  metricCount,
  hasPolicy,
}: {
  data: RuleSetData
  metricCount: number
  hasPolicy: boolean
}) {
  const { rules, cascade, version, scenario, description } = data
  const items: CompletenessItem[] = []

  items.push({ ok: !!(version && scenario && description), label: "清单信息（版本/场景/描述）" })
  items.push({ ok: rules.length > 0, label: `规则集（${rules.length} 条）` })

  const llmUnbound = rules.filter(
    (r) => (r.method === "llm" || r.method === "llm_vision") && !r.prompt_id,
  ).length
  items.push({
    ok: llmUnbound === 0,
    label: llmUnbound === 0 ? "LLM 规则已绑定提示词" : `${llmUnbound} 条 LLM 规则未绑定提示词`,
    fix: llmUnbound > 0 ? "修复" : undefined,
  })

  const rsCount = rules.filter((r) => r.method === "rule_set").length
  items.push({
    ok: true,
    label:
      rsCount === 0
        ? "无规则集评估"
        : `规则集评估 ${rsCount} 条（默认使用全部参考数据集/知识库）`,
  })

  items.push({ ok: cascade.length > 0, label: "级联阶段已配置" })

  const orphan = rules.filter((r) => r.stage && !cascade.some((c) => c.stage === r.stage)).length
  items.push({
    ok: orphan === 0,
    label: orphan === 0 ? "规则阶段引用一致" : `${orphan} 条规则阶段引用不存在`,
  })

  items.push({ ok: metricCount > 0, label: `指标定义（${metricCount} 项）` })
  items.push({ ok: hasPolicy, label: "聚合策略" })

  const passed = items.filter((i) => i.ok).length
  const pct = Math.round((passed / items.length) * 100)

  return (
    <div className="mt-4 rounded-md border border-border p-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        配置完整度
      </div>
      <div className="space-y-0.5">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-2 py-1 text-xs">
            <span>{it.ok ? "✅" : "⚠️"}</span>
            <span className={it.ok ? "text-foreground/80" : "text-warning"}>{it.label}</span>
            {it.fix && (
              <a
                href="#"
                onClick={(e) => e.preventDefault()}
                className="ml-auto text-[11px] text-primary hover:underline"
              >
                {it.fix}
              </a>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 border-t border-border pt-2 text-[11px] text-muted-foreground">
        整体完整度:{" "}
        <span className={pct === 100 ? "font-semibold text-success" : "font-semibold text-warning"}>
          {pct}%
        </span>
      </div>
    </div>
  )
}
