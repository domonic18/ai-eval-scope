import { createContext, useContext, type ReactNode } from "react"
import type { Membership } from "@/types"

/** 面包屑：label + 可选回跳 to。 */
export interface Crumb {
  label: ReactNode
  to?: string
}

interface CrumbsApi {
  crumbs: Crumb[]
  setCrumbs: (c: Crumb[]) => void
}

interface OrgApi {
  activeOrg: string | null
  memberships: Membership[]
  loading: boolean
  setActive: (orgId: string) => void
}

export const CrumbsContext = createContext<CrumbsApi>({ crumbs: [], setCrumbs: () => {} })
export const OrgContext = createContext<OrgApi>({
  activeOrg: null,
  memberships: [],
  loading: true,
  setActive: () => {},
})

export const useCrumbs = () => useContext(CrumbsContext)
export const useOrg = () => useContext(OrgContext)
