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
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 3 }}>
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Displacement, per concept
                </Typography>
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
              </Box>

              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Taught vs learned, side by side
                </Typography>
                <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
                  <Box>
                    <Typography
                      variant="caption"
                      sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', display: 'block', mb: 0.5 }}
                    >
                      Taught
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {(statsData.taught_order ?? []).map((concept, idx) => (
                        <Box key={idx} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          <Typography sx={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'text.secondary', minWidth: 20 }}>
                            {idx + 1}
                          </Typography>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                            {concept}
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                  <Box>
                    <Typography
                      variant="caption"
                      sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', display: 'block', mb: 0.5 }}
                    >
                      Learned
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {(statsData.learned_order ?? []).map((concept, idx) => (
                        <Box key={idx} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          <Typography sx={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'text.secondary', minWidth: 20 }}>
                            {idx + 1}
                          </Typography>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                            {concept}
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                </Box>
              </Box>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
