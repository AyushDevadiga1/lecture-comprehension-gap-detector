import React from 'react'
import { Box, Button, Card, CardContent, Chip, Grid, LinearProgress, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import { jobs as jobsApi } from '../../../api/jobs'
import { useJobList, useFeedStatus } from '../../../lib/useJobFeed'
import { feedStatus } from '../../../lib/feedStatus'
import { formatElapsed } from '../../../lib/format'
import { useAppStore } from '../../../store/useAppStore'
import type { JobOut } from '../../../api/types'

/**
 * The job registry, as a view rather than only a drawer.
 *
 * Reads the feed cache through `useJobList` — it never fetches `/jobs` itself.
 * The stream owns that key (§I2); a view that queried it could overwrite the
 * live snapshot with an empty page.
 *
 * P5 polish per `revamp-plan/04-phases.md`: the strip above the table
 * (running / finished / orphaned / change token) and the elapsed column mirror
 * the registry's own summary, so the view is not a bare table of rows.
 */
const parse = (iso: string | null | undefined): number | null => {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

/** Wall-clock elapsed for a row, from start to finish (or to now if still running). */
function elapsedSeconds(job: JobOut, nowMs: number): number | null {
  const start = parse(job.started_at) ?? parse(job.created_at)
  if (start == null) return null
  const end = parse(job.finished_at) ?? nowMs
  return Math.max(0, (end - start) / 1000)
}

export const JobsView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const jobs = useJobList(selectedCourseId)
  const { mode, changeToken } = useFeedStatus(selectedCourseId)
  const feed = feedStatus(mode)
  const nowMs = Date.now()

  const active = jobs.filter((j) => !j.terminal)
  const finished = jobs.filter((j) => j.terminal && j.status === 'ready')
  const orphaned = jobs.filter((j) => j.status === 'orphaned')

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

      <Grid container spacing={2}>
        <Grid item xs={6} md={3}>
          <Card sx={{ p: 2, height: '100%' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
              Running now
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: active.length ? 'warning.main' : 'text.primary' }}>
              {active.length}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              In flight
            </Typography>
          </Card>
        </Grid>
        <Grid item xs={6} md={3}>
          <Card sx={{ p: 2, height: '100%' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
              Finished
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: 'success.main' }}>
              {finished.length}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Ready this session
            </Typography>
          </Card>
        </Grid>
        <Grid item xs={6} md={3}>
          <Card sx={{ p: 2, height: '100%' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
              Orphaned
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: orphaned.length ? 'error.main' : 'text.primary' }}>
              {orphaned.length}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Lost at last restart
            </Typography>
          </Card>
        </Grid>
        <Grid item xs={6} md={3}>
          <Card sx={{ p: 2, height: '100%' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
              Snapshot token
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', fontFamily: 'var(--font-mono)' }}>
              #{changeToken}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Advances on change
            </Typography>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <CardContent sx={{ p: 3 }}>
          {jobs.length === 0 ? (
            <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
              No background jobs for this course yet. Upload a lecture or extract concepts to
              start one.
            </Typography>
          ) : (
            <>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Job</TableCell>
                    <TableCell>Kind</TableCell>
                    <TableCell>Target</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Stage</TableCell>
                    <TableCell>Progress</TableCell>
                    <TableCell align="right">Elapsed</TableCell>
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
                      <TableCell align="right" sx={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        {formatElapsed(elapsedSeconds(job, nowMs))}
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

              {orphaned.length > 0 && (
                <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 2 }}>
                  <b>Orphaned</b> means the server restarted while the job was running; nothing
                  is executing it any more. That is stated plainly rather than shown as a stuck
                  spinner.
                </Typography>
              )}
            </>
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
