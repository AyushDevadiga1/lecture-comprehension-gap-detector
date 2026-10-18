import React from 'react'
import { Box, Button, Typography } from '@mui/material'
import { NavLink } from 'react-router-dom'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import { useQuery } from '@tanstack/react-query'
import { CoursePicker } from './CoursePicker'
import { NAV, NAV_GROUPS } from '../../nav'
import { useAppStore } from '../../store/useAppStore'
import { useActiveJobs, useFeedStatus } from '../../lib/useJobFeed'
import { feedStatus } from '../../lib/feedStatus'
import { usageLine } from '../../lib/usageLine'
import { usage as usageApi } from '../../api/usage'
import { queryKeys } from '../../lib/queryKeys'
import { tint } from '../../theme/alpha'

/**
 * The primary navigation.
 *
 * It replaces the navbar's role tabs because the approved layout carries both
 * dashboards in one sidebar — a student and a lecturer are two groups of one
 * app, not two apps.
 *
 * What it must NOT do: subscribe to job state in a way that re-renders the
 * route. It reads the active job *count* (a leaf read through
 * `useSyncExternalStore` over the query cache) and the feed *mode*; it never
 * renders the job list and never passes job data down. §1 keeps holding because
 * `<Outlet/>` is a sibling of this component, not a child of it, and the count
 * changing only re-renders the badge.
 *
 * The footer owns `['usage']`. Overview and System read the same key, so the
 * quota line costs one request for the whole app rather than one per view.
 */
export const Sidebar: React.FC = () => {
  const { selectedCourseId, base, toggleBase } = useAppStore()
  const activeJobs = useActiveJobs(selectedCourseId)
  const { mode } = useFeedStatus(selectedCourseId)
  const feed = feedStatus(mode)

  const { data: usageData } = useQuery({
    queryKey: queryKeys.usage(),
    queryFn: () => usageApi.get(),
    // Failure is silent here by design: the footer is ambient information, and
    // a quota line must never become an error banner. Overview surfaces the
    // same key with a real error state for anyone who needs to act on it.
    retry: false,
  })
  const quota = usageLine(usageData)

  return (
    <Box
      component="nav"
      aria-label="Sections"
      sx={{
        width: 250,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        height: '100vh',
        position: 'sticky',
        top: 0,
        borderRight: '1px solid',
        borderColor: 'divider',
        backgroundColor: tint('surface', 55),
      }}
    >
      {/* Brand */}
      <Box sx={{ px: 2, pt: 2, pb: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mb: 1.5 }}>
          <Box
            sx={{
              width: 34,
              height: 34,
              borderRadius: '10px',
              backgroundColor: 'primary.main',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: `1px solid ${tint('ink-light', 35)}`,
            }}
          >
            <AccountTreeIcon sx={{ color: 'primary.contrastText', fontSize: 18 }} />
          </Box>
          <Box>
            <Typography
              variant="h6"
              sx={{ fontWeight: 600, fontSize: '1.1rem', lineHeight: 1.05, letterSpacing: '-0.01em' }}
            >
              LecGap
            </Typography>
            <Typography
              variant="caption"
              sx={{
                color: 'text.secondary',
                fontSize: '0.6rem',
                fontWeight: 600,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                display: 'block',
              }}
            >
              Comprehension DAG
            </Typography>
          </Box>
        </Box>
        <CoursePicker />
      </Box>

      {/* Sections */}
      <Box sx={{ flex: 1, overflowY: 'auto', minHeight: 0, px: 1, py: 1.5 }}>
        {NAV_GROUPS.map((group) => (
          <Box key={group} sx={{ mb: 1.5 }}>
            <Typography
              sx={{
                px: 1,
                pb: 0.5,
                fontSize: '0.6rem',
                fontWeight: 600,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'text.secondary',
                display: 'block',
              }}
            >
              {group}
            </Typography>
            {NAV.filter((item) => item.group === group).map((item) => {
              const Icon = item.icon
              const isJobs = item.to === '/jobs'
              return (
                <Box
                  key={item.to}
                  component={NavLink}
                  to={item.to}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.1,
                    px: 1,
                    py: 0.7,
                    mb: 0.25,
                    borderRadius: '8px',
                    textDecoration: 'none',
                    color: 'text.secondary',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    border: '1px solid transparent',
                    '&:hover': { backgroundColor: tint('text', 5), color: 'text.primary' },
                    '&[aria-current="page"]': {
                      color: 'text.primary',
                      backgroundColor: tint('info', 11),
                      borderColor: tint('info', 38),
                    },
                  }}
                >
                  <Icon fontSize="small" />
                  <span>{item.label}</span>
                  {isJobs && activeJobs.length > 0 && (
                    <Box
                      component="span"
                      sx={{
                        ml: 'auto',
                        minWidth: 18,
                        height: 18,
                        px: 0.5,
                        borderRadius: '999px',
                        backgroundColor: 'primary.main',
                        color: 'primary.contrastText',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.62rem',
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      {activeJobs.length}
                    </Box>
                  )}
                </Box>
              )
            })}
          </Box>
        ))}
      </Box>

      {/* Ambient state: feed, quota, theme */}
      <Box sx={{ px: 1.5, py: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75 }}>
          <Box
            role="status"
            aria-label={`Feed status: ${feed.detail}`}
            sx={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor:
                feed.tone === 'ok'
                  ? 'success.main'
                  : feed.tone === 'degraded'
                    ? 'warning.main'
                    : 'text.disabled',
              boxShadow: feed.tone === 'ok' ? '0 0 8px var(--lgc-ok)' : 'none',
            }}
          />
          <Typography variant="caption" sx={{ color: 'text.secondary', flex: 1 }}>
            {feed.label}
            {activeJobs.length > 0 ? ` · ${activeJobs.length} job${activeJobs.length === 1 ? '' : 's'}` : ''}
          </Typography>
          <Button
            size="small"
            variant="outlined"
            onClick={toggleBase}
            aria-label={base === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            sx={{ minWidth: 0, px: 1, py: 0.25, fontSize: '0.68rem' }}
          >
            {base === 'dark' ? 'Light' : 'Dark'}
          </Button>
        </Box>
        {quota && (
          <Typography
            variant="caption"
            sx={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6rem',
              color: 'text.secondary',
              display: 'block',
              lineHeight: 1.35,
            }}
          >
            {quota}
          </Typography>
        )}
      </Box>
    </Box>
  )
}
