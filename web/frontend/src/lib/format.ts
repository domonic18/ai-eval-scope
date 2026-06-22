/** 纯展示格式化工具（无 React）。 */

/** 三位小数；null/undefined → "—"。 */
export function fmt3(n: number | null | undefined): string {
  return n == null ? "—" : n.toFixed(3)
}

/** 百分比（值 0~1 → "96.2%"）；null → "—"。 */
export function pct(n: number | null | undefined): string {
  return n == null ? "—" : (n * 100).toFixed(1) + "%"
}

/** 整数千分位。 */
export function num(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString("en-US")
}

/** 毫秒 → "3.2s" / "3,184 ms"。 */
export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—"
  return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : Math.round(ms) + " ms"
}

/** 毫秒原始展示 → "3,184 ms"。 */
export function fmtMsRaw(ms: number | null | undefined): string {
  return ms == null ? "—" : Math.round(ms).toLocaleString("en-US") + " ms"
}

/** 相对时间（中文）："刚刚 / 12 分钟前 / 3 小时前 / 昨天 21:04 / 2 天前 / 2026-06-18"。 */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—"
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return "—"
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day === 1) return `昨天 ${hm(t)}`
  if (day < 7) return `${day} 天前`
  return dateStr(t)
}

/** "2026-06-18 09:46"。 */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return "—"
  return `${dateStr(t)} ${hm(t)}`
}

function dateStr(t: number): string {
  const d = new Date(t)
  const p = (x: number) => String(x).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function hm(t: number): string {
  const d = new Date(t)
  const p = (x: number) => String(x).padStart(2, "0")
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 环比：返回方向与文案（如 "▲ 1.2%"）。无对比值时返回 null。 */
export function delta(cur: number | null | undefined, prev: number | null | undefined) {
  if (cur == null || prev == null) return null
  const d = cur - prev
  const abs = Math.abs(d) * 100
  if (Math.abs(d) < 0.0005) return { dir: "flat" as const, text: `▬ 持平` }
  const arrow = d > 0 ? "▲" : "▼"
  return { dir: (d > 0 ? "up" : "down") as "up" | "down", text: `${arrow} ${abs.toFixed(1)}%` }
}

/** 取姓名/邮箱首字作为头像占位。 */
export function initialOf(s: string | null | undefined): string {
  if (!s) return "?"
  const trimmed = s.trim()
  if (!trimmed) return "?"
  return trimmed[0].toUpperCase()
}
