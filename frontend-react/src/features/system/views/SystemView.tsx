import React from 'react'
import { Alert, Box, Card, CardContent, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { usage as usageApi } from '../../../api/usage'
import { queryKeys } from '../../../lib/queryKeys'
import { useFeedStatus } from '../../../lib/useJobFeed'
import { feedStatus } from '../../../lib/feedStatus'
import { usageLine, usageRows } from '../../../lib/usageLine'
import { useAppStore } from '../../../store/useAppStore'

/**
 * System & quota — what the backend can do right now.
 *
 * Reads `['usage']` (owned by the sidebar, so this is a cache hit) and the feed
 * mode. It exists so a reader who *needs* to know whether transcription will
 * work has a page for it, rather than a one-line footer caption.
 */
export const SystemView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const { mode } = useFeedStatus(selectedCourseId)
  const feed = feedStatus(mode)

  const { data, error } = useQuery({
    queryKey: queryKeys.usage(),
    queryFn: () => usageApi.get(),
  })

  const summary = usageLine(data)
  const rows = usageRows(data)

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4">System &amp; quota</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          What the backend can do right now, and what it will refuse.
        </Typography>
      </Box>

      {error && <Alert severity="error">Could not read usage: {(error as Error).message}</Alert>}

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Services
          </Typography>
          {summary ? (
            <Typography variant="body2" sx={{ fontFamily: 'var(--font-mono)', mb: 2 }}>
              {summary}
            </Typography>
          ) : (
            <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
              No usage data yet — counters appear after the first API call.
            </Typography>
          )}

          {rows.length === 0 ? (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              No usage data yet — counters appear after the first API call.
            </Typography>
          ) : (
            rows.map((row) => (
              <Box
                key={row.name}
                sx={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 2,
                  py: 1,
                  borderTop: '1px solid',
                  borderColor: 'divider',
                }}
              >
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {row.name}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: 'var(--font-mono)', color: 'text.secondary' }}
                >
                  {row.detail}
                </Typography>
              </Box>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Feed &amp; connectivity
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            <b>{feed.label}</b> — {feed.detail}
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Three states exist on purpose: polling is degraded-but-working, disconnected is
            terminal. One label for both would read as a lie.
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Failure surfaces
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            401 → one banner at the top of the page, with Retry that clears it and refetches.
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Course delete is refused for the last remaining course — with none selected there
            is no path to create the next one yet.
          </Typography>
          <Typography variant="body2">
            A view that throws renders an error panel in place; the sidebar and job drawer stay
            mounted so the state is still visible.
          </Typography>
        </CardContent>
      </Card>
    </Box>
  )
}
