<script setup lang="ts">
interface SystemInfo {
  versions: { app: string; uvicorn: string; fastapi: string }
  queue_depth: number
  worker: { status: string; running_jobs: number }
  storage: { free_bytes: number; total_bytes: number; used_bytes: number }
}

interface UserRow {
  id: number
  subject: string
  name: string | null
  email: string
  groups: string[]
  is_admin: boolean
  created_at: string
}

interface RawJob {
  job_id: string
  template_id: string
  status: string
  workflow: Record<string, unknown>
  params: Record<string, unknown>
  counts: Record<string, unknown>
}

const { isAdmin } = useAuthStore()
const { get, post } = useApi()

const system = ref<SystemInfo | null>(null)
const users = ref<UserRow[]>([])
const rawJob = ref<RawJob | null>(null)
const rawJobInput = ref("")
const moderationUser = ref<number | null>(null)
const moderationItems = ref<{ id: number; filename: string; kind: string }[]>([])
const error = ref("")
const notice = ref("")

function formatBytes(bytes: number): string {
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

async function loadSystem(): Promise<void> {
  error.value = ""
  try {
    system.value = await get<SystemInfo>("/admin/system")
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function loadUsers(): Promise<void> {
  error.value = ""
  try {
    const data = await get<{ users: UserRow[] }>("/admin/users")
    users.value = data.users
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function fetchRawJob(): Promise<void> {
  error.value = ""
  rawJob.value = null
  if (!rawJobInput.value.trim()) return
  try {
    rawJob.value = await get<RawJob>(`/admin/jobs/${rawJobInput.value.trim()}/raw`)
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function loadModeration(): Promise<void> {
  error.value = ""
  moderationItems.value = []
  if (moderationUser.value === null) return
  try {
    const data = await get<{
      items: { id: number; filename: string; kind: string }[]
    }>(`/gallery?user=${moderationUser.value}`)
    moderationItems.value = data.items
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function moderateDelete(mediaId: number): Promise<void> {
  error.value = ""
  if (!window.confirm(`Moderator-delete gallery item ${mediaId}?`)) return
  try {
    await post(`/admin/gallery/${mediaId}/delete`)
    notice.value = `Deleted gallery item ${mediaId}.`
    await loadModeration()
  } catch (err) {
    error.value = (err as Error).message
  }
}

onMounted(() => {
  if (isAdmin.value) {
    void loadSystem()
    void loadUsers()
  }
})
</script>

<template>
  <div v-if="!isAdmin" class="centered">
    <h1>Forbidden</h1>
    <p>This panel is limited to administrators.</p>
  </div>

  <div v-else>
    <h1 class="page-title">Administration</h1>
    <p class="page-sub">System health, users, and moderation tools.</p>

    <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
    <div v-if="notice" class="notice" role="status">{{ notice }}</div>

    <div class="admin-grid">
      <section class="card">
        <h2>System</h2>
        <button type="button" class="primary" @click="loadSystem">Refresh</button>
        <dl v-if="system">
          <div>
            <dt>App version</dt>
            <dd>{{ system.versions.app }} (FastAPI {{ system.versions.fastapi }}, uvicorn {{ system.versions.uvicorn }})</dd>
          </div>
          <div>
            <dt>Queue</dt>
            <dd>{{ system.queue_depth }} queued · {{ system.worker.running_jobs }} running (worker: {{ system.worker.status }})</dd>
          </div>
          <div>
            <dt>Storage</dt>
            <dd>{{ formatBytes(system.storage.free_bytes) }} free of {{ formatBytes(system.storage.total_bytes) }}</dd>
          </div>
        </dl>
      </section>

      <section class="card">
        <h2>Raw job</h2>
        <form class="field" @submit.prevent="fetchRawJob">
          <label for="raw-job">Job ID</label>
          <input
            id="raw-job"
            v-model="rawJobInput"
            type="text"
            placeholder="00000000-0000-0000-0000-000000000000"
          />
          <button type="submit" class="primary" style="margin-top: 0.5rem">Fetch</button>
        </form>
        <pre v-if="rawJob" class="mono">{{ JSON.stringify(rawJob, null, 2) }}</pre>
      </section>

      <section class="card">
        <h2>Users</h2>
        <button type="button" class="primary" @click="loadUsers">Refresh</button>
        <table>
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Name</th>
              <th scope="col">Admin</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.email }}</td>
              <td>{{ user.name ?? "—" }}</td>
              <td>{{ user.is_admin ? "yes" : "no" }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card">
        <h2>Moderation</h2>
        <form class="field" @submit.prevent="loadModeration">
          <label for="mod-user">User id</label>
          <input id="mod-user" v-model.number="moderationUser" type="number" min="0" />
          <button type="submit" class="primary" style="margin-top: 0.5rem">List gallery</button>
        </form>
        <ul v-if="moderationItems.length" class="list">
          <li v-for="item in moderationItems" :key="item.id" class="row">
            <span>{{ item.filename }}</span>
            <button type="button" class="danger" @click="moderateDelete(item.id)">
              Delete
            </button>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
dt {
  color: var(--text-dim);
  font-size: 0.82rem;
  margin-top: 0.5rem;
}

dd {
  margin: 0;
}

table {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.9rem;
}

th,
td {
  text-align: left;
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--border);
}

th {
  color: var(--text-dim);
  font-weight: 600;
}

.notice {
  border: 1px solid var(--ok);
  color: var(--ok);
  background: rgba(52, 211, 153, 0.08);
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  margin: 0 0 0.9rem;
}
</style>