<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Camera, Recording } from '../types'

const auth = useAuthStore()
const recordings = ref<Recording[]>([])
const cameras = ref<Camera[]>([])

onMounted(async () => {
  const [recRes, camRes] = await Promise.all([api.get('/recordings'), api.get('/cameras')])
  recordings.value = recRes.data
  cameras.value = camRes.data
})

function cameraName(id: string) {
  return cameras.value.find((c) => c.id === id)?.name ?? id.slice(0, 8)
}

function formatSize(bytes: number) {
  return bytes > 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} Go` : `${(bytes / 1024 ** 2).toFixed(0)} Mo`
}

async function exportRecording(id: string) {
  const { data } = await api.get(`/playback/${id}/export`)
  window.open(data.download_url, '_blank')
}
</script>

<template>
  <div data-testid="recordings-page">
    <h1>Enregistrements</h1>
    <div class="card">
      <table>
        <thead><tr><th>Caméra</th><th>Début</th><th>Fin</th><th>Taille</th><th>Statut</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in recordings" :key="r.id">
            <td>{{ cameraName(r.camera_id) }}</td>
            <td>{{ new Date(r.start_ts).toLocaleString('fr-FR') }}</td>
            <td>{{ r.end_ts ? new Date(r.end_ts).toLocaleString('fr-FR') : '—' }}</td>
            <td class="muted">{{ formatSize(r.size_bytes) }}</td>
            <td><span class="badge" :class="r.status === 'recording' ? 'badge-warn' : 'badge-ok'">{{ r.status }}</span></td>
            <td>
              <button v-if="auth.can('export_files')" class="btn" data-testid="export-recording-button"
                      @click="exportRecording(r.id)">Exporter</button>
            </td>
          </tr>
          <tr v-if="!recordings.length"><td colspan="6" class="muted">Aucun enregistrement</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-bottom: 20px; }
</style>
