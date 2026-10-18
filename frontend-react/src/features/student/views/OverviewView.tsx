import React from 'react'
import { Box, Card, Grid, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { Rise } from '../../../components/common/Rise'

/**
 * Course overview — the snapshot strip, and nothing else yet.
 *
 * This is the P0 move: the section lifted out of `StudentDashboard` verbatim,
 * so the route exists before it is redesigned. P1 adds the in-flight card,
 * the quota card and the next-actions row from the approved mock.
 *
 * Owns `['snapshot', courseId]`. The shell owns `['courses']` and `['usage']`,
 * so this view adds exactly one request.
 */
export const OverviewView: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  const { data: snapshot, error: snapshotError } = useQuery({
    queryKey: queryKeys.snapshot(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.snapshot(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4">
          Student portal: {selectedCourseId.toUpperCase()}
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Upload lectures, take adaptive comprehension checks, and stream prerequisite
          remediation clips.
        </Typography>
      </Box>

      {snapshotError && (
        <ErrorAlert error={snapshotError} title="Failed to load course snapshot" />
      )}

      {snapshot && (
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} md={3}>
            <Rise delay={0}>
              <Card sx={{ p: 1.5 }}>
                <Typography
                  variant="caption"
                  sx={{
                    color: 'text.secondary',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                  }}
                >
                  Total lectures
                </Typography>
                <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.lectures.total} ({snapshot.lectures.ready} ready)
                </Typography>
              </Card>
            </Rise>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Rise delay={0.05}>
              <Card sx={{ p: 1.5 }}>
                <Typography
                  variant="caption"
                  sx={{
                    color: 'text.secondary',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                  }}
                >
                  Extracted concepts
                </Typography>
                <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.concepts}
                </Typography>
              </Card>
            </Rise>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Rise delay={0.1}>
              <Card sx={{ p: 1.5 }}>
                <Typography
                  variant="caption"
                  sx={{
                    color: 'text.secondary',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                  }}
                >
                  Prerequisite graph
                </Typography>
                <Typography
                  variant="h5"
                  sx={{
                    mt: 0.5,
                    fontVariantNumeric: 'tabular-nums',
                    color: snapshot.graph.has ? 'success.main' : 'warning.main',
                  }}
                >
                  {snapshot.graph.has ? `${snapshot.graph.edges} edges` : 'Not built'}
                </Typography>
              </Card>
            </Rise>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Rise delay={0.15}>
              <Card sx={{ p: 1.5 }}>
                <Typography
                  variant="caption"
                  sx={{
                    color: 'text.secondary',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                  }}
                >
                  Video clips cut
                </Typography>
                <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.clips.ok} / {snapshot.clips.cut} OK
                </Typography>
              </Card>
            </Rise>
          </Grid>
        </Grid>
      )}
    </Box>
  )
}
