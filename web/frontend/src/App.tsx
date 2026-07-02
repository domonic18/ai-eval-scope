import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { loadSession } from "./store/auth"
import { AppShell } from "./components/AppShell"
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
        {/* 调试台：登录即可访问，不限组织 / 角色 */}
        <Route path="/debug" element={<DebugPage />} />
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
