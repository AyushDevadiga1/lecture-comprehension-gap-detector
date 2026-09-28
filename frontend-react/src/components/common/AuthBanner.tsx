import { useSyncExternalStore } from 'react'
import { Alert, Button } from '@mui/material'
import { getAuthBanner, subscribeAuthBanner } from '../../lib/authBanner'

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
  if (!banner.message) return null

  return (
    <Alert
      severity="warning"
      role="alert"
      sx={{ borderRadius: 0 }}
      action={
        <Button color="inherit" size="small" href="/health" target="_blank" rel="noreferrer">
          Check API
        </Button>
      }
    >
      {banner.message}
    </Alert>
  )
}
