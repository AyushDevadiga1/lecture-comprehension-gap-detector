import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useQuery } from '@tanstack/react-query'
import { AuthBanner } from './AuthBanner'
import { clearAuthBanner, createQueryClient, getAuthBanner } from '../../lib/authBanner'
import { courses as coursesApi } from '../../api/courses'
import { queryKeys } from '../../lib/queryKeys'
import { mockFetch } from '../../test/fetchMock'
import { renderWithProviders } from '../../test/render'

/**
 * F4: the 401 banner was sticky *and* inescapable.
 *
 * `lib/authBanner.ts` is explicit that stickiness is deliberate — a later
 * successful read must not erase the flag, because that read succeeding is
 * exactly the confusing part, and `authBanner.test.ts` pins that. But
 * `clearAuthBanner` had no caller outside the test suite and the banner offered
 * no way to clear itself. So one transient 401 (a key mid-rotation, a proxy
 * hiccup, a laptop waking) pinned "set VITE_LECGAP_API_KEY" over a session that
 * was working perfectly well — the same misleading state the banner exists to
 * prevent, reached by the other door.
 *
 * The fix is an explicit retry that drops the flag *and* resets the queries, so
 * a corrected key proves itself by the data arriving rather than by the banner
 * choosing to disappear.
 *
 * Note what is deliberately preserved: an unrelated success still does not clear
 * it. That is the existing stickiness contract and this change does not touch it.
 */

const courses = [
  { course_id: 'ml', total_lectures: 2, ready_lectures: 2, total_concepts: 24, has_graph: true, node_count: 22, edge_count: 10 },
]

/** Raise the banner the way production does: a real 401 through the real client. */
async function raise401(): Promise<void> {
  mockFetch([{ path: '/courses', status: 401, json: { detail: 'Unauthorized' } }])
  const qc = createQueryClient({ queries: { retry: false } })
  await qc.fetchQuery({ queryKey: queryKeys.courses(), queryFn: () => coursesApi.list() }).catch(() => {})
  expect(getAuthBanner().message).not.toBeNull()
}

describe('AuthBanner', () => {
  beforeEach(() => clearAuthBanner())

  it('renders nothing when no 401 has been seen', () => {
    renderWithProviders(<AuthBanner />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the banner and a way out once a 401 has been seen', async () => {
    await raise401()
    renderWithProviders(<AuthBanner />)

    expect(screen.getByRole('alert')).toHaveTextContent(/requires an API key/i)
    // The regression: this button did not exist, and nothing else could clear it.
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    // The pre-existing affordance is kept.
    expect(screen.getByRole('link', { name: /check api/i })).toBeInTheDocument()
  })

  it('Retry clears the flag', async () => {
    await raise401()
    renderWithProviders(<AuthBanner />)

    await userEvent.setup().click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(getAuthBanner().message).toBeNull())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('Retry refetches, so a corrected key proves itself with data', async () => {
    // The reason Retry is not just `clearAuthBanner()`: clearing the flag on its
    // own would let the banner be dismissed while the API is still refusing,
    // which is the mirror-image lie. The queries go back to their initial state
    // and refetch, so the banner only stays gone if the read now succeeds.
    await raise401()
    const fetchMock = mockFetch([{ path: '/courses', json: courses }])

    // A live query in the tree, because `resetQueries` only refetches queries
    // that exist. Asserting on the flag alone would pass even if the refetch
    // never happened.
    function Probe() {
      useQuery({ queryKey: queryKeys.courses(), queryFn: () => coursesApi.list() })
      return null
    }

    renderWithProviders(
      <>
        <AuthBanner />
        <Probe />
      </>,
    )

    await waitFor(() => expect(fetchMock.callsTo('GET', '/courses')).toHaveLength(1))

    await userEvent.setup().click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(getAuthBanner().message).toBeNull())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // The query was reset and refetched, rather than the flag merely dropped.
    await waitFor(() => expect(fetchMock.callsTo('GET', '/courses')).toHaveLength(2))
  })

  it('a later success alone still does not clear it', async () => {
    // The stickiness contract is unchanged. Retry is the *only* new exit, and
    // this is what stops "fix it by refreshing" from becoming a reflex that
    // teaches people to ignore the banner.
    await raise401()
    mockFetch([{ path: '/courses/ml/snapshot', json: { exists: true, course_id: 'ml' } }])
    const qc = createQueryClient({ queries: { retry: false } })
    await qc.fetchQuery({ queryKey: ['s'], queryFn: () => coursesApi.snapshot('ml') }).catch(() => {})

    expect(getAuthBanner().message).not.toBeNull()
  })
})