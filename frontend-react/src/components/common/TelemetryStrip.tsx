import React from 'react'
import { Card, Grid, Typography } from '@mui/material'
import type { CourseGraphOut, CourseStats } from '../../api/types'
import { Rise } from './Rise'
import { averageDivergence, gapCount, rootConceptCount } from '../../lib/telemetry'

/**
 * The faculty telemetry strip — the four summary cards that head Analytics.
 *
 * Extracted at P4 so the strip is testable on its own (`TelemetryStrip.test.ts`)
 * and reusable. The three subtle numbers live in `lib/telemetry.ts` as pure
 * functions; this file is the presentation half.
 */
export interface TelemetryStripProps {
  graph: CourseGraphOut | null
  stats: CourseStats | null
}

export const TelemetryStrip: React.FC<TelemetryStripProps> = ({ graph, stats }) => {
  const roots = rootConceptCount(graph)
  const gaps = gapCount(stats)
  const divergence = averageDivergence(stats)

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} sm={6} md={3}>
        <Rise delay={0}>
          <Card sx={{ p: 2, height: '100%', transition: 'border-color 0.2s ease', '&:hover': { borderColor: 'info.main' } }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
              DAG structure
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, fontVariantNumeric: 'tabular-nums', color: graph?.is_dag ? 'success.main' : 'warning.main' }}>
              {graph?.is_dag ? 'Valid DAG' : 'Cyclic / pending'}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {graph ? `${graph.node_count} nodes, ${graph.edge_count} edges` : '—'}
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
              {roots}
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
              {gaps}
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
              {divergence}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Step gap (taught vs learned)
            </Typography>
          </Card>
        </Rise>
      </Grid>
    </Grid>
  )
}
