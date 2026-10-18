import React from 'react'
import { Box, Typography } from '@mui/material'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { errorMessage } from '../../../api/client'
import { queryKeys, invalidateCourse } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ClipBrowser } from '../ClipBrowser'

/**
 * The clip library route.
 *
 * Owns `['lectures', courseId]` — the same key LecturesView uses, so the list is
 * fetched once per course. The clip list itself is loaded per selected lecture
 * inside `ClipBrowser` (keyed by lecture, not course).
 */
export const ClipsView: React.FC = () => {
  const queryClient = useQueryClient()
  const { selectedCourseId } = useAppStore()

  const { data: lectureList = [] } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  const handleCutClips = async (lectureId: number) => {
    try {
      await lecturesApi.cutClips(lectureId)
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      // The browser shows its own per-lecture error; a failed cut here is not
      // worth a page-level banner, but it must not be silent either.
      console.error(errorMessage(err, 'Could not start clip cutting'))
    }
  }

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Clips</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Every concept clip cut for a lecture, playable in the browser.
        </Typography>
      </Box>
      <ClipBrowser lectures={lectureList} onCutClips={handleCutClips} />
    </Box>
  )
}
