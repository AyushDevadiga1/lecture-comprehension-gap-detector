import React, { useState } from 'react'
import { Box, Card, CardContent, MenuItem, Select, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { StatusBadge } from '../../../components/common/StatusBadge'

/**
 * Faculty lecture coverage.
 *
 * P0 version: the lecture picker over the same `['lectures', course]` key the
 * student views use. The coverage timeline itself is shared with the student
 * lecture-detail route and arrives with the P2 port.
 */
export const CoverageView: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const [lectureId, setLectureId] = useState<number | null>(null)

  const { data: lectureList = [] } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to inspect analytics.</Typography>
  }

  const selected = lectureList.find((l) => l.id === lectureId) ?? lectureList[0] ?? null

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
            <Box sx={{ mt: 2 }}>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                <StatusBadge status={selected.status} />
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  {selected.has_media ? 'media on the server' : 'no media on the server'}
                </Typography>
              </Box>
              <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1.5 }}>
                The coverage timeline arrives with the P2 port of the Python timeline
                renderer, and is shared with the student lecture-detail view.
              </Typography>
            </Box>
          ) : (
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 2 }}>
              This course has no lectures yet.
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
