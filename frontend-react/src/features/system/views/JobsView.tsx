import React from 'react'
import { Box, Button, Card, CardContent, Chip, LinearProgress, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import { jobs as jobsApi } from '../../../api/jobs'
import { useJobList, useFeedStatus } from '../../../lib/useJobFeed'
import { feedStatus } from '../../../lib/feedStatus'
import { useAppStore } from '../../../store/useAppStore'

/**
 * The job registry, as a view rather than only a drawer.
 *
 * Reads the feed cache through `useJobList` — it never fetches `/jobs` itself.
 * The stream owns that key (§I2); a view that queried it could overwrite the
 * live snapshot with an empty page.
 */
export const JobsView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const jobs = useJobList(selectedCourseId)
  const { mode } = useFeedStatus(selectedCourseId)
  const feed = feedStatus(mode)

  const active = jobs.filter((j) => !j.terminal)

  const cancel = async (id: number) => {
    try {
      await jobsApi.cancel(id)
    } catch (err: unknown) {
      console.error('Failed to cancel job', err)
    }
  }

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to see its jobs.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h4">Background tasks</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
            Every job for this course, whoever started it.
          </Typography>
        </Box>
        <Chip
          label={feed.label}
          color={feed.tone === 'ok' ? 'success' : feed.tone === 'degraded' ? 'warning' : 'default'}
          variant="outlined"
        />
      </Box>

      {feed.tone === 'down' && (
        <Typography variant="body2" sx={{ color: 'warning.main' }}>
          {feed.detail}
        </Typography>
      )}

      <Card>
        <CardContent sx={{ p: 3 }}>
          {jobs.length === 0 ? (
            <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
              No background jobs for this course yet. Upload a lecture or extract concepts to
              start one.
            </Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Job</TableCell>
                  <TableCell>Kind</TableCell>
                  <TableCell>Target</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Stage</TableCell>
                  <TableCell>Progress</TableCell>
                  <TableCell align="right">Action</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={job.id} hover>
                    <TableCell sx={{ fontFamily: 'var(--font-mono)' }}>#{job.id}</TableCell>
                    <TableCell>{job.kind}</TableCell>
                    <TableCell>{job.title ?? '—'}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={job.status}
                        variant="outlined"
                        color={
                          job.status === 'ready'
                            ? 'success'
                            : job.status === 'error' || job.status === 'orphaned'
                              ? 'error'
                              : job.status === 'running'
                                ? 'warning'
                                : 'default'
                        }
                      />
                    </TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontSize: '0.8rem' }}>
                      {job.stage ?? '—'}
                    </TableCell>
                    <TableCell sx={{ minWidth: 130 }}>
                      <LinearProgress
                        variant="determinate"
                        value={job.progress_pct}
                        sx={{ height: 6, borderRadius: 3 }}
                      />
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        {job.progress_pct}%
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      {!job.terminal && (
                        <Button size="small" color="error" onClick={() => void cancel(job.id)}>
                          Cancel
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        {active.length} running · {jobs.length - active.length} finished. Terminal jobs stay
        listed here; the drawer keeps only work still in flight.
      </Typography>
    </Box>
  )
}
