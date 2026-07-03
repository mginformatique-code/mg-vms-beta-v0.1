<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Camera, Recording } from '../types'

interface Segment { id: string; start: string; end: string | null; status: string }

const auth = useAuthStore()
const recordings = ref<Recording[]>([])
const cameras = ref<Camera[]>([])
const selectedCamera = ref('')
const selectedDay = ref(new Date().toISOString().slice(0, 10))
const segments = ref<Segment[]>([])
const timelineLoading = ref(false)
const hovered = ref<Segment | null>(null)

const HOURS = Array.from({ length: 25 }, (_, i) => i)

onMounted(async () => {
  const [recRes, camRes] = await Promise.all([api.get('/recordings'), api.get('/cameras')])
  recordings.value = recRes.data
  cameras.value = camRes.data
  if (cameras.value.length) {
    selectedCamera.value = cameras.value[0].id
  }
})

async function loadTimeline() {
  if (!selectedCamera.value) return
  timelineLoading.value = true
  try {
    const { data } = await api.get(`/recordings/timeline/${selectedCamera.value}`, {
      params: { day: `${selectedDay.value}T00:00:00` },
    })
    segments.value = data.segments
  } finally {
    timelineLoading.value = false
  }
}

watch([selectedCamera, selectedDay], loadTimeline)

const dayStart = computed(() => new Date(`${selectedDay.value}T00:00:00`).getTime())
const DAY_MS = 86_400_000

function segmentStyle(seg: Segment) {
  const start = Math.max(new Date(seg.start).getTime(), dayStart.value)
  const end = Math.min(seg.end ? new Date(seg.end).getTime() : Date.now(), dayStart.value + DAY_MS)
  const left = ((start - dayStart.value) / DAY_MS) * 100
  const width = Math.max(((end - start) / DAY_MS) * 100, 0.3)
  return { left: `${left}%`, width: `${width}%` }
}

function segmentTooltip(seg: Segment) {
  const fmt = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR')
  return `${fmt(seg.start)} → ${seg.end ? fmt(seg.end) : 'en cours'}`
}

async function play(seg: Segment) {
  const { data } = await api.get(`/playback/${seg.id}/url`)
  window.open(data.url, '_blank')
}

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

    <div class="card timeline-card">
      <div class="timeline-header">
        <h2>Timeline 24h</h2>
        <div class="controls">
          <select v-model="selectedCamera" class="input" data-testid="timeline-camera-select">
            <option v-for="c in cameras" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <input v-model="selectedDay" class="input" type="date" data-testid="timeline-day-input" />
        </div>
      </div>

      <div class="timeline" data-testid="timeline-track">
        <div v-for="seg in segments" :key="seg.id" class="segment"
             :class="seg.status === 'recording' ? 'seg-live' : 'seg-closed'"
             :style="segmentStyle(seg)" :data-testid="`timeline-segment-${seg.id}`"
             @mouseenter="hovered = seg" @mouseleave="hovered = null" @click="play(seg)" />
      </div>
      <div class="hours">
        <span v-for="h in HOURS" :key="h" class="hour-tick">{{ h % 4 === 0 ? `${h}h` : '' }}</span>
      </div>
      <p class="muted tooltip-line">
        <template v-if="hovered">{{ segmentTooltip(hovered) }} — cliquer pour lire</template>
        <template v-else-if="timelineLoading">Chargement...</template>
        <template v-else-if="!segments.length">Aucun segment ce jour</template>
        <template v-else>{{ segments.length }} segment(s) — survoler pour le détail, cliquer pour lire</template>
      </p>
    </div>

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
.timeline-card { margin-bottom: 20px; }
.timeline-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; gap: 12px; flex-wrap: wrap; }
.controls { display: flex; gap: 10px; }
.controls .input { width: 200px; }
.timeline {
  position: relative;
  height: 44px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background-image: repeating-linear-gradient(to right, transparent, transparent calc(100% / 24 - 1px), var(--border) calc(100% / 24 - 1px), var(--border) calc(100% / 24));
}
.segment { position: absolute; top: 4px; bottom: 4px; border-radius: 3px; cursor: pointer; transition: opacity 0.15s; }
.segment:hover { opacity: 0.75; }
.seg-closed { background: var(--accent-dark); }
.seg-live { background: var(--warning); }
.hours { display: flex; justify-content: space-between; margin-top: 4px; }
.hour-tick { flex: 1; font-size: 10px; color: var(--muted); text-align: left; }
.hour-tick:last-child { flex: 0; }
.tooltip-line { margin-top: 8px; font-size: 12px; min-height: 16px; }
</style>
