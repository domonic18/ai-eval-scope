import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { loadSession } from "./store/auth"
import { AppShell } from "./components/ui"
import Login from "./pages/Login"
import Dashboard from "./pages/Dashboard"
import ProjectDetail from "./pages/ProjectDetail"
import RunDetail from "./pages/RunDetail"
import SampleDetail from "./pages/SampleDetail"
import ComingSoon from "./pages/ComingSoon"

/** 根路径：已登录进看板，未登录进登录页（为公开落地页占位）。 */
function RootRedirect() {
  return <Navigate to={loadSession() ? "/dashboard" : "/login"} replace />
}

/** 登录守卫：无 session 跳登录（记下来源）。通过则渲染 AppShell（含 Outlet）。 */
function RequireAuth() {
  const loc = useLocation()
  if (!loadSession()) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  }
  return <AppShell />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/project/:id" element={<ProjectDetail />} />
        <Route path="/run/:id" element={<RunDetail />} />
        <Route path="/run/:id/sample/:sid" element={<SampleDetail />} />
        <Route path="/runs" element={<ComingSoon title="全部运行" />} />
        <Route path="/members" element={<ComingSoon title="成员" />} />
        <Route path="/settings" element={<ComingSoon title="组织设置" />} />
      </Route>
    </Routes>
  )
}
