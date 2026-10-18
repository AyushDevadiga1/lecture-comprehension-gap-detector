import React from 'react'
import { Box, Card, CardContent, Grid, LinearProgress, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { usage as usageApi } from '../../../api/usage'
import { queryKeys } from '../../../lib/queryKeys'
import { usageRows } from '../../../lib/usageLine'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { Rise } from '../../../components/common/Rise'

/** One brick of the snapshot strip. */
const Brick: React.FC<{ label: string; value: React.ReactNode; note?: string; delay: number }> = ({
  label,
  value,
  note,
  delay,
}) => (
  <Grid item xs={12} sm={6} md={3}>
    <Rise delay={delay}>
      <Card sx={{ p: 1.5, height: '100%' }}>
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
          {label}
        </Typography>
        <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
          {value}
        </Typography>
        {note && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {note}
          </Typography>
        )}
      </Card>
    </Rise>
  </Grid>
)

/**
 * Course overview — the snapshot strip, what the pipeline is working on, the
 * quota, and where to go next.
 *
 * One request of its own (`['snapshot', courseId]`); the quota card reads
 * `['usage']`, which the sidebar already owns, so it is a cache hit rather
 * than a second fetch.
 *
 * The in-flight card reads `snapshot.in_flight` — the same payload, no extra
 * call. It is the honest place to see "something is running" without opening
 * the drawer, and it lists *only* rows the pipeline is actively working on: a
 * stuck `uploaded` row is a triage problem, and it belongs in Lectures, not in
 * a spinning card here.
 */
export const OverviewView: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  const { data: snapshot, error: snapshotError } = useQuery({
    queryKey: queryKeys.snapshot(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.snapshot(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  const { data: usage } = useQuery({
    queryKey: queryKeys.usage(),
    queryFn: () => usageApi.get(),
    retry: false,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  const inFlight = snapshot?.in_flight ?? []
  const quota = usageRows(usage)

  const actions = [
    { to: '/student/lectures', label: 'Upload a lecture', hint: 'add a recording and transcribe it' },
    { to: '/student/map', label: 'Open the concept map', hint: 'see what depends on what' },
    { to: '/student/quiz', label: 'Take the quiz', hint: 'find your gaps' },
    { to: '/student/remediation', label: 'Study the plan', hint: 'work the gaps in order' },
  ]

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4">Student portal: {selectedCourseId.toUpperCase()}</Typography>
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
          <Brick
            label="Total lectures"
            value={`${snapshot.lectures.total} (${snapshot.lectures.ready} ready)`}
            note={`${snapshot.lectures.uploaded} uploaded · ${snapshot.lectures.transcribing} transcribing · ${snapshot.lectures.error} error`}
            delay={0}
          />
          <Brick label="Extracted concepts" value={snapshot.concepts} delay={0.05} />
          <Brick
            label="Prerequisite graph"
            value={snapshot.graph.has ? `${snapshot.graph.edges} edges` : 'Not built'}
            note={snapshot.graph.has ? `${snapshot.graph.nodes} nodes` : 'extract concepts to build it'}
            delay={0.1}
          />
          <Brick
            label="Video clips cut"
            value={`${snapshot.clips.ok} / ${snapshot.clips.cut} OK`}
            note={snapshot.clips.cut > snapshot.clips.ok ? 'some rows have no media on the server' : undefined}
            delay={0.15}
          />
        </Grid>
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>
                In flight
              </Typography>
              {inFlight.length === 0 ? (
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  Nothing is processing right now.
                </Typography>
              ) : (
                inFlight.map((f) => (
                  <Box key={f.lecture_id} sx={{ mb: 1.5 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        #{f.lecture_id} — {f.title}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        {f.status}
                      </Typography>
                    </Box>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      {f.stage} · {f.progress_pct}%
                    </Typography>
                    <LinearProgress
                      variant="determinate"
                      value={f.progress_pct}
                      sx={{ height: 6, borderRadius: 3, mt: 0.5 }}
                    />
                  </Box>
                ))
              )}
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Read from the snapshot, so this costs no extra request. A row stuck on
                &ldquo;uploaded&rdquo; is not shown here — it needs triage, not a spinner.
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Quota &amp; services
              </Typography>
              {quota.length === 0 ? (
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  No usage data yet — counters appear after the first API call.
                </Typography>
              ) : (
                quota.map((row) => (
                  <Box
                    key={row.name}
                    sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 2,
                      py: 0.75,
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {row.name}
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{ fontFamily: 'var(--font-mono)', color: 'text.secondary' }}
                    >
                      {row.detail}
                    </Typography>
                  </Box>
                ))
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Where to go next
          </Typography>
          <Grid container spacing={2}>
            {actions.map((a) => (
              <Grid item xs={12} sm={6} md={3} key={a.to}>
                <Box
                  component={RouterLink}
                  to={a.to}
                  sx={{
                    display: 'block',
                    textDecoration: 'none',
                    color: 'text.primary',
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 2,
                    p: 1.5,
                    height: '100%',
                    '&:hover': { borderColor: 'info.main' },
                  }}
                >
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                    {a.label}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {a.hint}
                  </Typography>
                </Box>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>
    </Box>
  )
}
