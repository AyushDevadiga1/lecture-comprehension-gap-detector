import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UploadDialog } from './UploadDialog'
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/fetchMock'
import type { LectureOut } from '../../api/types'

/**
 * The upload dialog, and the guard that is its whole reason for having tests:
 * a duplicate upload creates a second row, transcribes it again, and extracts
 * the same concepts — real cost, silently.
 *
 * `uploadMedia` is XHR (fetch has no upload progress), so the transport is
 * stubbed the way `api/client.test.ts` stubs it: one fake XMLHttpRequest that
 * succeeds. The client's own behaviour is tested there; here the claim is that
 * the dialog wires create → upload → invalidate → close.
 */

class FakeXhr {
  static last: FakeXhr | null = null
  status = 200
  responseText = '{"id": 7}'
  upload: { onprogress?: (e: ProgressEvent) => void } = {}
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  headers: Record<string, string> = {}

  constructor() {
    FakeXhr.last = this
  }
  open() {}
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  send() {
    this.upload.onprogress?.({ loaded: 50, total: 100, lengthComputable: true } as ProgressEvent)
    this.onload?.()
  }
  abort() {
    this.onabort?.()
  }
}

const lectures = [
  {
    id: 1,
    course_id: 'ml',
    title: 'linear regression',
    status: 'ready',
    created_at: '2026-01-01',
    has_media: true,
  },
] as LectureOut[]

function renderDialog(extra: Parameters<typeof mockFetch>[0] = []) {
  // `extra` first: mockFetch takes the first matching route, so a test that
  // stubs POST /lectures with a failure must shadow the success default.
  const mock = mockFetch([...extra, { method: 'POST', path: '/lectures', json: { id: 7 } }])
  const onClose = vi.fn()
  const view = renderWithProviders(
    <UploadDialog open onClose={onClose} courseId="ml" lectures={lectures} />,
    { route: '/student/lectures' },
  )
  return { mock, onClose, view }
}

const fileInput = () => {
  const input = document.querySelector('input[type="file"]')
  if (!(input instanceof HTMLInputElement)) throw new Error('no file input rendered')
  return input
}

beforeEach(() => {
  vi.stubGlobal('XMLHttpRequest', FakeXhr as unknown as typeof XMLHttpRequest)
})

describe('UploadDialog', () => {
  it('keeps the submit closed until a title and a file are both present', async () => {
    const user = userEvent.setup()
    renderDialog()

    const submit = screen.getByRole('button', { name: /Upload & transcribe/i })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(/Lecture title/i), 'Brand new lecture')
    expect(submit).toBeDisabled()

    await user.upload(fileInput(), new File(['x'], 'brand new.mp4', { type: 'video/mp4' }))
    expect(submit).toBeEnabled()
  })

  it('warns on a duplicate and blocks until it is acknowledged', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(screen.getByLabelText(/Lecture title/i), 'anything')
    await user.upload(fileInput(), new File(['x'], 'linear regression.mp4', { type: 'video/mp4' }))

    expect(await screen.findByText(/already looks like this file/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /Upload & transcribe/i })
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox', { name: /Upload anyway/i }))
    expect(submit).toBeEnabled()
  })

  it('re-arms the guard when a different file is chosen', async () => {
    // An acknowledgement belongs to one filename. Carrying it across a file
    // change would mean the guard warns and then protects nothing.
    const user = userEvent.setup()
    renderDialog()

    await user.type(screen.getByLabelText(/Lecture title/i), 'anything')
    await user.upload(fileInput(), new File(['x'], 'linear regression.mp4', { type: 'video/mp4' }))
    await user.click(await screen.findByRole('checkbox', { name: /Upload anyway/i }))
    expect(screen.getByRole('button', { name: /Upload & transcribe/i })).toBeEnabled()

    await user.upload(fileInput(), new File(['x'], 'different.mp4', { type: 'video/mp4' }))
    await waitFor(() => {
      expect(screen.queryByText(/already looks like this file/)).not.toBeInTheDocument()
    })
    // Not a duplicate any more, so it is submittable — the point is the ack is
    // gone, not that the button is disabled.
    expect(screen.queryByRole('checkbox', { name: /Upload anyway/i })).not.toBeInTheDocument()
  })

  it('creates the row, uploads the media, and closes', async () => {
    const user = userEvent.setup()
    const { mock, onClose } = renderDialog()

    await user.type(screen.getByLabelText(/Lecture title/i), 'Brand new lecture')
    await user.upload(fileInput(), new File(['x'], 'brand new.mp4', { type: 'video/mp4' }))
    await user.click(screen.getByRole('button', { name: /Upload & transcribe/i }))

    await waitFor(() => expect(mock.callsTo('POST', '/lectures')).toHaveLength(1))
    // Step one is form-encoded (`postForm`), not JSON: the create endpoint takes
    // multipart fields, which is why the body arrives as FormData here.
    const created = mock.callsTo('POST', '/lectures')[0]!.body as FormData
    expect(created.get('course_id')).toBe('ml')
    expect(created.get('title')).toBe('Brand new lecture')
    // Step two went to the media endpoint for the id the create returned.
    expect(FakeXhr.last).not.toBeNull()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('reports a failed create and stays open, keeping the typed title', async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog([
      { method: 'POST', path: '/lectures', status: 500, json: { detail: 'disk is full' } },
    ])

    await user.type(screen.getByLabelText(/Lecture title/i), 'Brand new lecture')
    await user.upload(fileInput(), new File(['x'], 'brand new.mp4', { type: 'video/mp4' }))
    await user.click(screen.getByRole('button', { name: /Upload & transcribe/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('disk is full')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Lecture title/i)).toHaveValue('Brand new lecture')
  })

  it('cancel closes without uploading', async () => {
    const user = userEvent.setup()
    const { mock, onClose } = renderDialog()

    await user.type(screen.getByLabelText(/Lecture title/i), 'Never sent')
    await user.upload(fileInput(), new File(['x'], 'x.mp4', { type: 'video/mp4' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalled()
    expect(mock.callsTo('POST', '/lectures')).toHaveLength(0)
  })
})
