// Module-level reactive auth session (no pinia dependency).
//
// /api/auth/me is the only authenticated read the shell performs; every other
// page pulls its own data through the api composable.

import { computed, reactive } from "vue"
import { api } from "~/composables/api"

export interface Me {
  name: string | null
  email: string
  is_admin: boolean
  groups: string[]
}

const state = reactive<{ loading: boolean; me: Me | null }>({
  loading: true,
  me: null,
})

export function useAuthStore() {
  async function refresh(): Promise<void> {
    state.loading = true
    try {
      state.me = await api.get<Me>("/auth/me", true)
    } catch {
      state.me = null
    } finally {
      state.loading = false
    }
  }

  function login(): void {
    window.location.assign("/api/auth/start")
  }

  async function logout(): Promise<void> {
    try {
      await api.post("/auth/logout")
    } finally {
      state.me = null
    }
  }

  return {
    loading: computed(() => state.loading),
    me: computed(() => state.me),
    isAdmin: computed(() => state.me?.is_admin === true),
    refresh,
    login,
    logout,
  }
}