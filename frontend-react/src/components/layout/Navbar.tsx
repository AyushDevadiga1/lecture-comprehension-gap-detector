import React from 'react'
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  Badge,
  IconButton,
  Tooltip,
} from '@mui/material'
import { NavLink, useLocation } from 'react-router-dom'
import BoltIcon from '@mui/icons-material/Bolt'
import SchoolIcon from '@mui/icons-material/School'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import LayersIcon from '@mui/icons-material/Layers'
import LightModeIcon from '@mui/icons-material/LightMode'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import { useAppStore } from '../../store/useAppStore'
import { useActiveJobs, useFeedStatus } from '../../lib/useJobFeed'
import { feedStatus } from '../../lib/feedStatus'
import { tint } from '../../theme/alpha'
import { CoursePicker } from './CoursePicker'

export const Navbar: React.FC = () => {
  const location = useLocation()
  const { selectedCourseId, toggleJobDrawer, base, toggleBase } = useAppStore()
  // Reads the query cache, not the feed. The badge and the status dot are the
  // only Navbar elements that depend on job state.
  const activeJobs = useActiveJobs(selectedCourseId)
  const { mode } = useFeedStatus(selectedCourseId)
  // One description of the feed, shared with the drawer. This used to be
  // `mode === 'stream'`, which reported a feed that had *given up* as
  // "Connecting to SSE Stream…" — forever, and indistinguishably from a slow
  // start. See lib/feedStatus.ts.
  const feed = feedStatus(mode)

  // Course selection, auto-selection, fallback and deletion live in
  // <CoursePicker/> — one owner for one concern. It reads the same query key
  // this navbar used to own, so nothing refetches.

  return (
    <AppBar position="sticky" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar
        sx={{
          justifyContent: 'space-between',
          px: { xs: 2, md: 4 },
          minHeight: { xs: 60, md: 68 },
        }}
      >
        {/* Brand */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box
            sx={{
              width: 38,
              height: 38,
              borderRadius: '10px',
              // Solid info tile, no glow: the gradient + shadow version read
              // as decoration rather than brand. One flat token, one hairline
              // ring, and the measured contrast ink do the whole job.
              backgroundColor: 'primary.main',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              // A hairline light ring so the tile reads as an object on both
              // bases — ink-light is near-white in dark and white in light.
              border: `1px solid ${tint('ink-light', 35)}`,
            }}
          >
            <AccountTreeIcon sx={{ color: 'primary.contrastText', fontSize: 20 }} />
          </Box>
          <Box>
            <Typography
              variant="h6"
              sx={{
                fontWeight: 600,
                fontSize: '1.2rem',
                lineHeight: 1.05,
                letterSpacing: '-0.025em',
                color: 'text.primary',
              }}
            >
              LecGap
            </Typography>
            <Typography
              variant="caption"
              sx={{
                color: 'text.secondary',
                fontSize: '0.64rem',
                fontWeight: 600,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                display: 'block',
                mt: 0.25,
              }}
            >
              Engine 2 &bull; Comprehension DAG
            </Typography>
          </Box>
        </Box>

        {/* Navigation Tabs */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            component={NavLink}
            to="/student"
            startIcon={<SchoolIcon fontSize="small" />}
            variant={location.pathname.startsWith('/student') ? 'contained' : 'text'}
            sx={{
              color: location.pathname.startsWith('/student') ? 'primary.contrastText' : 'text.secondary',
              backgroundColor: location.pathname.startsWith('/student') ? 'primary.main' : 'transparent',
            }}
          >
            Student Portal
          </Button>

          <Button
            component={NavLink}
            to="/faculty"
            startIcon={<LayersIcon fontSize="small" />}
            variant={location.pathname.startsWith('/faculty') ? 'contained' : 'text'}
            sx={{
              color: location.pathname.startsWith('/faculty') ? 'primary.contrastText' : 'text.secondary',
              backgroundColor: location.pathname.startsWith('/faculty') ? 'primary.main' : 'transparent',
            }}
          >
            Faculty Insights
          </Button>
        </Box>

        {/* Right Tools: Course Selector + Jobs Drawer Trigger */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ minWidth: 170 }}>
            <CoursePicker />
          </Box>

          {/* Theme base. The choice is remembered and defaults to the OS
              preference; see `resolveInitialBase`.

              `aria-label` on both icon buttons below is load-bearing, not
              decoration. A MUI `Tooltip` does NOT give its child an accessible
              name — it sets `aria-describedby` while open, and the title is
              otherwise unreachable — so an `IconButton` wrapping only an icon
              with no `aria-label` is an unnamed control: invisible to a screen
              reader, and unaddressable by role in a test. The E2E tier found
              this by timing out on `getByRole('button', { name: ... })`. */}
          <Tooltip title={base === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            <IconButton
              onClick={toggleBase}
              color="inherit"
              aria-label={base === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              sx={{ border: '1px solid', borderColor: 'divider' }}
            >
              {base === 'dark' ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
            </IconButton>
          </Tooltip>

          {/* Jobs drawer toggle with active count */}
          <Tooltip title="View Background Jobs & Pipelines">
            <IconButton
              onClick={toggleJobDrawer}
              color="inherit"
              aria-label="View Background Jobs & Pipelines"
              sx={{ border: '1px solid', borderColor: 'divider' }}
            >
              <Badge badgeContent={activeJobs.length} color="primary">
                <BoltIcon sx={{ color: activeJobs.length > 0 ? 'info.main' : 'text.secondary' }} />
              </Badge>
            </IconButton>
          </Tooltip>

          {/* Feed connection indicator. The dot is decorative; the tooltip carries the
              meaning, and `aria-label` repeats it so the state is not trapped in
              a hover — a screen reader gets "Feed status: <detail>" rather than
              silence. */}
          <Tooltip title={feed.detail}>
            <Box
              role="status"
              aria-label={`Feed status: ${feed.detail}`}
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                backgroundColor:
                  feed.tone === 'ok'
                    ? 'success.main'
                    : feed.tone === 'degraded'
                      ? 'warning.main'
                      : 'text.disabled',
                boxShadow: feed.tone === 'ok' ? '0 0 10px var(--lgc-ok)' : 'none',
              }}
            />
          </Tooltip>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
