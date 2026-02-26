import { create } from "zustand"
import { GetUserInfo } from "@/app/api/os"
import type { UserPermissions } from "@/types/playground"
import { DEFAULT_PERMISSIONS } from "@/types/playground"

// Before permissions are loaded, deny everything to prevent flash of
// unauthorised UI. Once fetched, the real values replace these.
const DENY_ALL: UserPermissions = {
  create_agents: false,
  create_teams: false,
  create_workflows: false,
  create_tools: false,
  manage_providers: false,
  manage_mcp_servers: false,
  create_knowledge_bases: false,
}

interface PermissionsState {
  permissions: UserPermissions
  loaded: boolean
  /** The role returned by the latest /get_user_details call. */
  latestRole: string | null

  fetchPermissions: (accessToken?: string) => Promise<void>
  hasPermission: (key: keyof UserPermissions) => boolean
  reset: () => void
}

export const usePermissionsStore = create<PermissionsState>((set, get) => ({
  permissions: { ...DENY_ALL },
  loaded: false,
  latestRole: null,

  fetchPermissions: async (accessToken?: string) => {
    try {
      const user = await GetUserInfo(accessToken)
      const role = user.role || null
      if (user.permissions) {
        const merged = { ...DEFAULT_PERMISSIONS, ...user.permissions } as UserPermissions
        set({ permissions: merged, loaded: true, latestRole: role })
      } else {
        // No permissions field → admin or legacy user, grant all
        set({ permissions: { ...DEFAULT_PERMISSIONS }, loaded: true, latestRole: role })
      }
    } catch (error) {
      console.error("Failed to fetch permissions:", error)
      set({ loaded: true })
    }
  },

  hasPermission: (key: keyof UserPermissions) => {
    return get().permissions[key] ?? false
  },

  reset: () => {
    set({ permissions: { ...DENY_ALL }, loaded: false, latestRole: null })
  },
}))
