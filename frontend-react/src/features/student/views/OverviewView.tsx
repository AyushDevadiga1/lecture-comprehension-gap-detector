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
import { gradient } from '../../../theme/alpha'

/** One stat brick of the snapshot strip. */
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

/** One clickable step in the pipeline stepper. */
const PipelineStep: React.FC<{
  num: number
  label: string
  desc: string
  done: boolean
  active: boolean
  to: string
}> = ({ num, label, desc, done, active, to }) => (
  <Box
    component={RouterLink}
    to={to}
    sx={{
      flex: 1,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 0.75,
      textDecoration: 'none',
      color: 'text.primary',
      '&:hover .step-circle': { borderColor: 'primary.main' },
    }}
  >
    <Box
      className="step-circle"
      sx={{
        width: 40,
        height: 40,
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: '2px solid',
        borderColor: done ? 'success.main' : active ? 'primary.main' : 'divider',
        bgcolor: done ? 'success.main' : active ? 'primary.main' : 'transparent',
        color: done || active ? 'primary.contrastText' : 'text.secondary',
        fontWeight: 700,
        fontSize: '0.9rem',
        transition: 'border-color 0.2s',
        flexShrink: 0,
      }}
    >
      {done ? '✓' : num}
    </Box>
    <Box sx={{ textAlign: 'center' }}>
      <Typography
        variant="caption"
        sx={{
          fontWeight: 700,
          color: done ? 'success.main' : active ? 'primary.main' : 'text.secondary',
          display: 'block',
        }}
      >
        {label}
      </Typography>
      <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem' }}>
        {desc}
      </Typography>
    </Box>
  </Box>
)

/** Horizontal connector line between steps. */
const Connector: React.FC<{ done: boolean }> = ({ done }) => (
  <Box
    sx={{
      flex: '0 0 24px',
      height: '2px',
      bgcolor: done ? 'success.main' : 'divider',
      mt: '20px',
      alignSelf: 'flex-start',
      transition: 'background-color 0.3s',
    }}
  />
)

/**
 * Course overview — hero banner explaining LecGap in plain English, a smart
 * pipeline stepper driven by real snapshot data, stat bricks, in-flight jobs,
 * and a "where to go next" action grid.
 *
 * Quota & services info has been moved to /system (System & quota view) —
 * it is debugging/admin context that students don't need on their landing page.
 *
 * One request of its own (`['snapshot', courseId]`).
 */
export const OverviewView: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  const { data: snapshot, error: snapshotError } = useQuery({
    queryKey: queryKeys.snapshot(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.snapshot(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  const { data: usageData } = useQuery({
    queryKey: queryKeys.usage(),
    queryFn: () => usageApi.get(),
  })
  const quota = usageRows(usageData)

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  const inFlight = snapshot?.in_flight ?? []

  // Derive pipeline step completion state from the snapshot
  const hasLectures = (snapshot?.lectures.ready ?? 0) > 0
  const hasGraph    = snapshot?.graph.has ?? false
  const hasQuiz     = (snapshot?.quiz.questions ?? 0) > 0

  const steps = [
    {
      num: 1, label: 'Upload a lecture', desc: 'Add a recording',
      done: hasLectures, active: !hasLectures,
      to: '/student/lectures',
    },
    {
      num: 2, label: 'Build concept map', desc: 'Extract & connect topics',
      done: hasGraph, active: hasLectures && !hasGraph,
      to: '/student/map',
    },
    {
      num: 3, label: 'Take the quiz', desc: 'Find your gaps',
      done: hasQuiz, active: hasGraph && !hasQuiz,
      to: '/student/quiz',
    },
    {
      num: 4, label: 'Follow the plan', desc: 'Watch prerequisite clips',
      done: false, active: hasQuiz,
      to: '/student/remediation',
    },
  ]

  const actions = [
    { to: '/student/lectures', label: 'Upload a lecture', hint: 'add a recording and transcribe it' },
    { to: '/student/map', label: 'Open the concept map', hint: 'see what depends on what' },
    { to: '/student/quiz', label: 'Take the quiz', hint: 'find your gaps' },
    { to: '/student/remediation', label: 'Study the plan', hint: 'work the gaps in order' },
  ]

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>

      {/* ── Hero banner ──────────────────────────────────────────────────── */}
      <Rise delay={0}>
        <Card
          sx={{
            background: gradient('surface', 'surface_alt', 135),
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <CardContent sx={{ p: { xs: 2.5, md: 3.5 } }}>
            <Typography
              variant="overline"
              sx={{ color: 'primary.main', fontWeight: 700, letterSpacing: '0.12em' }}
            >
              Lecture Comprehension Gap Detector
            </Typography>
            <Typography variant="h5" sx={{ mt: 1, fontWeight: 700, lineHeight: 1.35 }}>
              Upload your lectures. LecGap maps which topics depend on which,
              then after a quiz tells you exactly which prerequisites to revisit —
              in the right order.
            </Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1.5, maxWidth: 680 }}>
              No manual tagging required. The prerequisite graph is built automatically
              from what the professor actually says in the lecture, refined by your quiz
              performance, and linked back to the exact video clip where each concept
              was first taught.
            </Typography>
          </CardContent>
        </Card>
      </Rise>

      {/* ── Pipeline progress stepper ────────────────────────────────────── */}
      <Rise delay={0.05}>
        <Card>
          <CardContent sx={{ p: 3 }}>
            <Typography
              variant="subtitle2"
              sx={{ mb: 2.5, color: 'text.secondary', fontWeight: 600 }}
            >
              Your progress · course {selectedCourseId.toUpperCase()}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'flex-start' }}>
              {steps.map((s, i) => (
                <React.Fragment key={s.num}>
                  <PipelineStep {...s} />
                  {i < steps.length - 1 && (
                    <Connector done={steps[i + 1].done || steps[i + 1].active} />
                  )}
                </React.Fragment>
              ))}
            </Box>
          </CardContent>
        </Card>
      </Rise>

      {snapshotError && (
        <ErrorAlert error={snapshotError} title="Failed to load course snapshot" />
      )}

      {/* ── Snapshot stat bricks ─────────────────────────────────────────── */}
      {snapshot && (
        <Grid container spacing={2}>
          <Brick
            label="Total lectures"
            value={`${snapshot.lectures.total} (${snapshot.lectures.ready} ready)`}
            note={`${snapshot.lectures.uploaded} uploaded · ${snapshot.lectures.transcribing} transcribing · ${snapshot.lectures.error} error`}
            delay={0.08}
          />
          <Brick
            label="Extracted concepts"
            value={snapshot.concepts}
            note="unique topics found across all lectures"
            delay={0.11}
          />
          <Brick
            label="Prerequisite graph"
            value={snapshot.graph.has ? `${snapshot.graph.edges} edges` : 'Not built yet'}
            note={
              snapshot.graph.has
                ? `${snapshot.graph.nodes} nodes`
                : 'extract concepts first'
            }
            delay={0.14}
          />
          <Brick
            label="Video clips cut"
            value={`${snapshot.clips.ok} / ${snapshot.clips.cut} OK`}
            note={
              snapshot.clips.cut > snapshot.clips.ok
                ? 'some clips missing media'
                : 'all clips available'
            }
            delay={0.17}
          />
        </Grid>
      )}

      {/* ── In-flight processing & Quota ─────────────────────────────────── */}
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

      {/* ── Where to go next ─────────────────────────────────────────────── */}
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
