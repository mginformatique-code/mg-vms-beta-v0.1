import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    {
      path: '/',
      component: () => import('../components/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'cameras', name: 'cameras', component: () => import('../views/CamerasView.vue') },
        { path: 'live', name: 'live', component: () => import('../views/LiveView.vue') },
        { path: 'recordings', name: 'recordings', component: () => import('../views/RecordingsView.vue') },
        { path: 'events', name: 'events', component: () => import('../views/EventsView.vue') },
        { path: 'users', name: 'users', component: () => import('../views/UsersView.vue'), meta: { adminOnly: true } },
        { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { adminOnly: true } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.fetchMe()
  if (to.meta.requiresAuth && !auth.user) return { name: 'login' }
  if (to.meta.adminOnly && !auth.isAdmin) return { name: 'dashboard' }
  if (to.name === 'login' && auth.user) return { name: 'dashboard' }
})

export default router
