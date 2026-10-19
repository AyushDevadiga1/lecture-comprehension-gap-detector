import React, { useState } from 'react'
import { Box, Card, CardContent, LinearProgress, MenuItem, Select, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { queryKeys } from '../../../lib/queryKeys'
import { useLectureProgress } from '../../../lib/useLectureProgress'
import { useActiveJobs } from '../../../lib/useJobFeed'
import { useAppStore } from '../../../store/useAppStore'
import { StatusBadge } from '../../../components/common/StatusBadge'
import { CoverageTimeline } from '../../../components/common/CoverageTimeline'

/**
 * Per-lecture detail.
 *
 * P0 version: the lecture picker and the status facts the API already returns.
 * P2.3 lands here: the coverage timeline ported from `frontend/render.py::
 * lecture_html`, and the live progress card.
 *
 * Request budget per `revamp-plan/02-backend-map.md` §5: one `GET /lectures/{id}`
 * for the detail, and `GET /lectures/{id}/progress` only while the lecture is
 * transcribing and no job for it is visible in the feed.
 */
export const LectureDetailView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const [lectureId, setLectureId] = useState<number | null>(null)

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
          Coverage, transcript evidence and processing state for one lecture.
        </Typography>
      </Box>

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
