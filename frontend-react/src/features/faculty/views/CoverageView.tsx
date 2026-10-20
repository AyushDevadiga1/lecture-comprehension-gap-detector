import React, { useState } from 'react'
import { Box, Card, CardContent, MenuItem, Select, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { StatusBadge } from '../../../components/common/StatusBadge'
import { CoverageTimeline } from '../../../components/common/CoverageTimeline'

/**
 * Faculty lecture coverage — the second consumer of `CoverageTimeline`.
 *
 * P4 per `revamp-plan/04-phases.md`: the stub's "arrives with the P2 port" copy
 * is gone. The faculty route mounts the same component the student lecture-detail
 * route mounts, which is the proof the extraction was worth doing — one timeline
 * implementation, two routes, no fork.
 *
 * Reads `['lectures', course]` for the picker and `['lecture', id]` for the
 * detail, the same keys the student views use, so a lecture opened on both sides
 * is one cache entry.
 */
export const CoverageView: React.FC = () => {
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
  const showTimeline = selected != null && status === 'ready' && detail != null

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to inspect analytics.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4">Lecture coverage</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          How much of the spoken lecture the extracted concepts actually pin down.
        </Typography>
      </Box>

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
            Lecture
          </Typography>
          <Select
            size="small"
            fullWidth
            value={selected?.id ?? ''}
            onChange={(e) => setLectureId(Number(e.target.value))}
          >
            {lectureList.map((lec) => (
              <MenuItem key={lec.id} value={lec.id}>
                #{lec.id} — {lec.title}
              </MenuItem>
            ))}
          </Select>

          {selected ? (
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
          ) : (
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 2 }}>
              This course has no lectures yet.
            </Typography>
          )}
        </CardContent>
      </Card>

      {showTimeline && (
        <Card>
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

      {selected != null && status === 'error' && (
        <Typography variant="body2" sx={{ color: 'error.main', mt: 2 }}>
          Last error: {selected.error}
        </Typography>
      )}
    </Box>
  )
}
