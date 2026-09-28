import { describe, expect, it, vi } from 'vitest'
import { putStream, LecGapApiError } from './client'

/**
 * The upload path is XHR, not fetch, because fetch has no upload progress
 * event (§7). Two defects lived here and both were silent:
 *
 *   - `Content-Length` is a **forbidden header name**; setting it is ignored by
 *     browsers, so it was doing nothing at all.
 *   - An aborted request fires `onabort` and *neither* `onload` nor `onerror`.
 *     With no `onabort` handler the promise never settles, so the first person
 *     to wire an upload-cancel button would inherit a permanently pending
 *     promise and a `finally` that never runs.
 */

class FakeXhr {
  static last: FakeXhr | null = null

  status = 200
  responseText = '{"id":1}'
  upload: { onprogress?: (e: ProgressEvent) => void } = {}
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  headers: Record<string, string> = {}
  sent = false
  aborted = false

  constructor() {
    FakeXhr.last = this
  }

  open(_method: string, _url: string) {}
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  send() {
    this.sent = true
  }
  abort() {
    this.aborted = true
    this.onabort?.()
  }
  /** Simulate the browser firing an upload progress event. */
  progress(loaded: number, total: number | undefined) {
    this.upload.onprogress?.({
      loaded,
      total,
      lengthComputable: total !== undefined && total > 0,
    } as ProgressEvent)
  }
}

function withFakeXhr() {
  const original = globalThis.XMLHttpRequest
  globalThis.XMLHttpRequest = FakeXhr as unknown as typeof XMLHttpRequest
  return {
    last: () => FakeXhr.last!,
    restore: () => {
      globalThis.XMLHttpRequest = original
    },
  }
}

describe('putStream', () => {
  it('resolves on 2xx', async () => {
    const x = withFakeXhr()
    try {
      const p = putStream('/lectures/1/media', new Blob(['hi']), () => {})
      x.last().onload?.()
      await expect(p).resolves.toMatchObject({ id: 1 })
    } finally {
      x.restore()
    }
  })

  it('rejects with the backend detail on 4xx', async () => {
    const x = withFakeXhr()
    try {
      const p = putStream('/lectures/1/media', new Blob(['hi']), () => {})
      x.last().status = 409
      x.last().responseText = '{"detail":"must be uploaded"}'
      x.last().onload?.()
      await expect(p).rejects.toMatchObject({ status: 409, detail: 'must be uploaded' })
    } finally {
      x.restore()
    }
  })

  it('does not set Content-Length, which browsers forbid', () => {
    const x = withFakeXhr()
    try {
      void putStream('/lectures/1/media', new Blob(['hi']), () => {}).catch(() => {})
      expect(x.last().headers).not.toHaveProperty('Content-Length')
    } finally {
      x.restore()
    }
  })

  it('settles on abort instead of hanging forever', async () => {
    const x = withFakeXhr()
    try {
      const controller = new AbortController()
      const p = putStream('/lectures/1/media', new Blob(['hi']), () => {}, controller.signal)
      controller.abort()

      // The whole point: this must settle. Before the fix it stayed pending.
      await expect(p).rejects.toBeInstanceOf(LecGapApiError)
      expect(x.last().aborted).toBe(true)
    } finally {
      x.restore()
    }
  })

  it('rejects immediately if the signal is already aborted', async () => {
    const x = withFakeXhr()
    try {
      const controller = new AbortController()
      controller.abort()
      await expect(
        putStream('/lectures/1/media', new Blob(['hi']), () => {}, controller.signal),
      ).rejects.toBeInstanceOf(LecGapApiError)
      expect(x.last().sent).toBe(false)
    } finally {
      x.restore()
    }
  })

  it('reports a percentage when the total is known', () => {
    const x = withFakeXhr()
    try {
      const seen: number[] = []
      void putStream('/lectures/1/media', new Blob(['hi']), (p) => seen.push(p)).catch(() => {})
      x.last().progress(50, 100)
      expect(seen).toEqual([50])
    } finally {
      x.restore()
    }
  })

  it('does not report a bogus percentage when the total is unknown', () => {
    // lengthComputable is false for a File body in most browsers. Reporting
    // loaded/total with total=0 gives Infinity or NaN, which is worse than
    // simply not claiming progress.
    const x = withFakeXhr()
    try {
      const onProgress = vi.fn()
      void putStream('/lectures/1/media', new Blob(['hi']), onProgress).catch(() => {})
      x.last().progress(1234, undefined)
      expect(onProgress).not.toHaveBeenCalled()
    } finally {
      x.restore()
    }
  })
})
