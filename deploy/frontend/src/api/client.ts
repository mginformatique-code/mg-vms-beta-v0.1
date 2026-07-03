import axios from 'axios'

const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL ?? ''}/api`,
  withCredentials: true,
})

let refreshing: Promise<void> | null = null

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry && original.url !== '/auth/refresh') {
      original._retry = true
      refreshing ??= api.post('/auth/refresh').then(() => undefined).finally(() => { refreshing = null })
      try {
        await refreshing
        return api(original)
      } catch {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export function formatApiError(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((e) => e?.msg ?? '').filter(Boolean).join(' ')
  return 'Une erreur est survenue. Veuillez réessayer.'
}

export default api
