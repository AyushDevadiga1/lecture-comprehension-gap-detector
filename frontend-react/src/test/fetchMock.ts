import { vi } from 'vitest'

/**
 * A route table for `fetch`, so a test states exactly what the backend returns.
 *
 * Why not just `vi.stubGlobal('fetch', vi.fn())`: an unstubbed request would
 * either hit jsdom's origin for real or hang, and the failure surfaces as a
 * timeout in a test about something else. Here an unmatched request throws
 * immediately, naming the route, so "the app called something the test forgot
 * to stub" is legible in the failure rather than a mystery.
 */

export interface MockRoute {
  /** Defaults to GET. */
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  /** Matched against the pathname only; the origin is jsdom's, not ours. */
  path: string | RegExp
  /** HTTP status. Defaults to 200. */
  status?: number
  /** JSON response body. */
  json?: unknown
  /**
   * For the streaming upload (PUT /lectures/{id}/media), which the client
   * performs with XMLHttpRequest and therefore never reaches `fetch`.
   */
  text?: string
}

export interface RecordedCall {
  method: string
  /** Full request URL as the client built it. */
  url: string
  /** Pathname only. */
  path: string
  headers: Record<string, string>
  body: unknown
}

export interface FetchMock {
  /** Every call made, in order. */
  calls: RecordedCall[]
  /** Calls matching a method + path, for "was this invalidated / refetched?". */
  callsTo(method: string, path: string | RegExp): RecordedCall[]
  restore(): void
}

const headerRecord = (init?: HeadersInit): Record<string, string> => {
  const out: Record<string, string> = {}
  new Headers(init).forEach((value, key) => {
    out[key] = value
  })
  return out
}

export function mockFetch(routes: MockRoute[]): FetchMock {
  const calls: RecordedCall[] = []
  const original = globalThis.fetch

  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const url = new URL(rawUrl, 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()

    let parsedBody: unknown = init?.body
    if (typeof init?.body === 'string') {
      try {
        parsedBody = JSON.parse(init.body)
      } catch {
        /* leave as the raw string — multipart/FormData is not JSON */
      }
    }

    calls.push({ method, url: rawUrl, path: url.pathname, headers: headerRecord(init?.headers), body: parsedBody })

    const match = routes.find(
      (r) => (r.method ?? 'GET') === method && (typeof r.path === 'string' ? url.pathname === r.path : r.path.test(url.pathname)),
    )

    if (!match) {
      throw new Error(
        `mockFetch: no route for ${method} ${url.pathname}. ` +
          `Registered: ${routes.map((r) => `${r.method ?? 'GET'} ${r.path}`).join(', ') || '(none)'}`,
      )
    }

    return new Response(match.text ?? JSON.stringify(match.json ?? null), {
      status: match.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  vi.stubGlobal('fetch', impl)

  return {
    calls,
    callsTo: (method, path) =>
      calls.filter(
        (c) =>
          c.method === method.toUpperCase() &&
          (typeof path === 'string' ? c.path === path : path.test(c.path)),
      ),
    restore: () => {
      vi.stubGlobal('fetch', original)
    },
  }
}
