import React from 'react'
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import type { ConceptOut, SegmentOut } from '../../api/types'
import { buildTimelineModel } from '../../lib/coverageTimeline'
import { token } from '../../theme/alpha'

/**
 * The lecture coverage timeline, ported from `frontend/render.py::
 * lecture_html` (the Streamlit era's static SVG island).
 *
 * What it shows, exactly as the Python drew it: a track bar with transcript
 * ticks, one green rect per *merged* covered run (not per concept — merging
 * overlapping and touching windows is what keeps the lecture's real gaps
 * visible and the percentage honest), one coloured band per concept in taught
 * order with a teal→coral ramp that matches the DAG, a coverage percentage
 * where the number is `merged union / duration` — never a sum of concept
 * lengths — and a table of concept → window → the spoken sentence the quiz
 * grades against.
 *
 * Fidelity lives in `lib/coverageTimeline.ts` (payload in, model out, golden
 * numbers measured from the Python); this file is the presentation half:
 * geometry constants, `var(--lgc-*)` chrome, and MUI table slots. Two notes
 * where a React port is allowed to differ from the HTML island:
 *
 * - the SVG's band labels keep the Python's Arial; the surrounding page uses
 *   the app's typography (Newsreader / Plus Jakarta Sans) instead of the
 *   island's Arial body, because this is a React citizen, not an iframe;
 * - the SVG carries an accessible name (`aria-label`), which the bare
 *   `role="img"` Python never had.
 */
export interface CoverageTimelineProps {
  segments?: readonly SegmentOut[] | null
  concepts?: readonly ConceptOut[] | null
  title?: string
  width?: number
}

// SVG geometry, byte-pinned against the Python render. The track sits at
// y=40 (10 tall, rx 5), ticks hang under it (y=42, 2×6), covered runs paint
// over it (y=40, 10 tall, rx 2, opacity 0.75), then one 14-tall band per
// concept. Band tops (58 + 26 · index), the axis labels (y=78; the right one
// at width − 40) and the svg height (78 + 27 · drawn bands) are computed in
// `lib/coverageTimeline.ts` — the parts the golden tests measure.
const TRACK_Y = 40
const TRACK_HEIGHT = 10
const TRACK_RX = 5
const TICK_Y = 42
const TICK_HEIGHT = 6
const TICK_WIDTH = 2
const COVERED_HEIGHT = 10
const COVERED_RX = 2
const COVERED_OPACITY = 0.75
const BAND_HEIGHT = 14
const BAND_RX = 3
const AXIS_Y = 78
const SVG_LABEL_FONT = 11

export const CoverageTimeline: React.FC<CoverageTimelineProps> = ({
  segments,
  concepts,
  title = '',
  width = 1000,
}) => {
  const model = buildTimelineModel(segments, concepts, title, width)
  const svgFont = 'Arial, sans-serif'

  return (
    <Box sx={{ maxWidth: width }}>
      <Box component="h5" sx={{ margin: 0 }}>
        {model.title}
      </Box>
      {/* The honest percentage: bolded, measured from the merged union. */}
      <Typography
        sx={{ fontSize: 13, margin: '2px 0 8px', color: 'text.secondary' }}
      >
        {`${model.nConcepts} concepts · ${model.nSegments} transcript segments · `}
        <Box component="b">{model.captionBold}</Box>
        {` by extracted concepts (${model.coveredText}s of ${model.durationText}s).`}
      </Typography>

      <svg
        role="img"
        aria-label="Lecture coverage timeline"
        viewBox={`0 0 ${model.width} ${model.svgHeight}`}
        width="100%"
        height={model.svgHeight}
      >
        {/* The "not covered yet" track the runs paint over. */}
        <rect
          x={0}
          y={TRACK_Y}
          width={model.width}
          height={TRACK_HEIGHT}
          rx={TRACK_RX}
          fill={token('track')}
        />
        {/* Transcript ticks: one per segment start. */}
        {model.ticks.map((tick, i) => (
          <rect
            key={`tick-${i.toString()}`}
            x={tick.x}
            y={TICK_Y}
            width={TICK_WIDTH}
            height={TICK_HEIGHT}
            fill={token('tick')}
          />
        ))}
        {/* Covered runs: ONE rect per merged run, so gaps stay gaps. */}
        {model.coveredRects.map((run, i) => (
          <rect
            key={`run-${i.toString()}`}
            x={run.x}
            y={TRACK_Y}
            width={run.width}
            height={COVERED_HEIGHT}
            rx={COVERED_RX}
            fill={token('covered')}
            opacity={COVERED_OPACITY}
          >
            <title>{run.title}</title>
          </rect>
        ))}
        {/* Concept bands in taught order, labels inside their own fill's ink. */}
        {model.bands.map((band, i) => (
          <React.Fragment key={`band-${i.toString()}`}>
            <rect
              x={band.x}
              y={band.top}
              width={band.width}
              height={BAND_HEIGHT}
              rx={BAND_RX}
              fill={band.fill}
            >
              <title>{band.title}</title>
            </rect>
            <text
              x={band.labelX}
              y={band.labelY}
              fontFamily={svgFont}
              fontSize={SVG_LABEL_FONT}
              fill={band.ink}
            >
              {band.name}
            </text>
          </React.Fragment>
        ))}
        <text
          x={model.axisStart.x}
          y={AXIS_Y}
          fontFamily={svgFont}
          fontSize={SVG_LABEL_FONT}
          fill={token('muted')}
        >
          {model.axisStart.text}
        </text>
        <text
          x={model.axisEnd.x}
          y={AXIS_Y}
          fontFamily={svgFont}
          fontSize={SVG_LABEL_FONT}
          fill={token('muted')}
          textAnchor="start"
        >
          {model.axisEnd.text}
        </text>
      </svg>

      {/* Concept → window → quiz-answer evidence. Every concept appears,
          drawn or skipped, with an em-dash standing in for what never parsed
          or nothing grounded it — the same honest rows the Python table had. */}
      <Table
        size="small"
        sx={{ marginTop: '10px', fontSize: '12.5px' }}
      >
        <TableHead>
          <TableRow sx={{ textAlign: 'left', backgroundColor: token('surface_alt') }}>
            <TableCell>#</TableCell>
            <TableCell>Concept</TableCell>
            <TableCell>Window</TableCell>
            <TableCell>Quiz-answer evidence (spoken sentence)</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {model.rows.map((row) => (
            <TableRow key={row.index}>
              <TableCell>{row.index}</TableCell>
              <TableCell>{row.name}</TableCell>
              <TableCell>{row.window}</TableCell>
              <TableCell>{row.support}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )
}
