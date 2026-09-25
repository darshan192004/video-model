<script setup lang="ts">
const { me, loading, login } = useAuthStore()
</script>

<template>
  <section class="centered">
    <div class="card" style="max-width: 420px; width: 100%">
      <h1 style="margin-top: 0">Media Studio</h1>
      <p>
        Self-hosted image and video generation. Sign in with your
        organizational account to continue.
      </p>
      <p v-if="loading">
        <span class="spinner" aria-hidden="true"></span>
        Checking your session…
      </p>
      <button v-else-if="me" type="button" class="primary" style="width: 100%" @click="login">
        Continue to the studio
      </button>
      <button v-else type="button" class="primary" style="width: 100%" @click="login">
        Sign in via organizational SSO
      </button>
      <p class="help" style="color: var(--text-dim); font-size: 0.85rem; margin-bottom: 0">
        You will be redirected to your identity provider and back to this
        studio afterwards.
      </p>
    </div>
  </section>
</template>