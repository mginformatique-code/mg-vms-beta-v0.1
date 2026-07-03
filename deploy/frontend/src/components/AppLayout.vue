<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const links = [
  { to: '/', label: 'Tableau de bord', icon: '▦' },
  { to: '/live', label: 'Direct', icon: '▶' },
  { to: '/cameras', label: 'Caméras', icon: '◎' },
  { to: '/recordings', label: 'Enregistrements', icon: '⏺' },
  { to: '/events', label: 'Événements', icon: '⚡' },
]

async function logout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">MG-<span>VMS</span></div>
      <nav>
        <router-link v-for="l in links" :key="l.to" :to="l.to" class="nav-link" :data-testid="`nav-${l.label}`">
          <span class="icon">{{ l.icon }}</span>{{ l.label }}
        </router-link>
        <router-link v-if="auth.can('read_anpr')" to="/anpr" class="nav-link" data-testid="nav-anpr">
          <span class="icon">▤</span>Recherche LAPI
        </router-link>
        <template v-if="auth.isAdmin">
          <div class="nav-section">Administration</div>
          <router-link to="/users" class="nav-link" data-testid="nav-users"><span class="icon">◉</span>Utilisateurs</router-link>
          <router-link to="/settings" class="nav-link" data-testid="nav-settings"><span class="icon">⚙</span>Paramètres</router-link>
        </template>
      </nav>
      <div class="sidebar-footer">
        <div class="user-info">
          <div>{{ auth.user?.name }}</div>
          <div class="muted">{{ auth.user?.email }}</div>
        </div>
        <button class="btn" data-testid="logout-button" @click="logout">Déconnexion</button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; min-height: 100vh; }
.sidebar {
  width: 230px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
  position: sticky;
  top: 0;
  height: 100vh;
}
.brand { font-size: 1.3rem; font-weight: 700; padding: 0 10px 20px; letter-spacing: 1px; }
.brand span { color: var(--accent); }
nav { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--radius);
  color: var(--muted);
  transition: background-color 0.15s, color 0.15s;
}
.nav-link:hover { background: var(--surface-2); color: var(--text); }
.nav-link.router-link-exact-active { background: var(--surface-2); color: var(--accent); }
.icon { width: 18px; text-align: center; }
.nav-section { padding: 16px 10px 6px; font-size: 11px; text-transform: uppercase; color: var(--muted); }
.sidebar-footer { display: flex; flex-direction: column; gap: 10px; padding: 10px; border-top: 1px solid var(--border); font-size: 13px; }
.content { flex: 1; padding: 28px 32px; }
</style>
