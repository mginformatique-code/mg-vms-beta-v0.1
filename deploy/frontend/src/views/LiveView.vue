<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Camera } from '../types'

const auth = useAuthStore()
const cameras = ref<Camera[]>([])

onMounted(async () => {
  const { data } = await api.get<Camera[]>('/cameras')
  cameras.value = data.filter((c) => c.status === 'online')
})

async function ptz(cameraId: string, action: string) {
  await api.post(`/cameras/${cameraId}/ptz`, { action })
}
</script>

<template>
  <div data-testid="live-page">
    <div class="header">
      <h1>Vue en direct</h1>
      <span v-if="!auth.can('stream_hd')" class="badge badge-warn" data-testid="sd-badge">Qualité SD</span>
    </div>
    <div class="grid">
      <div v-for="c in cameras" :key="c.id" class="card tile" :data-testid="`live-tile-${c.name}`">
        <div class="video-placeholder">
          <span class="muted">Flux WebRTC/HLS — {{ c.name }}</span>
        </div>
        <div class="tile-footer">
          <span>{{ c.name }}</span>
          <div v-if="c.ptz_enabled && auth.can('ptz_control')" class="ptz" data-testid="ptz-controls">
            <button class="btn" @click="ptz(c.id, 'left')">◀</button>
            <button class="btn" @click="ptz(c.id, 'up')">▲</button>
            <button class="btn" @click="ptz(c.id, 'down')">▼</button>
            <button class="btn" @click="ptz(c.id, 'right')">▶</button>
          </div>
        </div>
      </div>
      <p v-if="!cameras.length" class="muted">Aucune caméra en ligne.</p>
    </div>
  </div>
</template>

<style scoped>
.header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.tile { padding: 0; overflow: hidden; }
.video-placeholder { aspect-ratio: 16/9; background: #000; display: flex; align-items: center; justify-content: center; }
.tile-footer { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; }
.ptz { display: flex; gap: 4px; }
.ptz .btn { padding: 4px 8px; }
</style>
