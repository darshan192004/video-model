// Thin typed wrapper around the control-plane REST API.
//
// - Sends cookies (credentials: 'include') for the server-side media_sid.
// - Echoes the media_csrf cookie value in the X-CSRF header for every
//   mutating request (CSRF tokens are shared via a readable cookie).
// - Flattens FastAPI error bodies into ApiError with .status + .detail.
// - Redirects to the SSO start screen when a non-silenced request hits 401
//   (the session expired mid-use), except /auth/* which handles auth itself.

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  form?: FormData
  silent401?: boolean
}

function csrfToken(): string {
  const prefix = "media_csrf="
  const cookie = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(prefix))
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : ""
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? (options.body !== undefined || options.form ? "POST" : "GET")
  const headers: Record<string, string> = { Accept: "application/json" }
  if (options.body !== undefined) headers["Content-Type"] = "application/json"
  if (method !== "GET" && method !== "HEAD") {
    const token = csrfToken()
    if (token) headers["X-CSRF"] = token
  }
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : options.form,
    credentials: "include",
  })
  if (response.status === 401 && !options.silent401 && !path.startsWith("/auth")) {
    window.location.assign("/api/auth/start")
    throw new ApiError(401, "session expired")
  }
  const contentType = response.headers.get("content-type") ?? ""
  const payload: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text()
  if (!response.ok) {
    const detail =
      typeof payload === "string"
        ? payload
        : (payload as { detail?: unknown })?.detail ?? JSON.stringify(payload)
    throw new ApiError(response.status, String(detail))
  }
  return payload as T
}

export const api = {
  get: <T>(path: string, silent401 = false) => request<T>(path, { silent401 }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { form }),
}

export function useApi() {
  return api
}