import React, { useState } from 'react'
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  Chip,
  Tooltip,
  LinearProgress,
  Alert,
} from '@mui/material'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import TrendingUpIcon from '@mui/icons-material/TrendingUp'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { useAppStore } from '../../store/useAppStore'
import { LoadingScreen } from '../../components/common/LoadingScreen'
import { ErrorAlert } from '../../components/common/ErrorAlert'
import { queryKeys, invalidateCourse } from '../../lib/queryKeys'
import { errorMessage } from '../../api/client'
import { gradient } from '../../theme/alpha'

export const FacultyDashboard: React.FC = () => {
  const queryClient = useQueryClient()
  const [buildError, setBuildError] = useState<string | null>(null)
  const { selectedCourseId } = useAppStore()

  // Fetch Course Graph
  const {
    data: graphData,
    isLoading: isLoadingGraph,
    error: graphError,
  } = useQuery({
    queryKey: queryKeys.graph(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.graph(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  // Fetch Course Stats (Heatmap + Divergence)
  const {
    data: statsData,
    isLoading: isLoadingStats,
    error: statsError,
  } = useQuery({
    queryKey: queryKeys.stats(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.stats(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  // Mutation to build DAG
  const buildGraphMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCourseId) throw new Error('No course selected')
      return coursesApi.buildGraph(selectedCourseId)
    },
    onSuccess: () => {
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    },
    // This had no onError, which is why the wrong-verb bug was invisible: a
    // failed rebuild just flickered the button and said nothing.
    onError: (err: unknown) => setBuildError(errorMessage(err, 'Could not queue a graph rebuild')),
  })

  if (!selectedCourseId) {
    return (
      <Alert severity="info" sx={{ mt: 4 }}>
        Please select a course to inspect pedagogical analytics.
      </Alert>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Top Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 800 }}>
            Faculty Insights: {selectedCourseId.toUpperCase()}
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
            Inspect the extracted prerequisite DAG, spoken lecture evidence, and taught-vs-learned divergence.
          </Typography>
        </Box>

        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={() => {
            setBuildError(null)
            buildGraphMutation.mutate()
          }}
          disabled={buildGraphMutation.isPending}
        >
          {buildGraphMutation.isPending ? 'Queuing Graph Build...' : 'Rebuild Prerequisite DAG'}
        </Button>
      </Box>

      {buildError && <ErrorAlert error={buildError} title="Graph rebuild failed" />}

      {/* Metric Cards */}
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ p: 2 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              DAG Structure
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5, color: graphData?.is_dag ? 'success.main' : 'warning.main' }}>
              {graphData?.is_dag ? 'Valid DAG' : 'Cyclic / Pending'}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {graphData ? `${graphData.node_count} nodes, ${graphData.edge_count} edges` : '—'}
            </Typography>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ p: 2 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Topological Root Concepts
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5 }}>
              {graphData?.topological_order?.length ?? 0}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Prerequisite sequence
            </Typography>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ p: 2 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Comprehension Gaps Tracked
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5, color: 'warning.main' }}>
              {statsData?.heatmap?.filter((h) => h.rate > 0.3)?.length ?? 0}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Concepts with &gt;30% failure rate
            </Typography>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ p: 2 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Avg. Sequence Divergence
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5, color: 'info.main' }}>
              {statsData?.divergence?.length
                ? (statsData.divergence.reduce((acc, d) => acc + d.gap, 0) / statsData.divergence.length).toFixed(1)
                : '0.0'}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Step gap (taught vs learned)
            </Typography>
          </Card>
        </Grid>
      </Grid>

      {/* DAG Edges with Spoken Evidence */}
      <Card>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <AccountTreeIcon sx={{ color: 'primary.light' }} />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Prerequisite Dependencies &amp; Spoken Evidence
            </Typography>
          </Box>

          {isLoadingGraph && <LoadingScreen message="Loading prerequisite graph..." />}
          {graphError && <ErrorAlert error={graphError} title="Failed to load DAG" />}

          {graphData && graphData.edges.length === 0 && (
            <Alert severity="warning">
              No dependency edges detected yet. Ensure lectures are ready and click "Rebuild Prerequisite DAG" above.
            </Alert>
          )}

          {graphData && graphData.edges.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Prerequisite (Source)</TableCell>
                  <TableCell>Dependent (Target)</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Extraction Method</TableCell>
                  <TableCell>Spoken Evidence from Lecture</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {graphData.edges.map((edge, idx) => (
                  <TableRow key={idx} hover>
                    <TableCell sx={{ fontWeight: 600, color: 'secondary.light' }}>
                      {edge.source}
                    </TableCell>
                    <TableCell sx={{ fontWeight: 600, color: 'primary.light' }}>
                      {edge.target}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={`${Math.round(edge.confidence * 100)}%`}
                        size="small"
                        color={edge.confidence > 0.8 ? 'success' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell sx={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {edge.source_method}
                    </TableCell>
                    <TableCell sx={{ maxWidth: 360 }}>
                      {edge.evidence ? (
                        <Tooltip title={edge.evidence} arrow placement="top">
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'pointer' }}>
                            <Typography
                              variant="body2"
                              sx={{
                                color: 'text.secondary',
                                fontSize: '0.82rem',
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                maxWidth: 320,
                              }}
                            >
                              "{edge.evidence}"
                            </Typography>
                            <HelpOutlineIcon sx={{ fontSize: 14, color: 'primary.light' }} />
                          </Box>
                        </Tooltip>
                      ) : (
                        <Typography variant="caption" sx={{ color: 'text.disabled' }}>
                          —
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Taught vs. Learned Divergence & Heatmap */}
      <Grid container spacing={3}>
        {/* Divergence Table */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
                <TrendingUpIcon sx={{ color: 'secondary.light' }} />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  Taught vs. Learned Order Divergence
                </Typography>
              </Box>

              {isLoadingStats && <LoadingScreen message="Loading divergence statistics..." />}
              {statsError && <ErrorAlert error={statsError} title="Failed to load statistics" />}

              {statsData && statsData.divergence.length === 0 && (
                <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
                  No quiz attempt data available yet to compute student mastery sequence.
                </Typography>
              )}

              {statsData && statsData.divergence.length > 0 && (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Concept</TableCell>
                      <TableCell align="center">Taught #</TableCell>
                      <TableCell align="center">Learned #</TableCell>
                      <TableCell align="right">Divergence Gap</TableCell>
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
        </Grid>

        {/* Heatmap of Comprehension Failures */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
                <WarningAmberIcon sx={{ color: 'warning.light' }} />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  Comprehension Gap Heatmap
                </Typography>
              </Box>

              {statsData && statsData.heatmap.length === 0 && (
                <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
                  No concept failure metrics available yet.
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
                          <Typography variant="caption" sx={{ color: pct > 40 ? 'error.main' : 'text.secondary', fontWeight: 600 }}>
                            {item.wrong} / {item.attempts} missed ({pct}%)
                          </Typography>
                        </Box>
                        <LinearProgress
                          variant="determinate"
                          value={pct}
                          sx={{
                            height: 8,
                            borderRadius: 4,
                            backgroundColor: 'rgba(255, 255, 255, 0.08)',
                            '& .MuiLinearProgress-bar': {
                              borderRadius: 4,
                              background:
                                pct > 50
                                  ? gradient('warn', 'bad')
                                  : gradient('info', 'ok'),
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
        </Grid>
      </Grid>
    </Box>
  )
}
