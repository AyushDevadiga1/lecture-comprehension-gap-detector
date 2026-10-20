import { describe, expect, it, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { createRef } from 'react'
import { useRouteFocus } from './useRouteFocus'

/**
 * P6 a11y: route changes must move focus and update the document title.
 */

function renderAt(route: string) {
  const mainRef = createRef<HTMLElement>()
  const { result } = renderHook(() => useRouteFocus(mainRef), {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    ),
  })
  return { mainRef, ...result }
}

describe('useRouteFocus', () => {
  beforeEach(() => {
    document.title = ''
  })

  it('sets document.title from the nav label', () => {
    renderAt('/student/overview')
    expect(document.title).toBe('Overview · LecGap')
  })

  it('sets document.title for a faculty route', () => {
    renderAt('/faculty/heatmap')
    expect(document.title).toBe('Heatmap · LecGap')
  })

  it('sets document.title for a system route', () => {
    renderAt('/jobs')
    expect(document.title).toBe('Jobs · LecGap')
  })

  it('falls back to a generic title for an unknown route', () => {
    renderAt('/no-such-route')
    expect(document.title).toBe('LecGap · LecGap')
  })
})
