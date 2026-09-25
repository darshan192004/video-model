<script setup lang="ts">
interface GalleryItem {
  id: number
  job_id: string
  kind: string
  filename: string
  size_bytes: number
  content_type: string
  sha256: string
  created_at: string
  file_url: string
  metadata_url: string
}

const { get, del } = useApi()
const items = ref<GalleryItem[]>([])
const loadError = ref("")
const selected = ref<GalleryItem | null>(null)

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

async function load(): Promise<void> {
  try {
    const data = await get<{ items: GalleryItem[] }>("/gallery")
    items.value = data.items
    if (
      selected.value &&
      !items.value.some((item) => item.id === selected.value!.id)
    ) {
      selected.value = null
    }
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

async function remove(item: GalleryItem): Promise<void> {
  if (
    !window.confirm(
      `Remove ${item.filename} and every file from job ${item.job_id}?`,
    )
  ) {
    return
  }
  try {
    await del<{ deleted: boolean }>(`/gallery/${item.id}`)
    if (selected.value?.id === item.id) selected.value = null
    await load()
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <h1 class="page-title">Gallery</h1>
    <p class="page-sub">Your generated media. Files are public to you.</p>

    <div v-if="loadError" class="error-banner" role="alert">{{ loadError }}</div>
    <div v-else-if="items.length === 0" class="empty">
      Nothing here yet — generated files appear as their jobs finish.
    </div>

    <div class="gallery-grid">
      <article
        v-for="item in items"
        :key="item.id"
        class="gallery-item"
        @click="selected = item"
      >
        <img
          v-if="item.kind === 'image'"
          :src="item.file_url"
          :alt="item.filename"
        />
        <video
          v-else
          :src="item.file_url"
          controls
          preload="metadata"
          :aria-label="item.filename"
        />
        <div class="actions">
          <a :href="item.file_url" target="_blank" rel="noopener">Open</a>
          <a :href="item.file_url" :download="item.filename">Download</a>
          <button type="button" class="danger" @click.stop="remove(item)">
            Delete
          </button>
        </div>
        <p class="meta">{{ item.kind }} · {{ formatBytes(item.size_bytes) }}</p>
      </article>
    </div>

    <aside v-if="selected" class="card" style="margin-top: 1rem" aria-label="File details">
      <h2>{{ selected.filename }}</h2>
      <dl>
        <div>
          <dt>Kind</dt>
          <dd>{{ selected.kind }}</dd>
        </div>
        <div>
          <dt>Content type</dt>
          <dd>{{ selected.content_type }}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd>{{ formatBytes(selected.size_bytes) }}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{{ selected.created_at }}</dd>
        </div>
        <div>
          <dt>SHA-256</dt>
          <dd><span class="mono">{{ selected.sha256 }}</span></dd>
        </div>
        <div>
          <dt>Job</dt>
          <dd><span class="mono">{{ selected.job_id }}</span></dd>
        </div>
      </dl>
    </aside>
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
</style>