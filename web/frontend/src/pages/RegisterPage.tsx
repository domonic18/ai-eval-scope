/**
 * 注册页（shadcn/Tailwind 重写）— 居中卡片 + 密码强度。
 */
import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api, saveSession } from "../api/client"
import { loadSession } from "../store/auth"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { useToast } from "../components/toast"
import { Lock, Mail } from "lucide-react"

function passwordStrength(pw: string): { score: number; level: string; label: string } {
  let score = 0
  if (pw.length >= 8) score += 1
  if (/[a-zA-Z]/.test(pw) && /\d/.test(pw)) score += 1
  if (pw.length >= 12 || /[^a-zA-Z0-9]/.test(pw)) score += 1
  const levels = ["weak", "medium", "strong"]
  const labels = ["弱", "一般", "强"]
  const idx = Math.max(0, score - 1)
  return { score, level: levels[idx], label: labels[idx] }
}

const STRENGTH_COLOR: Record<string, string> = {
  weak: "bg-red-500",
  medium: "bg-yellow-500",
  strong: "bg-emerald-500",
}

export default function RegisterPage() {
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [loading, setLoading] = useState(false)

  const redirect = (loc.state as { from?: string } | null)?.from || "/dashboard"

  useEffect(() => {
    if (loadSession()) nav("/dashboard", { replace: true })
  }, [nav])

  const strength = passwordStrength(password)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (password !== confirm) {
      toast.error("两次输入的密码不一致")
      return
    }
    setLoading(true)
    try {
      const data = await api.register(email, password, name || email.split("@")[0])
      saveSession(data)
      toast.success("注册成功")
      nav(redirect)
    } catch (err) {
      const ex = err as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "注册失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="mb-3 inline-flex size-9 items-center justify-center rounded-lg bg-primary font-bold text-primary-foreground">
            E
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">创建账号</h1>
          <p className="mt-1 text-sm text-muted-foreground">注册账号，开始创建你的评估项目</p>
        </div>

        <div className="rounded-xl border bg-card p-6 text-card-foreground shadow-sm">
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">姓名</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：张工" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="pl-9"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 8 位"
                  className="pl-9"
                />
              </div>
              {password && (
                <div className="flex items-center gap-2 pt-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className={`h-1.5 flex-1 rounded-full ${
                        i < strength.score ? STRENGTH_COLOR[strength.level] : "bg-muted"
                      }`}
                    />
                  ))}
                  <span className="ml-1 text-xs text-muted-foreground">{strength.label}</span>
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">确认密码</Label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="confirm"
                  type="password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="再次输入密码"
                  className="pl-9"
                />
              </div>
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "处理中…" : "注册并进入"}
            </Button>
          </form>
        </div>

        <div className="text-center text-sm text-muted-foreground">
          已有账号？
          <button className="ml-1 text-primary hover:underline" onClick={() => nav("/login")}>
            登录
          </button>
        </div>
      </div>
    </div>
  )
}
