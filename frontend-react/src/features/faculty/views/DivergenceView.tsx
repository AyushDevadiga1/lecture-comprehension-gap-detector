import React from 'react'
import { Box, Card, CardContent, Chip, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import TrendingUpIcon from '@mui/icons-material/TrendingUp'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { LoadingScreen } from '../../../components/common/LoadingScreen'
import { SectionIcon } from '../../../components/common/SectionIcon'

/**
 * Taught-vs-learned divergence. Reads `['stats', course]` — shared with
 * Analytics and Heatmap.
 */
export const DivergenceView: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  const { data: statsData, isLoading, error } = useQuery({
    queryKey: queryKeys.stats(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.stats(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to inspect analytics.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4">Taught vs learned</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Where the order you taught and the order students actually learned in disagree.
        </Typography>
      </Box>

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <SectionIcon>
              <TrendingUpIcon sx={{ color: 'primary.main', fontSize: 20 }} />
            </SectionIcon>
            <Typography variant="h6">Order divergence</Typography>
          </Box>

          {isLoading && <LoadingScreen message="Loading divergence statistics..." />}
          {error && <ErrorAlert error={error} title="Failed to load statistics" />}

          {statsData && statsData.divergence.length === 0 && (
            <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
              No quiz attempt data yet to compute a learned sequence.
            </Typography>
          )}

          {statsData && statsData.divergence.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Concept</TableCell>
                  <TableCell align="center">Taught #</TableCell>
                  <TableCell align="center">Learned #</TableCell>
                  <TableCell align="right">Divergence gap</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {statsData.divergence.map((div, idx) => (
                  <TableRow key={idx} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{div.concept}</TableCell>
                    <TableCell align="center">
                      {div.taught_idx !== undefined ? div.taught_idx + 1 : '—'}
                    </TableCell>
                    <TableCell align="center">
                      {div.learned_idx !== undefined ? div.learned_idx + 1 : '—'}
                    </TableCell>
                    <TableCell align="right">
                      <Chip
                        label={`Δ ${div.gap}`}
                        size="small"
                        color={div.gap > 3 ? 'warning' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
