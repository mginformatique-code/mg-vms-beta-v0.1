<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { formatApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = formatApiError(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <form class="card login-card" @submit.prevent="submit">
      <h1>MG-<span class="accent">VMS</span></h1>
      <p class="muted">Plateforme de supervision vidéo</p>
      <input v-model="email" class="input" type="email" placeholder="Email" required data-testid="login-email-input" />
      <input v-model="password" class="input" type="password" placeholder="Mot de passe" required data-testid="login-password-input" />
      <p v-if="error" class="error-text" data-testid="login-error">{{ error }}</p>
      <button class="btn btn-primary" type="submit" :disabled="loading" data-testid="login-submit-button">
        {{ loading ? 'Connexion...' : 'Se connecter' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.login-card { width: 360px; display: flex; flex-direction: column; gap: 14px; }
.accent { color: var(--accent); }
</style>
