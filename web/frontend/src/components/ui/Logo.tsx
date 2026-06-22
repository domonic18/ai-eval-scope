import { Link } from "react-router-dom"

/** EvalScope reticle logo（.logo）。应用内点击回到看板。 */
export function Logo({ to = "/dashboard", fontSize = 15 }: { to?: string; fontSize?: number }) {
  return (
    <Link to={to} className="logo" style={{ fontSize }}>
      <span className="logo-mark">
        <img src="/logo.svg" alt="" style={{ width: "100%", height: "100%" }} />
      </span>
      <span className="logo-text">
        Eval<b>Scope</b>
      </span>
    </Link>
  )
}
