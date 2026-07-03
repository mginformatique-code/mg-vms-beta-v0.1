<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '../api/client'
import type { Site } from '../types'

interface PlateHit {
  id: string
  plate: string
  site_id: string
  confidence: number | null
  country: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_color: string | null
  vehicle_type: string | null
  direction: string | null
  list_status: string
  image_url: string | null
  ts: string
}

const sites = ref<Site[]>([])
const results = ref<PlateHit[]>([])
const loading = ref(false)
const searched = ref(false)
const filters = ref({ q: '', site_id: '', list_status: '', start: '', end: '' })

async function search() {
  loading.value = true
  try {
    const params: Record<string, string> = { limit: '200' }
    if (filters.value.q) params.q = filters.value.q
    if (filters.value.site_id) params.site_id = filters.value.site_id
    if (filters.value.list_status) params.list_status = filters.value.list_status
    if (filters.value.start) params.start = new Date(filters.value.start).toISOString()
    if (filters.value.end) params.end = new Date(filters.value.end).toISOString()
    const { data } = await api.get<PlateHit[]>('/ai/plates', { params })
    results.value = data
    searched.value = true
  } finally {
    loading.value = false
  }
}

function siteName(id: string) {
  return sites.value.find((s) => s.id === id)?.name ?? '—'
}

function vehicleLabel(p: PlateHit) {
  return [p.vehicle_color, p.vehicle_make, p.vehicle_model].filter(Boolean).join(' ') || '—'
}

onMounted(async () => {
  const { data } = await api.get<Site[]>('/sites')
  sites.value = data
  await search()
})
</script>

<template>
  <div data-testid="anpr-page">
    <h1>Recherche LAPI</h1>

    <form class="card filters" @submit.prevent="search">
      <input v-model="filters.q" class="input" placeholder="Plaque (partielle) — ex. AB-123"
             data-testid="anpr-search-input" />
      <select v-model="filters.site_id" class="input" data-testid="anpr-site-filter">
        <option value="">Tous les sites</option>
        <option v-for="s in sites" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="filters.list_status" class="input" data-testid="anpr-list-filter">
        <option value="">Toutes les listes</option>
        <option value="black">Liste noire</option>
        <option value="white">Liste blanche</option>
        <option value="none">Sans liste</option>
      </select>
      <input v-model="filters.start" class="input" type="datetime-local" data-testid="anpr-start-filter" />
      <input v-model="filters.end" class="input" type="datetime-local" data-testid="anpr-end-filter" />
      <button class="btn btn-primary" type="submit" :disabled="loading" data-testid="anpr-search-button">
        {{ loading ? 'Recherche...' : 'Rechercher' }}
      </button>
    </form>

    <div class="card">
      <div class="results-header">
        <h2>Résultats</h2>
        <span class="muted" data-testid="anpr-results-count">{{ results.length }} lecture(s)</span>
      </div>
      <table>
        <thead>
          <tr><th>Plaque</th><th>Véhicule</th><th>Site</th><th>Direction</th><th>Confiance</th><th>Liste</th><th>Photo</th><th>Horodatage</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in results" :key="p.id" :data-testid="`anpr-row-${p.plate}`">
            <td><span class="plate">{{ p.plate }}</span><span v-if="p.country" class="muted"> ({{ p.country }})</span></td>
            <td>{{ vehicleLabel(p) }}<div v-if="p.vehicle_type" class="muted">{{ p.vehicle_type }}</div></td>
            <td>{{ siteName(p.site_id) }}</td>
            <td class="muted">{{ p.direction ?? '—' }}</td>
            <td>{{ p.confidence != null ? `${Math.round(p.confidence * 100)}%` : '—' }}</td>
            <td>
              <span class="badge" :class="p.list_status === 'black' ? 'badge-danger' : p.list_status === 'white' ? 'badge-ok' : 'badge-muted'">
                {{ p.list_status === 'black' ? 'Noire' : p.list_status === 'white' ? 'Blanche' : '—' }}
              </span>
            </td>
            <td>
              <a v-if="p.image_url" :href="p.image_url" target="_blank" rel="noopener">
                <img :src="p.image_url" class="thumb" alt="Capture" />
              </a>
              <span v-else class="muted">—</span>
            </td>
            <td class="muted">{{ new Date(p.ts).toLocaleString('fr-FR') }}</td>
          </tr>
          <tr v-if="searched && !results.length"><td colspan="8" class="muted">Aucune lecture trouvée</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-bottom: 20px; }
.filters { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr auto; gap: 12px; margin-bottom: 20px; align-items: center; }
.results-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.plate { font-family: monospace; font-weight: 700; letter-spacing: 1px; background: var(--surface-2); padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border); }
.thumb { height: 36px; border-radius: 4px; display: block; }
@media (max-width: 1100px) { .filters { grid-template-columns: 1fr 1fr; } }
</style>
