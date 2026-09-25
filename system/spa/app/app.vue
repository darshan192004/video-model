<script setup lang="ts">
const { loading, me, isAdmin, refresh, login, logout } = useAuthStore()
const route = useRoute()
const isLogin = computed(() => route.path === "/login")

onMounted(() => {
  void refresh()
})

const navItems = computed(() => [
  { to: "/templates", label: "Templates" },
  { to: "/jobs", label: "Jobs" },
  { to: "/gallery", label: "Gallery" },
  ...(isAdmin.value ? [{ to: "/admin", label: "Admin" }] : []),
])
</script>

<template>
  <div>
    <header v-if="me" class="topbar">
      <span class="brand">Media Studio</span>
      <nav aria-label="Primary">
        <NuxtLink v-for="item in navItems" :key="item.to" :to="item.to">
          {{ item.label }}
        </NuxtLink>
      </nav>
      <div class="account">
        <span class="email">{{ me.email }}</span>
        <span v-if="isAdmin" class="chip ok">admin</span>
        <button type="button" @click="logout">Sign out</button>
      </div>
    </header>
    <main class="content">
      <div v-if="loading" class="centered">
        <span class="spinner" aria-hidden="true"></span>
        <p>Loading session…</p>
      </div>
      <NuxtPage v-else />
    </main>
  </div>
</template>