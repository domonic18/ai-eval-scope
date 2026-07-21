/**
 * YAML / 表单模式切换 Hook（消除 MetricDefsEditor/AggregationPolicyEditor 的重复逻辑）。
 */
import { useState, useCallback } from "react"
import * as yaml from "js-yaml"

export function useYamlToggle<T extends Record<string, unknown>>(
  initial: T,
  onChange: (data: T) => void,
) {
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [yamlText, setYamlText] = useState(() => yaml.dump(initial, { sortKeys: false }))

  const syncYaml = useCallback(
    (data: T) => setYamlText(yaml.dump(data, { sortKeys: false })),
    [],
  )

  const onYamlChange = useCallback(
    (text: string) => {
      setYamlText(text)
      try {
        const parsed = yaml.load(text)
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          onChange(parsed as T)
        }
      } catch {
        /* YAML 语法错误时保留编辑 */
      }
    },
    [onChange],
  )

  const switchMode = useCallback(
    (m: "form" | "yaml") => {
      if (m === "yaml") setYamlText(yaml.dump(initial, { sortKeys: false }))
      setMode(m)
    },
    [initial],
  )

  return { mode, yamlText, setYamlText, syncYaml, onYamlChange, switchMode }
}
