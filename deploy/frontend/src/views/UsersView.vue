<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api, { formatApiError } from '../api/client'
import type { User } from '../types'

const PERMISSIONS: { key: string; label: string }[] = [
  { key: 'view_live', label: 'Vue en direct' },
  { key: 'view_recordings', label: 'Enregistrements' },
  { key: 'read_anpr', label: 'Lecture LAPI' },
  { key: 'stream_hd', label: 'Flux HD' },
  { key: 'ptz_control', label: 'Contrôle PTZ' },
  { key: 'export_files', label: 'Exports' },
]
const ROLES: Record<number, string> = { 1: 'Administrateur', 2: 'Technicien', 3: 'Opérateur' }

const users = ref<User[]>([])
const showForm = ref(false)
const error = ref('')
const form = ref({ email: '', password: '', name: '', role_id: 3 })

async function load() {
  const { data } = await api.get<User[]>('/users')
  users.value = data
}

async function create() {
  error.value = ''
  try {
    await api.post('/users', form.value)
    showForm.value = false
    form.value = { email: '', password: '', name: '', role_id: 3 }
    await load()
  } catch (e) {
    error.value = formatApiError(e)
  }
}

async function togglePermission(user: User, key: string) {
  const next = { [key]: !user.permissions?.[key] }
  const { data } = await api.patch<User>(`/users/${user.id}/permissions`, next)
  user.permissions = data.permissions
}

async function remove(id: string) {
  await api.delete(`/users/${id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <div data-testid="users-page">
    <div class="header">
      <h1>Utilisateurs & permissions</h1>
      <button class="btn btn-primary" data-testid="add-user-button" @click="showForm = !showForm">+ Ajouter</button>
    </div>

    <form v-if="showForm" class="card form" @submit.prevent="create">
      <input v-model="form.name" class="input" placeholder="Nom" required data-testid="user-name-input" />
      <input v-model="form.email" class="input" type="email" placeholder="Email" required data-testid="user-email-input" />
      <input v-model="form.password" class="input" type="password" placeholder="Mot de passe (8 min.)" required minlength="8" data-testid="user-password-input" />
      <select v-model.number="form.role_id" class="input" data-testid="user-role-select">
        <option :value="2">Technicien</option>
        <option :value="3">Opérateur</option>
      </select>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="btn btn-primary" type="submit" data-testid="user-submit-button">Créer</button>
    </form>

    <div class="card matrix-card">
      <h2>Matrice de permissions</h2>
      <table>
        <thead>
          <tr>
            <th>Utilisateur</th><th>Rôle</th>
            <th v-for="p in PERMISSIONS" :key="p.key">{{ p.label }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" :data-testid="`user-row-${u.email}`">
            <td>{{ u.name }}<div class="muted">{{ u.email }}</div></td>
            <td><span class="badge badge-muted">{{ ROLES[u.role_id] }}</span></td>
            <td v-for="p in PERMISSIONS" :key="p.key" class="perm-cell">
              <span v-if="u.role_id === 1" class="muted">✓</span>
              <input v-else type="checkbox" :checked="Boolean(u.permissions?.[p.key])"
                     :data-testid="`perm-${u.email}-${p.key}`" @change="togglePermission(u, p.key)" />
            </td>
            <td><button v-if="u.role_id !== 1" class="btn btn-danger" @click="remove(u.id)">Supprimer</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
.matrix-card h2 { margin-bottom: 14px; }
.perm-cell { text-align: center; }
</style>
