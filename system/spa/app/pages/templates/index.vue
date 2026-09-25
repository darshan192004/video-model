<script setup lang="ts">
interface ParamSpec {
  type: "int" | "float" | "bool" | "string" | "image" | "enum"
  label: string
  required?: boolean
  default?: unknown
  min?: number
  max?: number
  step?: number
  values?: unknown[]
}

interface Template {
  id: string
  display: string
  workflow: string
  params: Record<string, ParamSpec>
}

const { get, post, upload } = useApi()
const list = ref<Template[]>([])
const loadError = ref("")
const openId = ref<string | null>(null)
const schema = ref<Template | null>(null)
const form = ref<Record<string, any>>({})
const enumIndex = ref<Record<string, number>>({})
const formError = ref("")
const busy = ref(false)

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function prepareForm(template: Template): void {
  const next: Record<string, any> = {}
  const indexes: Record<string, number> = {}
  for (const [name, parameter] of Object.entries(template.params)) {
    next[name] = parameter.default
    if (parameter.type === "enum") {
      const values = parameter.values ?? []
      const found = values.findIndex((value) => sameValue(value, parameter.default))
      indexes[name] = found >= 0 ? found : 0
      next[name] = values[indexes[name]]
    }
  }
  form.value = next
  enumIndex.value = indexes
}

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
    prepareForm(schema.value)
  } catch (error) {
    formError.value = (error as Error).message
  }
}

function onEnum(name: string, event: Event): void {
  const input = event.target as HTMLSelectElement
  const index = Number(input.value)
  enumIndex.value[name] = index
  const values = schema.value?.params[name]?.values ?? []
  form.value[name] = values[index]
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
    for (const [name, parameter] of Object.entries(schema.value.params)) {
      const value = form.value[name]
      if (value === undefined || value === null || value === "") {
        if (parameter.required) {
          throw new Error(`Parameter "${parameter.label}" is required`)
        }
        continue
      }
      params[name] = value
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
        <h2>{{ template.display }}</h2>
        <p>
          <span class="chip dim">{{ template.id }}</span>
          <span class="chip dim">{{ template.workflow }}</span>
        </p>
        <button type="button" class="primary" @click="toggle(template)">
          {{ openId === template.id ? "Close" : "Configure" }}
        </button>

        <form v-if="openId === template.id && schema" @submit.prevent="submit">
          <h3>Parameters</h3>
          <div v-if="formError" class="error-banner" role="alert">{{ formError }}</div>

          <div
            v-for="(parameter, name) in schema.params"
            :key="name"
            class="field"
          >
            <label :for="`p-${name}`">
              <span>{{ parameter.label }}<span v-if="parameter.required" class="req">*</span></span>
            </label>

            <template v-if="parameter.type === 'enum'">
              <select
                :id="`p-${name}`"
                :value="enumIndex[name]"
                @change="onEnum(name, $event)"
              >
                <option v-for="(value, index) in (parameter.values ?? [])" :key="index" :value="index">
                  {{ Array.isArray(value) ? `${value[0]} x ${value[1]}` : String(value) }}
                </option>
              </select>
              <span class="value">selected: {{ form[name] }}</span>
            </template>

            <template v-else-if="parameter.type === 'bool'">
              <input
                :id="`p-${name}`"
                type="checkbox"
                v-model="form[name]"
              />
            </template>

            <template v-else-if="parameter.type === 'int' || parameter.type === 'float'">
              <input
                :id="`p-${name}`"
                type="number"
                v-model.number="form[name]"
                :min="parameter.min"
                :max="parameter.max"
                :step="parameter.type === 'int' ? 1 : parameter.step"
              />
              <input
                type="range"
                v-model.number="form[name]"
                :min="parameter.min"
                :max="parameter.max"
                :step="parameter.type === 'int' ? 1 : parameter.step"
              />
              <span class="value">current: {{ form[name] }}</span>
            </template>

            <template v-else-if="parameter.type === 'string'">
              <input
                :id="`p-${name}`"
                type="text"
                v-model="form[name]"
              />
            </template>

            <template v-else-if="parameter.type === 'image'">
              <input
                :id="`p-${name}`"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                @change="onFile(name, $event)"
              />
              <p v-if="form[name]" class="preview">
                <img
                  :src="form[name] as string"
                  alt="Selected input image"
                  style="max-width: 180px; display: block; border-radius: 8px"
                />
                <button type="button" @click="form[name] = null">
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