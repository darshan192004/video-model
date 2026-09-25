<script setup lang="ts">
interface GalleryItem {
  id: number
  job_id: string
  kind: string
  filename: string
  size_bytes: number
  content_type: string
  file_url: string
  metadata_url: string
}

interface JobRow {
  job_id: string
  template_id: string
  params: Record<string, unknown>
  status: "queued" | "running" | "success" | "failed" | "cancelled"
  counts: Record<string, number | boolean>
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

interface JobDetail extends JobRow {
  gallery: GalleryItem[]
  cancel_requested: boolean
  progress: Record<string, number | boolean>
}

const route = useRoute()
const { get, post } = useApi()

const jobs = ref<JobRow[]>([])
const loadError = ref("")
const details = ref<Record<string, JobDetail>>({})
const expanded = ref<string | null>(null)
const highlight = ref<string | null>(
  typeof route.query.highlight === "string" ? (route.query.highlight as string) : null,
)

const ACTIVE = new Set(["queued", "running"])
const STATUS_PILL: Record<string, string> = {
  queued: "queued",
  running: "running",
  success: "success",
  failed: "failed",
  cancelled: "cancelled",
}

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

function progressPercent(job: JobRow): number | null {
  const counts = job.counts ?? {}
  const overall = counts.overall
  if (typeof overall !== "number") return null
  return Math.round(overall)
}

async function loadList(): Promise<void> {
  try {
    const data = await get<{ jobs: JobRow[] }>("/jobs")
    jobs.value = data.jobs
    if (highlight.value && !jobs.value.some((job) => job.job_id === highlight.value)) {
      void loadDetail(highlight.value)
    }
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

async function loadDetail(jobId: string): Promise<void> {
  try {
    details.value[jobId] = await get<JobDetail>(`/jobs/${jobId}`)
    if (!jobs.value.some((job) => job.job_id === jobId)) {
      jobs.value.unshift({ ...details.value[jobId] })
    }
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

async function toggle(jobId: string): Promise<void> {
  expanded.value = expanded.value === jobId ? null : jobId
  if (expanded.value === jobId) {
    await loadDetail(jobId)
  }
}

async function cancelJob(jobId: string): Promise<void> {
  try {
    await post(`/jobs/${jobId}/cancel`)
    await loadList()
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

let timer: ReturnType<typeof setInterval> | null = null

function visible(): boolean {
  return !document.hidden
}

onMounted(() => {
  void loadList()
  timer = setInterval(() => {
    if (visible()) void loadList()
  }, 4000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

onActivated(() => {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    if (visible()) void loadList()
  }, 4000)
})
</script>

<template>
  <div>
    <h1 class="page-title">Jobs</h1>
    <p class="page-sub">
      Your generation queue. Jobs run in submission order; refresh happens
      automatically while you watch.
    </p>

    <div v-if="loadError" class="error-banner" role="alert">{{ loadError }}</div>
    <div v-else-if="jobs.length === 0" class="empty">
      No jobs yet — start one from the templates page.
    </div>

    <div class="list">
      <article
        v-for="job in jobs"
        :key="job.job_id"
        class="card row"
        :class="{ 'highlight-row': highlight === job.job_id }"
      >
        <div style="min-width: 0">
          <p style="margin: 0 0 0.2rem">
            <strong>{{ job.template_id }}</strong>
            <span class="status-pill" :class="STATUS_PILL[job.status]">
              {{ statusLabel(job.status) }}
            </span>
            <span v-if="progressPercent(job) !== null" class="chip warn">
              {{ progressPercent(job) }}%
            </span>
          </p>
          <p style="margin: 0" class="help">
            <span class="mono">{{ job.job_id }}</span> · started
            {{ job.started_at ? new Date(job.started_at).toLocaleString() : "not yet" }}
          </p>
        </div>
        <div style="display: flex; gap: 0.5rem; flex-shrink: 0">
          <button type="button" @click="toggle(job.job_id)">
            {{ expanded === job.job_id ? "Details" : "Details" }}
          </button>
          <button
            v-if="ACTIVE.has(job.status)"
            type="button"
            class="danger"
            @click="cancelJob(job.job_id)"
          >
            Cancel
          </button>
        </div>
      </article>
    </div>

    <section
      v-if="expanded && details[expanded]"
      class="card"
      style="margin-top: 1rem"
      :aria-label="`Details for job ${expanded}`"
    >
      <h2>Job details</h2>
      <dl v-if="details[expanded]">
        <div>
          <dt>Status</dt>
          <dd>{{ statusLabel(details[expanded]!.status) }}</dd>
        </div>
        <div v-if="details[expanded]!.error">
          <dt>Error</dt>
          <dd style="color: var(--bad)">{{ details[expanded]!.error }}</dd>
        </div>
        <div>
          <dt>Parameters</dt>
          <dd><pre class="mono">{{ JSON.stringify(details[expanded]!.params, null, 2) }}</pre></dd>
        </div>
        <div>
          <dt>Progress</dt>
          <dd><pre class="mono">{{ JSON.stringify(details[expanded]!.progress, null, 2) }}</pre></dd>
        </div>
      </dl>

      <div v-if="details[expanded]!.gallery.length" class="gallery-grid">
        <figure v-for="item in details[expanded]!.gallery" :key="item.id" class="gallery-item">
          <img v-if="item.kind === 'image'" :src="item.file_url" :alt="item.filename" />
          <video v-else :src="item.file_url" controls preload="metadata" :aria-label="item.filename" />
          <figcaption class="meta">
            <a :href="item.file_url" target="_blank" rel="noopener">Open {{ item.filename }}</a>
          </figcaption>
        </figure>
      </div>
    </section>
  </div>
</template>

<style scoped>
.highlight-row {
  border-color: var(--accent);
}

dt {
  color: var(--text-dim);
  font-size: 0.82rem;
  margin-top: 0.5rem;
}

dd {
  margin: 0 0 0 0;
}
</style>