<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api, { formatApiError } from '../api/client'

interface Channel { id: string; type: string; name: string; enabled: boolean; config: Record<string, string> }

const channels = ref<Channel[]>([])
const error = ref('')
const message = ref('')
const form = ref({ type: 'email', name: '', configJson: '{}' })

async function load() {
  const { data } = await api.get('/notifications/channels')
  channels.value = data
}

async function create() {
  error.value = ''
  try {
    await api.post('/notifications/channels', {
      type: form.value.type, name: form.value.name,
      config: JSON.parse(form.value.configJson || '{}'),
    })
    form.value = { type: 'email', name: '', configJson: '{}' }
    await load()
  } catch (e) {
    error.value = e instanceof SyntaxError ? 'JSON de configuration invalide' : formatApiError(e)
  }
}

async function test(id: string) {
  await api.post(`/notifications/channels/${id}/test`)
  message.value = 'Notification de test envoyée.'
}

async function remove(id: string) {
  await api.delete(`/notifications/channels/${id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <div data-testid="settings-page">
    <h1>Paramètres</h1>

    <div class="card section">
      <h2>Canaux de notification</h2>
      <table>
        <thead><tr><th>Nom</th><th>Type</th><th>Actif</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in channels" :key="c.id">
            <td>{{ c.name }}</td>
            <td><span class="badge badge-muted">{{ c.type }}</span></td>
            <td>{{ c.enabled ? 'Oui' : 'Non' }}</td>
            <td class="actions">
              <button class="btn" data-testid="test-channel-button" @click="test(c.id)">Tester</button>
              <button class="btn btn-danger" @click="remove(c.id)">Supprimer</button>
            </td>
          </tr>
          <tr v-if="!channels.length"><td colspan="4" class="muted">Aucun canal configuré</td></tr>
        </tbody>
      </table>
      <p v-if="message" class="muted">{{ message }}</p>

      <form class="form" @submit.prevent="create">
        <select v-model="form.type" class="input" data-testid="channel-type-select">
          <option value="email">Email (SMTP)</option>
          <option value="discord">Discord</option>
          <option value="telegram">Telegram</option>
          <option value="webhook">Webhook</option>
        </select>
        <input v-model="form.name" class="input" placeholder="Nom du canal" required data-testid="channel-name-input" />
        <input v-model="form.configJson" class="input" placeholder='Config JSON — ex. {"to": "ops@exemple.fr"}' data-testid="channel-config-input" />
        <p v-if="error" class="error-text">{{ error }}</p>
        <button class="btn btn-primary" type="submit" data-testid="channel-submit-button">Ajouter le canal</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-bottom: 20px; }
.section h2 { margin-bottom: 14px; }
.form { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px; align-items: center; }
.actions { display: flex; gap: 8px; }
</style>
