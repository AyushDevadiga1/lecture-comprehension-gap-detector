import React from 'react'
import { Box, Card, CardContent, LinearProgress, Typography } from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { LoadingScreen } from '../../../components/common/LoadingScreen'
import { SectionIcon } from '../../../components/common/SectionIcon'
import { gradient, tint } from '../../../theme/alpha'

/**
 * The confusion heatmap. Reads `['stats', course]` — shared with Analytics and
 * Divergence, so navigating between the three faculty routes fetches once.
 */
export const HeatmapView: React.FC = () => {
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
        <Typography variant="h4">Comprehension heatmap</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Wrong-answer rate per concept, highest first — with the counts behind every bar, so
          a single attempt never reads as a pattern.
        </Typography>
      </Box>

      <Card>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <SectionIcon tone="warn">
              <WarningAmberIcon sx={{ color: 'warning.main', fontSize: 20 }} />
            </SectionIcon>
            <Typography variant="h6">Wrong-answer rates</Typography>
          </Box>

          {isLoading && <LoadingScreen message="Loading divergence statistics..." />}
          {error && <ErrorAlert error={error} title="Failed to load statistics" />}

          {statsData && statsData.heatmap.length === 0 && (
            <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
              No concept failure metrics yet — students must submit a quiz first.
            </Typography>
          )}

          {statsData && statsData.heatmap.length > 0 && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {statsData.heatmap.map((item, idx) => {
                const pct = Math.round(item.rate * 100)
                return (
                  <Box key={idx}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {item.concept}
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: pct > 40 ? 'error.main' : 'text.secondary', fontWeight: 600 }}
                      >
                        {item.wrong} / {item.attempts} missed ({pct}%)
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={pct}
                      sx={{
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: tint('text', 8),
                        '& .MuiLinearProgress-bar': {
                          borderRadius: 4,
                          background: pct > 50 ? gradient('warn', 'bad') : gradient('info', 'ok'),
                        },
                      }}
                    />
                  </Box>
                )
              })}
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
