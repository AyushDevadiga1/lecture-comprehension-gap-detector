import { useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button } from '@mui/material'
import { getAuthBanner, subscribeAuthBanner, clearAuthBanner } from '../../lib/authBanner'

/**
 * The single 401 banner. Rendered at the top of the page, above everything.
 *
 * §6 and the roadmap's non-negotiables: "401 = one banner, never a dead
 * 'no courses' state". Before this, a key-guarded backend 401'd the course
 * query and the Navbar rendered "No courses found" — which reads as *your data
 * is gone* rather than *you are not authorised*, and sends the reader hunting in
 * the wrong place.
 */
export const AuthBanner: React.FC = () => {
  const banner = useSyncExternalStore(subscribeAuthBanner, getAuthBanner, getAuthBanner)
  const queryClient = useQueryClient()

  if (!banner.message) return null

  /**
   * The banner is sticky on purpose — a later successful read must not erase it,
   * because that read succeeding is exactly the confusing part. But sticky with
   * no way out is not a banner, it is a decoration: `clearAuthBanner` had no
   * caller outside the test suite, so one transient 401 (a key being rotated, a
   * proxy hiccup, a laptop waking) pinned "set VITE_LECGAP_API_KEY" over a
   * session that was working perfectly well. That is the same misleading state
   * this component exists to prevent, reached by the other door.
   *
   * `resetQueries` rather than `invalidateQueries`: clearing the error is the
   * point. The flag is dropped first, then every query goes back to its initial
   * state and refetches, so a corrected key proves itself by the data arriving
   * rather than by the banner choosing to disappear.
   */
  const retry = () => {
    clearAuthBanner()
    void queryClient.resetQueries()
  }

  return (
    <Alert
      severity="warning"
      role="alert"
      sx={{ borderRadius: 0 }}
      action={
        <Button color="inherit" size="small" onClick={retry}>
          Retry
        </Button>
      }
    >
      {banner.message}{' '}
      <Button
        color="inherit"
        size="small"
        href="/health"
        target="_blank"
        rel="noreferrer"
        sx={{ p: 0, minWidth: 0, verticalAlign: 'baseline', textDecoration: 'underline' }}
      >
        Check API
      </Button>
    </Alert>
  )
}
