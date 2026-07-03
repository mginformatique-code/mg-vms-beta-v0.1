<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import api from '../api/client'
import type { Stats, VmsEvent } from '../types'

const stats = ref<Stats | null>(null)
const events = ref<VmsEvent[]>([])
let ws: WebSocket | null = null

onMounted(async () => {
  const [statsRes, eventsRes] = await Promise.all([
    api.get<Stats>('/monitoring/stats'),
    api.get<VmsEvent[]>('/events', { params: { limit: 10 } }),
  ])
  stats.value = statsRes.data
  events.value = eventsRes.data

  const base = import.meta.env.VITE_API_URL || window.location.origin
  ws = new WebSocket(`${base.replace(/^http/, 'ws')}/api/ws`)
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data)
    if (data.kind === 'event') events.value = [data.payload, ...events.value].slice(0, 10)
  }
})

onUnmounted(() => ws?.close())
</script>

<template>
  <div data-testid="dashboard-page">
    <h1>Tableau de bord</h1>
    <div v-if="stats" class="grid">
      <div class="card stat" data-testid="stat-cameras-online">
        <div class="value ok">{{ stats.cameras.online }}<span class="muted">/{{ stats.cameras.total }}</span></div>
        <div class="label">Caméras en ligne</div>
      </div>
      <div class="card stat" data-testid="stat-sites">
        <div class="value">{{ stats.sites }}</div>
        <div class="label">Sites</div>
      </div>
      <div class="card stat" data-testid="stat-events">
        <div class="value warn">{{ stats.events_24h }}</div>
        <div class="label">Événements (24h)</div>
      </div>
      <div class="card stat" data-testid="stat-recordings">
        <div class="value">{{ stats.recordings_active }}</div>
        <div class="label">Enregistrements actifs</div>
      </div>
    </div>
    <div class="card events-card">
      <h2>Derniers événements <span class="badge badge-ok">temps réel</span></h2>
      <table>
        <thead><tr><th>Type</th><th>Sévérité</th><th>Horodatage</th></tr></thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>{{ e.type }}</td>
            <td><span class="badge" :class="e.severity === 'critical' ? 'badge-danger' : e.severity === 'warning' ? 'badge-warn' : 'badge-muted'">{{ e.severity }}</span></td>
            <td class="muted">{{ new Date(e.ts).toLocaleString('fr-FR') }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="3" class="muted">Aucun événement</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat .value { font-size: 2rem; font-weight: 700; }
.stat .label { color: var(--muted); margin-top: 4px; }
.ok { color: var(--ok); }
.warn { color: var(--warning); }
.events-card h2 { margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }
</style>
