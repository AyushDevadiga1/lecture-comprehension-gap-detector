import React, { useState } from 'react'
import { Box, Card, CardContent, MenuItem, Select, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { StatusBadge } from '../../../components/common/StatusBadge'

/**
 * Per-lecture detail.
 *
 * P0 version: the lecture picker and the status facts the API already returns.
 * The coverage timeline (ported from the Python `lecture_html`) and the live
 * progress card land in P2 — this route exists now so navigation is complete,
 * and it deliberately does not pretend to show a timeline it does not have.
 */
export const LectureDetailView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const [lectureId, setLectureId] = useState<number | null>(null)

  const { data: lectureList = [] } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  const selected = lectureList.find((l) => l.id === lectureId) ?? lectureList[0] ?? null

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
              <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1 }}>
                The coverage timeline and the live progress card arrive with the P2 port of
                the Python timeline renderer.
              </Typography>
            </Box>
          ) : (
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 2 }}>
              This course has no lectures yet. Upload one from the Lectures view.
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
