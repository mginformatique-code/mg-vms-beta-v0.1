import { defineStore } from 'pinia'
import api from '../api/client'
import type { User } from '../types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    checked: false,
  }),
  getters: {
    isAdmin: (s) => s.user?.role_id === 1,
    can: (s) => (permission: string): boolean =>
      s.user?.role_id === 1 || Boolean(s.user?.permissions?.[permission]),
  },
  actions: {
    async fetchMe() {
      try {
        const { data } = await api.get<User>('/auth/me')
        this.user = data
      } catch {
        this.user = null
      } finally {
        this.checked = true
      }
    },
    async login(email: string, password: string) {
      await api.post('/auth/login', { email, password })
      await this.fetchMe()
    },
    async logout() {
      try { await api.post('/auth/logout') } catch { /* déjà déconnecté */ }
      this.user = null
    },
  },
})
