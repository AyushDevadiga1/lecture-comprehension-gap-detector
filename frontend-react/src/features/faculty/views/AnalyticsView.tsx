import React from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { courses as coursesApi } from '../../../api/courses'
import { errorMessage } from '../../../api/client'
import { invalidateCourse, queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { LoadingScreen } from '../../../components/common/LoadingScreen'
import { Rise } from '../../../components/common/Rise'
import { SectionIcon } from '../../../components/common/SectionIcon'

/**
 * Faculty analytics — the telemetry cards, the rebuild control, and the
 * prerequisite edges with their spoken evidence.
 *
 * Lifted from `FacultyDashboard` at P0. Owns `['graph', course]` (shared with
 * MapView) and `['stats', course]` (shared with Heatmap and Divergence), so the
 * three faculty routes together fetch each payload once.
 */
export const AnalyticsView: React.FC = () => {
  const queryClient = useQueryClient()
  const { selectedCourseId } = useAppStore()
  const [buildError, setBuildError] = React.useState<string | null>(null)

  const {
    data: graphData,
    isLoading: isLoadingGraph,
    error: graphError,
  } = useQuery({
    queryKey: queryKeys.graph(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.graph(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  const { data: statsData } = useQuery({
    queryKey: queryKeys.stats(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.stats(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  const buildGraphMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCourseId) throw new Error('No course selected')
      return coursesApi.buildGraph(selectedCourseId)
    },
    onSuccess: () => {
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    },
    // This had no onError once, which is why the wrong-verb bug was invisible:
    // a failed rebuild just flickered the button and said nothing.
    onError: (err: unknown) => setBuildError(errorMessage(err, 'Could not queue a graph rebuild')),
  })

  /**
   * True root concepts: nodes with in-degree 0. `topological_order` contains
   * every node, so its length is the concept count, not the root count — a bug
   * fixed in 27fed3c. With no edges, every node is effectively a root.
   */
  const rootConcepts = React.useMemo(() => {
    if (!graphData) return 0
    if (graphData.edges.length === 0) return graphData.node_count
    const hasIncoming = new Set(graphData.edges.map((e) => e.target))
    return graphData.nodes.filter((n) => !hasIncoming.has(n)).length
  }, [graphData])

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to inspect analytics.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 2,
        }}
      >
        <Box>
          <Typography variant="h4">Faculty insights: {selectedCourseId.toUpperCase()}</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
            Inspect the extracted prerequisite DAG, spoken lecture evidence, and
            taught-vs-learned divergence.
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
          {buildGraphMutation.isPending ? 'Queuing graph build...' : 'Rebuild prerequisite DAG'}
        </Button>
      </Box>

      {buildError && <ErrorAlert error={buildError} title="Graph rebuild failed" />}

      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={3}>
          <Rise delay={0}>
            <Card sx={{ p: 2, height: '100%', transition: 'border-color 0.2s ease', '&:hover': { borderColor: 'info.main' } }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                DAG structure
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: graphData?.is_dag ? 'success.main' : 'warning.main' }}>
                {graphData?.is_dag ? 'Valid DAG' : 'Cyclic / pending'}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {graphData ? `${graphData.node_count} nodes, ${graphData.edge_count} edges` : '—'}
              </Typography>
            </Card>
          </Rise>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Rise delay={0.05}>
            <Card sx={{ p: 2, height: '100%', transition: 'border-color 0.2s ease', '&:hover': { borderColor: 'info.main' } }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                Root concepts
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                {rootConcepts}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                No prerequisites (in-degree 0)
              </Typography>
            </Card>
          </Rise>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Rise delay={0.1}>
            <Card sx={{ p: 2, height: '100%', transition: 'border-color 0.2s ease', '&:hover': { borderColor: 'info.main' } }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                Comprehension gaps tracked
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: 'warning.main' }}>
                {statsData?.heatmap?.filter((h) => h.rate > 0.3)?.length ?? 0}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Concepts with &gt;30% failure rate
              </Typography>
            </Card>
          </Rise>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Rise delay={0.15}>
            <Card sx={{ p: 2, height: '100%', transition: 'border-color 0.2s ease', '&:hover': { borderColor: 'info.main' } }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                Avg. sequence divergence
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: 'info.main' }}>
                {statsData?.divergence?.length
                  ? (
                      statsData.divergence.reduce((acc, d) => acc + d.gap, 0) /
                      statsData.divergence.length
                    ).toFixed(1)
                  : '0.0'}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Step gap (taught vs learned)
              </Typography>
            </Card>
          </Rise>
        </Grid>
      </Grid>

      <Rise delay={0.2}>
        <Card>
          <CardContent sx={{ p: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
              <SectionIcon>
                <AccountTreeIcon sx={{ color: 'primary.main', fontSize: 20 }} />
              </SectionIcon>
              <Typography variant="h6">Prerequisite dependencies &amp; spoken evidence</Typography>
            </Box>

            {isLoadingGraph && <LoadingScreen message="Loading prerequisite graph..." />}
            {graphError && <ErrorAlert error={graphError} title="Failed to load DAG" />}

            {graphData && graphData.edges.length === 0 && (
              <Alert severity="warning">
                No dependency edges detected yet. Ensure lectures are ready and click
                &ldquo;Rebuild prerequisite DAG&rdquo; above.
              </Alert>
            )}

            {graphData && graphData.edges.length > 0 && (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Prerequisite (source)</TableCell>
                    <TableCell>Dependent (target)</TableCell>
                    <TableCell>Confidence</TableCell>
                    <TableCell>Extraction method</TableCell>
                    <TableCell>Spoken evidence from lecture</TableCell>
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
                                &ldquo;{edge.evidence}&rdquo;
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
      </Rise>
    </Box>
  )
}
