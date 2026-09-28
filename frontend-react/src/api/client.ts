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

/**
 * Human-readable message from anything thrown by this module (or by a
 * component's own guard). Accepts `unknown` so a `catch (err)` needs no cast:
 * a `LecGapApiError` surfaces its `detail` — the backend's `{detail}` envelope,
 * never a traceback — and anything else degrades to the caller's fallback.
 */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof LecGapApiError) return err.detail
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra)
  if (!h.has('Accept')) h.set('Accept', 'application/json')
  if (API_KEY) h.set('X-API-Key', API_KEY)
  return h
}

/**
 * Auth headers for an out-of-band request that does not go through the JSON
 * verbs — currently only the `/jobs/stream` SSE feed, which needs a streaming
 * `fetch` rather than `get()`.
 *
 * This exists because the key must be injected in exactly one place (§6). Note
 * why the feed cannot use `EventSource`: that constructor has no header API at
 * all, so a key-guarded backend 401s the stream and the feed dies silently for
 * the life of the tab.
 */
export function streamHeaders(): Headers {
  return headers({ Accept: 'text/event-stream' })
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

/** Build an absolute URL with a query string, skipping undefined values. */
function url(path: string, params?: Record<string, string | number | boolean | undefined>): string {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v))
    })
  }
  return url.toString()
}

export async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const res = await fetch(url(path, params), { headers: headers() })
  return handleResponse<T>(res)
}

/**
 * `params` is carried in the query string, not the body: the backend declares
 * `lecture_id` as a query parameter on `POST /courses/{id}/graph`
 * (`backend/api/routes/courses.py:182`), and a JSON body would be ignored.
 */
export async function post<T>(
  path: string,
  body?: unknown,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const res = await fetch(url(path, params), {
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
 *
 * Two details that are easy to get wrong and were both wrong here:
 *   - `Content-Length` is a **forbidden header name**. Setting it is silently
 *     ignored by browsers, so it was doing nothing. The browser sets it itself
 *     from the Blob; the backend requires it to be present on the request.
 *   - An aborted request fires `onabort` and *neither* `onload` nor `onerror`, so
 *     without an `onabort` handler the promise never settles and the caller's
 *     `finally` never runs — an upload-cancel button would hang forever.
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

    let settled = false
    const done = (fn: () => void) => {
      if (settled) return
      settled = true
      signal?.removeEventListener('abort', onAbort)
      fn()
    }

    xhr.upload.onprogress = (e) => {
      // lengthComputable is false for a File body in most browsers; without a
      // total there is no honest percentage, so report loaded bytes as progress
      // rather than freezing the bar at a stale value.
      if (e.lengthComputable && e.total > 0) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        done(() => resolve(JSON.parse(xhr.responseText) as LectureOutRaw))
      } else {
        let detail = `HTTP ${xhr.status}`
        try {
          const b = JSON.parse(xhr.responseText) as ApiError
          if (typeof b.detail === 'string') detail = b.detail
        } catch {
          /* empty */
        }
        done(() => reject(new LecGapApiError(xhr.status, detail)))
      }
    }
    xhr.onerror = () => done(() => reject(new LecGapApiError(0, 'Network error')))
    // The settle path an abort takes. Without this the promise never resolves.
    xhr.onabort = () => done(() => reject(new LecGapApiError(0, 'Upload cancelled')))

    const onAbort = () => xhr.abort()
    if (signal) {
      if (signal.aborted) {
        done(() => reject(new LecGapApiError(0, 'Upload cancelled')))
        return
      }
      signal.addEventListener('abort', onAbort)
    }
    xhr.send(body)
  })
}

// Minimal inline type to avoid a circular import from types.ts:
type LectureOutRaw = import('./types').LectureOut
