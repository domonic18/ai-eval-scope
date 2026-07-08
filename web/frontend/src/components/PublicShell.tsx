import { Link, Outlet } from "react-router-dom"
import { Badge } from "@/components/shadcn/badge"

/**
 * 公开访问外壳（docs/arch/12 §3.5）：
 * 用于 /run/:id、/run/:id/sample/:sid 在**无登录态**下被第三方 iframe 嵌入或匿名访问。
 *
 * - 不调用 api.me()（匿名，避免触发 401→登录重定向）。
 * - 无组织切换器 / 用户菜单 / 写操作入口（只读）。
 * - 页面内的 Query 调用走匿名（axios 无 token）；非公开项目会 401 → 由 axios 拦截器跳登录。
 */
export function PublicShell() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 items-center justify-between border-b px-4">
        <Link to="/" className="inline-flex items-center gap-2">
          <span className="flex size-6 items-center justify-center">
            <img src="/logo.svg" alt="EvalScope" className="h-full w-full" />
          </span>
          <span className="font-semibold tracking-tight">EvalScope</span>
          <Badge variant="secondary" className="font-mono text-[10px]">
            公开预览
          </Badge>
        </Link>
        <Link
          to="/login"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          登录查看更多 →
        </Link>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
