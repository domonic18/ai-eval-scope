import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom"
import { loadSession } from "./store/auth"
import { AppShell, useOrg } from "./components/AppShell"
import Landing from "./pages/Landing"
import DocsPage from "./pages/DocsPage"
import LoginPage from "./pages/LoginPage"
import RegisterPage from "./pages/RegisterPage"
import JoinPage from "./pages/JoinPage"
import Dashboard from "./pages/Dashboard"
import ProjectDetail from "./pages/ProjectDetail"
import RunDetail from "./pages/RunDetail"
import SampleDetail from "./pages/SampleDetail"
import ComingSoon from "./pages/ComingSoon"
import DebugPage from "./pages/DebugPage"
import AdminLayout from "./pages/admin/AdminLayout"
import AdminOverview from "./pages/admin/AdminOverview"
import AdminUsers from "./pages/admin/AdminUsers"
import AdminOrgs from "./pages/admin/AdminOrgs"
import AdminProjects from "./pages/admin/AdminProjects"
import AdminRuns from "./pages/admin/AdminRuns"
import AdminArtifacts from "./pages/admin/AdminArtifacts"
import AdminAudit from "./pages/admin/AdminAudit"

/** 根路径：已登录进看板，未登录展示产品落地页。 */
function RootRedirect() {
  return loadSession() ? <Navigate to="/dashboard" replace /> : <Landing />
}

/** 登录守卫：无 session 跳登录（记下来源）。通过则渲染 AppShell（含 Outlet）。 */
function RequireAuth() {
  const loc = useLocation()
  if (!loadSession()) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  }
  return <AppShell />
}

/** owner 守卫：当前组织非 owner → 回看板（特殊入口，普通 member 不可见）。 */
function RequireOwner() {
  const { memberships, activeOrg, loading } = useOrg()
  // memberships 异步加载中（orgLoading=true）暂不判定，避免加载未完成被误重定向
  if (loading) return null
  const active = memberships.find((m) => m.orgId === activeOrg)
  if (!active || active.role !== "owner") {
    return <Navigate to="/dashboard" replace />
  }
  return <Outlet />
}

/** 超管守卫：非 platformAdmin → 回看板（管理后台独立 shell，不嵌套 AppShell）。 */
function RequireAdmin() {
  const session = loadSession()
  if (!session) return <Navigate to="/login" replace state={{ from: "/admin" }} />
  if (!session.user?.platformAdmin) return <Navigate to="/dashboard" replace />
  return <AdminLayout />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/docs" element={<DocsPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/join" element={<JoinPage />} />
        <Route path="/project/:id" element={<ProjectDetail />} />
        <Route path="/run/:id" element={<RunDetail />} />
        <Route path="/run/:id/sample/:sid" element={<SampleDetail />} />
        <Route path="/runs" element={<ComingSoon title="全部运行" />} />
        <Route element={<RequireOwner />}>
          <Route path="/debug" element={<DebugPage />} />
        </Route>
      </Route>
      {/* 超管后台（独立 shell，platformAdmin 专属）*/}
      <Route element={<RequireAdmin />}>
        <Route path="/admin" element={<AdminOverview />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/orgs" element={<AdminOrgs />} />
        <Route path="/admin/projects" element={<AdminProjects />} />
        <Route path="/admin/runs" element={<AdminRuns />} />
        <Route path="/admin/artifacts" element={<AdminArtifacts />} />
        <Route path="/admin/audit" element={<AdminAudit />} />
      </Route>
    </Routes>
  )
}
