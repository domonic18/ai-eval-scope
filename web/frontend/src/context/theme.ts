import { createContext, useContext } from "react"

/** 主题（docs/design/00-设计规范.md §9）：显式选择（localStorage es-theme）> 系统偏好 > 默认深色。
 *  首帧已由 index.html 内联脚本落 .dark 类，ThemeProvider 接管运行时状态与持久化。 */
export type Theme = "light" | "dark"

export const THEME_STORAGE_KEY = "es-theme"

export function readStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    return v === "light" || v === "dark" ? v : null
  } catch {
    return null
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark"
}

export function applyThemeClass(t: Theme) {
  document.documentElement.classList.toggle("dark", t === "dark")
}

interface ThemeApi {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

export const ThemeContext = createContext<ThemeApi>({
  theme: "dark",
  setTheme: () => {},
  toggle: () => {},
})

export const useTheme = () => useContext(ThemeContext)
