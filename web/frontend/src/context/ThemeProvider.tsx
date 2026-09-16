import { useCallback, useEffect, useState, type ReactNode } from "react"
import {
  THEME_STORAGE_KEY,
  ThemeContext,
  applyThemeClass,
  readStoredTheme,
  systemTheme,
  type Theme,
} from "@/context/theme"

/** 主题运行时：初始化读 DOM 类（与 index.html 内联脚本决策一致），
 *  setTheme 持久化到 localStorage，未显式选择时实时跟随系统切换。 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  )

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    applyThemeClass(t)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, t)
    } catch {
      // file:// 或隐私模式可能拒绝写入，忽略（会话内仍生效）
    }
  }, [])

  const toggle = useCallback(
    () => setTheme(document.documentElement.classList.contains("dark") ? "light" : "dark"),
    [setTheme],
  )

  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: light)")
    const onChange = () => {
      if (!readStoredTheme()) setThemeState(systemTheme())
    }
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>{children}</ThemeContext.Provider>
  )
}
