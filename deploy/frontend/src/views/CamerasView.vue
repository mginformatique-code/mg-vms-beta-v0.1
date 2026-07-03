<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api, { formatApiError } from '../api/client'
import type { Camera, Site } from '../types'

const cameras = ref<Camera[]>([])
const sites = ref<Site[]>([])
const showForm = ref(false)
const error = ref('')
const form = ref({ name: '', site_id: '', rtsp_url: '', ip: '', ptz_enabled: false })

async function load() {
  const [camerasRes, sitesRes] = await Promise.all([api.get('/cameras'), api.get('/sites')])
  cameras.value = camerasRes.data
  sites.value = sitesRes.data
}

async function create() {
  error.value = ''
  try {
    await api.post('/cameras', { ...form.value, ip: form.value.ip || null, rtsp_url: form.value.rtsp_url || null })
    showForm.value = false
    form.value = { name: '', site_id: '', rtsp_url: '', ip: '', ptz_enabled: false }
    await load()
  } catch (e) {
    error.value = formatApiError(e)
  }
}

async function remove(id: string) {
  await api.delete(`/cameras/${id}`)
  await load()
}

function siteName(id: string) {
  return sites.value.find((s) => s.id === id)?.name ?? '—'
}

onMounted(load)
</script>

<template>
  <div data-testid="cameras-page">
    <div class="header">
      <h1>Caméras</h1>
      <button class="btn btn-primary" data-testid="add-camera-button" @click="showForm = !showForm">+ Ajouter</button>
    </div>

    <form v-if="showForm" class="card form" @submit.prevent="create">
      <input v-model="form.name" class="input" placeholder="Nom" required data-testid="camera-name-input" />
      <select v-model="form.site_id" class="input" required data-testid="camera-site-select">
        <option value="" disabled>Site...</option>
        <option v-for="s in sites" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <input v-model="form.ip" class="input" placeholder="Adresse IP" />
      <input v-model="form.rtsp_url" class="input" placeholder="URL RTSP" />
      <label><input v-model="form.ptz_enabled" type="checkbox" /> PTZ</label>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="btn btn-primary" type="submit" data-testid="camera-submit-button">Créer</button>
    </form>

    <div class="card">
      <table>
        <thead><tr><th>Nom</th><th>Site</th><th>IP</th><th>Statut</th><th>PTZ</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in cameras" :key="c.id" :data-testid="`camera-row-${c.name}`">
            <td>{{ c.name }}</td>
            <td>{{ siteName(c.site_id) }}</td>
            <td class="muted">{{ c.ip ?? '—' }}</td>
            <td><span class="badge" :class="c.status === 'online' ? 'badge-ok' : 'badge-danger'">{{ c.status }}</span></td>
            <td>{{ c.ptz_enabled ? 'Oui' : 'Non' }}</td>
            <td><button class="btn btn-danger" @click="remove(c.id)">Supprimer</button></td>
          </tr>
          <tr v-if="!cameras.length"><td colspan="6" class="muted">Aucune caméra</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
</style>
