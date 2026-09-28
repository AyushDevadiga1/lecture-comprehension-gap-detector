/**
 * Thin HTTP client — the ONLY place in the codebase that calls fetch().
 *
 * Rules (from REACT_ARCHITECTURE.md §6):
 *   - All domain wrappers (courses.ts, lectures.ts, jobs.ts, quiz.ts) import
 *     from here; feature components NEVER call fetch directly.
 *   - X-API-Key header is injected here, once, from VITE_LECGAP_API_KEY.
 *   - 401 is extracted here and re-thrown as a typed ApiError so one banner
 *     covers it everywhere — never a silent "no courses" state.
 *   - {detail} envelope is always extracted, never a raw stacktrace.
 */

import type { ApiError } from './types'

const API_KEY = import.meta.env.VITE_LECGAP_API_KEY as string | undefined

/** Base URL for the backend — defaults to '' (same-origin via Vite proxy). */
const BASE = (import.meta.env.VITE_LECGAP_API_URL as string | undefined) ?? ''

export class LecGapApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'LecGapApiError'
  }
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra)
  h.set('Accept', 'application/json')
  if (API_KEY) h.set('X-API-Key', API_KEY)
  return h
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.ok) {
    // 204 No Content
    if (res.status === 204) return undefined as unknown as T
    return res.json() as Promise<T>
  }

  let detail = `HTTP ${res.status}`
  try {
    const body = (await res.json()) as ApiError
    if (typeof body.detail === 'string') {
      detail = body.detail
    } else if (Array.isArray(body.detail)) {
      detail = body.detail.map((e) => `${e.loc.join('.')}: ${e.msg}`).join('; ')
    }
  } catch {
    // body was not JSON — use status text
    detail = res.statusText || detail
  }
  throw new LecGapApiError(res.status, detail)
}

export async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString(), { headers: headers() })
  return handleResponse<T>(res)
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return handleResponse<T>(res)
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  // Let the browser set Content-Type (with boundary)
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: headers(),
    body: form,
  })
  return handleResponse<T>(res)
}

export async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    headers: headers(),
  })
  return handleResponse<T>(res)
}

/**
 * XHR-based PUT for streaming uploads with real progress events.
 * fetch() has no upload.onprogress — this is intentional per REACT_ARCHITECTURE.md §7.
 */
export function putStream(
  path: string,
  body: Blob | File,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<LectureOutRaw> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `${BASE}${path}`)
    if (API_KEY) xhr.setRequestHeader('X-API-Key', API_KEY)
    xhr.setRequestHeader('Content-Length', String(body.size))

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as LectureOutRaw)
      } else {
        let detail = `HTTP ${xhr.status}`
        try {
          const b = JSON.parse(xhr.responseText) as ApiError
          if (typeof b.detail === 'string') detail = b.detail
        } catch { /* empty */ }
        reject(new LecGapApiError(xhr.status, detail))
      }
    }
    xhr.onerror = () => reject(new LecGapApiError(0, 'Network error'))
    if (signal) signal.addEventListener('abort', () => xhr.abort())
    xhr.send(body)
  })
}

// Minimal inline type to avoid a circular import from types.ts:
type LectureOutRaw = import('./types').LectureOut
