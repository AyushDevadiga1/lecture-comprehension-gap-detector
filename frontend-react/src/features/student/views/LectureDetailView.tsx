import React, { useState } from 'react'
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  IconButton,
  LinearProgress,
  MenuItem,
  Select,
  Tooltip,
  Typography,
} from '@mui/material'
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined'
import { useQuery } from '@tanstack/react-query'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { lectures as lecturesApi } from '../../../api/lectures'
import { queryKeys } from '../../../lib/queryKeys'
import { useLectureProgress } from '../../../lib/useLectureProgress'
import { useActiveJobs } from '../../../lib/useJobFeed'
import { useAppStore } from '../../../store/useAppStore'
import { StatusBadge } from '../../../components/common/StatusBadge'
import { CoverageTimeline } from '../../../components/common/CoverageTimeline'

/** Format seconds as m:ss */
function fmtTime(s?: number): string {
  if (s == null) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

/**
 * Per-lecture detail — enriched storytelling view.
 *
 * Shows:
 *   - Lecture picker + status badge
 *   - Coverage timeline (segment heat map)
 *   - "What this lecture covers" — the extracted concepts list with teach-timestamps
 *   - "Prerequisite links found here" — a count of edges whose evidence is from this lecture
 *   - Live progress card while transcribing
 *
 * Request budget per `revamp-plan/02-backend-map.md` §5: one `GET /lectures/{id}`
 * for the detail, and `GET /lectures/{id}/progress` only while the lecture is
 * transcribing and no job for it is visible in the feed.
 */
export const LectureDetailView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const [lectureId, setLectureId] = useState<number | null>(null)
  const navigate = useNavigate()

  const { data: lectureList = [] } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  const selected = lectureList.find((l) => l.id === lectureId) ?? lectureList[0] ?? null

  const { data: detail } = useQuery({
    queryKey: queryKeys.lecture(selected?.id ?? 0),
    queryFn: () => lecturesApi.get(selected?.id ?? 0),
    enabled: selected != null,
  })

  const status = detail?.status ?? selected?.status
  const isTranscribing = status === 'transcribing'

  const activeJobs = useActiveJobs(selectedCourseId)
  const job = activeJobs.find((j) => j.lecture_id === selected?.id) ?? null

  const progress = useLectureProgress(selected?.id ?? null, status)

  const showTimeline = selected != null && status === 'ready' && detail != null
  const showProgress = selected != null && isTranscribing

  // Concepts sorted by teach-start time
  const concepts = (detail?.concepts ?? []).slice().sort(
    (a, b) => (a.start_s ?? 0) - (b.start_s ?? 0),
  )

  if (!selected) {
    return (
      <Typography variant="body2" sx={{ color: 'text.secondary', mt: 2 }}>
        This course has no lectures yet. Upload one from the Lectures view.
      </Typography>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Lecture detail</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          What was discovered in this lecture — concepts, their timestamps, and
          how they connect to the rest of the course graph.
        </Typography>
      </Box>

      {/* ── Lecture picker + status ──────────────────────────────────────── */}
      <Card>
        <CardContent>
          <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
            Lecture
          </Typography>
          <Select
            size="small"
            fullWidth
            value={selected.id}
            onChange={(e) => setLectureId(Number(e.target.value))}
          >
            {lectureList.map((lec) => (
              <MenuItem key={lec.id} value={lec.id}>
                #{lec.id} — {lec.title}
              </MenuItem>
            ))}
          </Select>

          <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <StatusBadge status={selected.status} />
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {selected.has_media ? 'media on the server' : 'no media on the server'}
              </Typography>
            </Box>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Created {new Date(selected.created_at).toLocaleDateString()}
            </Typography>
            {selected.error && (
              <Typography variant="caption" sx={{ color: 'error.main' }}>
                Last error: {selected.error}
              </Typography>
            )}
          </Box>
        </CardContent>
      </Card>

      {/* ── Coverage timeline ─────────────────────────────────────────────── */}
      {showTimeline && (
        <Card sx={{ mt: 0 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Coverage timeline
            </Typography>
            <CoverageTimeline
              segments={detail?.segments}
              concepts={detail?.concepts}
              title={detail?.title ?? ''}
            />
          </CardContent>
        </Card>
      )}

      {/* ── Concepts extracted from this lecture ─────────────────────────── */}
      {status === 'ready' && (
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
              <Typography variant="h6">
                What this lecture covers
              </Typography>
              {concepts.length > 0 && (
                <Chip
                  label={`${concepts.length} concept${concepts.length !== 1 ? 's' : ''}`}
                  size="small"
                  variant="outlined"
                />
              )}
            </Box>

            {concepts.length === 0 ? (
              <Alert severity="info">
                No concepts extracted yet. Trigger concept extraction from the{' '}
                <Typography
                  component={RouterLink}
                  to="/student/lectures"
                  variant="inherit"
                  sx={{ color: 'primary.main' }}
                >
                  Lectures view
                </Typography>
                .
              </Alert>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {concepts.map((c, idx) => (
                  <Box
                    key={c.id}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      py: 0.9,
                      borderBottom: idx === concepts.length - 1 ? 'none' : '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    {/* Timestamp badge */}
                    <Typography
                      sx={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.72rem',
                        color: 'text.secondary',
                        minWidth: 48,
                        flexShrink: 0,
                      }}
                    >
                      {fmtTime(c.start_s)}
                    </Typography>

                    {/* Concept name */}
                    <Typography variant="body2" sx={{ flex: 1, fontWeight: 500 }}>
                      {c.name}
                    </Typography>

                    {/* Kind badges + show-on-map */}
                    <Box sx={{ display: 'flex', gap: 0.5, flexShrink: 0, alignItems: 'center' }}>
                      {c.implicit && (
                        <Chip label="implicit" size="small" variant="outlined" color="default" />
                      )}
                      {c.source === 'transcript' && (
                        <Chip label="spoken" size="small" variant="outlined" color="info" />
                      )}
                      <Tooltip title={`Show "${c.name}" on concept map`}>
                        <IconButton
                          size="small"
                          onClick={() =>
                            navigate(`/student/map?find=${encodeURIComponent(c.name)}`)
                          }
                          aria-label={`Show ${c.name} on concept map`}
                        >
                          <AccountTreeOutlinedIcon fontSize="inherit" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Box>
                ))}
              </Box>
            )}

            {concepts.length > 0 && (
              <Typography variant="caption" sx={{ color: 'text.secondary', mt: 1.5, display: 'block' }}>
                Timestamps show when each concept was first taught. "Spoken" means the
                professor named it explicitly. "Implicit" means it was inferred from context.
                Click{' '}
                <Typography
                  component={RouterLink}
                  to="/student/map"
                  variant="inherit"
                  sx={{ color: 'primary.main' }}
                >
                  Concept map
                </Typography>{' '}
                to see how these concepts connect to other lectures.
              </Typography>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Live progress ─────────────────────────────────────────────────── */}
      {showProgress && (
        <Card sx={{ mt: 0 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Live progress</Typography>
            {job ? (
              <>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  {job.stage ?? status} · {job.progress_pct}%
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={job.progress_pct}
                  sx={{ height: 6, borderRadius: 3, mt: 0.5 }}
                />
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Live from the job feed ({job.kind}).
                </Typography>
              </>
            ) : progress.data ? (
              <>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  {progress.data.stage} · {progress.data.progress_pct}%
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={progress.data.progress_pct}
                  sx={{ height: 6, borderRadius: 3, mt: 0.5 }}
                />
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Polled from the server — no job is visible in the feed.
                </Typography>
              </>
            ) : (
              <>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  No live job visible — polling for progress.
                </Typography>
                <LinearProgress sx={{ height: 6, borderRadius: 3, mt: 0.5 }} />
              </>
            )}
          </CardContent>
        </Card>
      )}

      {selected != null && status === 'error' && (
        <Typography variant="body2" sx={{ color: 'error.main', mt: 2 }}>
          Last error: {selected.error}
        </Typography>
      )}
    </Box>
  )
}
