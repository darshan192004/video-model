<script setup lang="ts">
interface ParamSpec {
  name: string
  type: "int" | "float" | "bool" | "string" | "image"
  default?: unknown
  min?: number
  max?: number
  step?: number
  help?: string
}

interface Template {
  id: string
  name: string
  description: string
  kind: string
  version: string
  params: ParamSpec[]
}

const { get, post, upload } = useApi()
const list = ref<Template[]>([])
const loadError = ref("")
const openId = ref<string | null>(null)
const schema = ref<Template | null>(null)
const form = ref<Record<string, any>>({})
const formError = ref("")
const busy = ref(false)

async function load(): Promise<void> {
  try {
    const data = await get<{ templates: Template[] }>("/templates")
    list.value = data.templates
  } catch (error) {
    loadError.value = (error as Error).message
  }
}

onMounted(() => {
  void load()
})

async function toggle(template: Template): Promise<void> {
  if (openId.value === template.id) {
    openId.value = null
    return
  }
  openId.value = template.id
  formError.value = ""
  try {
    schema.value = await get<Template>(`/templates/${template.id}/schema`)
    form.value = {}
    for (const parameter of schema.value?.params ?? []) {
      form.value[parameter.name] = parameter.default
    }
  } catch (error) {
    formError.value = (error as Error).message
  }
}

async function onFile(paramName: string, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append("file", file)
  try {
    const result = await upload<{ url_path: string }>("/uploads/pre", fd)
    form.value[paramName] = result.url_path
  } catch (error) {
    formError.value = (error as Error).message
  }
}

async function submit(): Promise<void> {
  if (!schema.value) return
  formError.value = ""
  busy.value = true
  try {
    const params: Record<string, unknown> = {}
    for (const parameter of schema.value.params) {
      const value = form.value[parameter.name]
      if (value === undefined || value === null || value === "") continue
      params[parameter.name] = value
    }
    const result = await post<{ job_id: string }>("/jobs", {
      template_id: schema.value.id,
      params,
    })
    await navigateTo(`/jobs?highlight=${result.job_id}`)
  } catch (error) {
    formError.value = (error as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">Templates</h1>
    <p class="page-sub">
      Choose a workflow, tune its parameters, and submit a generation job.
    </p>

    <div v-if="loadError" class="error-banner" role="alert">{{ loadError }}</div>
    <div v-else-if="list.length === 0" class="empty">No templates available.</div>

    <div class="grid">
      <article v-for="template in list" :key="template.id" class="card">
        <h2>{{ template.name }}</h2>
        <p>{{ template.description }}</p>
        <p>
          <span class="chip dim">kind: {{ template.kind }}</span>
          <span class="chip dim">v{{ template.version }}</span>
        </p>
        <button type="button" class="primary" @click="toggle(template)">
          {{ openId === template.id ? "Close" : "Configure" }}
        </button>

        <form v-if="openId === template.id && schema" @submit.prevent="submit">
          <h3>Parameters</h3>
          <div v-if="formError" class="error-banner" role="alert">{{ formError }}</div>

          <div v-for="parameter in schema.params" :key="parameter.name" class="field">
            <label :for="`p-${parameter.name}`">
              <span>{{ parameter.name }}</span>
              <span class="help">{{ parameter.help }}</span>
            </label>

            <template v-if="parameter.type === 'bool'">
              <input
                :id="`p-${parameter.name}`"
                type="checkbox"
                v-model="form[parameter.name]"
              />
            </template>

            <template v-else-if="parameter.type === 'int' || parameter.type === 'float'">
              <input
                :id="`p-${parameter.name}`"
                type="number"
                v-model.number="form[parameter.name]"
                :min="parameter.min"
                :max="parameter.max"
                :step="parameter.type === 'int' ? 1 : parameter.step"
              />
              <input
                type="range"
                v-model.number="form[parameter.name]"
                :min="parameter.min"
                :max="parameter.max"
                :step="parameter.type === 'int' ? 1 : parameter.step"
              />
              <span class="value">current: {{ form[parameter.name] }}</span>
            </template>

            <template v-else-if="parameter.type === 'string'">
              <input
                :id="`p-${parameter.name}`"
                type="text"
                v-model="form[parameter.name]"
              />
            </template>

            <template v-else-if="parameter.type === 'image'">
              <input
                :id="`p-${parameter.name}`"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                @change="onFile(parameter.name, $event)"
              />
              <p v-if="form[parameter.name]" class="preview">
                <img
                  :src="form[parameter.name] as string"
                  alt="Selected input image"
                  style="max-width: 180px; display: block; border-radius: 8px"
                />
                <button type="button" @click="form[parameter.name] = null">
                  Remove image
                </button>
              </p>
            </template>
          </div>

          <button type="submit" class="primary" :disabled="busy">
            {{ busy ? "Submitting…" : "Submit job" }}
          </button>
        </form>
      </article>
    </div>
  </div>
</template>