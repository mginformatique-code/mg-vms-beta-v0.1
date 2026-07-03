<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '../api/client'
import type { VmsEvent } from '../types'

const events = ref<VmsEvent[]>([])
const typeFilter = ref('')

async function load() {
  const { data } = await api.get<VmsEvent[]>('/events', {
    params: { limit: 200, ...(typeFilter.value ? { type: typeFilter.value } : {}) },
  })
  events.value = data
}

async function ack(id: string) {
  await api.post(`/events/${id}/ack`)
  await load()
}

onMounted(load)
</script>

<template>
  <div data-testid="events-page">
    <div class="header">
      <h1>Événements</h1>
      <select v-model="typeFilter" class="input filter" data-testid="event-type-filter" @change="load">
        <option value="">Tous les types</option>
        <option value="motion">Mouvement</option>
        <option value="intrusion">Intrusion</option>
        <option value="line_crossing">Franchissement de ligne</option>
        <option value="object">Objet détecté</option>
        <option value="anpr">LAPI (plaque)</option>
      </select>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>Type</th><th>Sévérité</th><th>Horodatage</th><th>Acquitté</th><th></th></tr></thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>{{ e.type }}</td>
            <td><span class="badge" :class="e.severity === 'critical' ? 'badge-danger' : e.severity === 'warning' ? 'badge-warn' : 'badge-muted'">{{ e.severity }}</span></td>
            <td class="muted">{{ new Date(e.ts).toLocaleString('fr-FR') }}</td>
            <td>{{ e.acknowledged ? '✓' : '—' }}</td>
            <td><button v-if="!e.acknowledged" class="btn" data-testid="ack-event-button" @click="ack(e.id)">Acquitter</button></td>
          </tr>
          <tr v-if="!events.length"><td colspan="5" class="muted">Aucun événement</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.filter { width: 220px; }
</style>
