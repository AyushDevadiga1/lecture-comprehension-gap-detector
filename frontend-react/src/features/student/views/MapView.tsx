import React, { Suspense } from 'react'
import { Box, Skeleton, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { LoadingScreen } from '../../../components/common/LoadingScreen'

/** Loaded lazily: reactflow is ~52 KB gzipped and out of the first paint. */
const DagView = React.lazy(() =>
  import('../../../components/graph/DagView').then((m) => ({ default: m.DagView })),
)

/**
 * The concept map route.
 *
 * Owns `['graph', courseId]`; the faculty analytics view reads the same key, so
 * opening both fetches once. `key={selectedCourseId}` resets the canvas'
 * control state on a course switch — a colour-by or node-limit choice for one
 * course must never silently scope another.
 */
export const MapView: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  const {
    data: graphData,
    isLoading: isLoadingGraph,
    error: graphError,
  } = useQuery({
    queryKey: queryKeys.graph(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.graph(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Concept map</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Prerequisites sit above what they unlock. Drag to pan, scroll to zoom, click a
          concept for its links and evidence.
        </Typography>
      </Box>

      {graphError && <ErrorAlert error={graphError} title="Failed to load graph" />}
      {isLoadingGraph && <LoadingScreen message="Loading prerequisite graph..." />}
      {graphData && (
        // The chunk fallback is scoped to the graph card's own shape — a
        // skeleton, not a page-level spinner.
        <Suspense
          fallback={
            <Skeleton
              variant="rounded"
              height={480}
              role="status"
              aria-label="Loading prerequisite graph"
            />
          }
        >
          <DagView key={selectedCourseId} graph={graphData} idPrefix="student-graph" />
        </Suspense>
      )}
    </Box>
  )
}
