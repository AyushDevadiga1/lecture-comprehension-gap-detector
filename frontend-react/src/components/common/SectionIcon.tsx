import React from 'react'
import { Box } from '@mui/material'
import { tint } from '../../theme/alpha'

type Tone = 'info' | 'warn' | 'error' | 'success'

interface SectionIconProps {
  /** Which status token tints the tile — matches the icon it frames. */
  tone?: Tone
  children: React.ReactNode
}

/**
 * The rounded wash every dashboard section header sits in.
 *
 * One motif, used at every card title, is most of what makes a set of panels
 * read as a designed system rather than as separately-styled tables: the same
 * 34px tile, the same 10px radius, the same token-derived wash at every
 * section. Wash *and* border come from `tint()`, so it re-derives per theme
 * base — a hardcoded pale-blue tile would be the exact bug `REACT_ARCHITECTURE`
 * §4 exists to prevent.
 */
export const SectionIcon: React.FC<SectionIconProps> = ({ tone = 'info', children }) => (
  <Box
    sx={{
      width: 34,
      height: 34,
      flexShrink: 0,
      borderRadius: '10px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: tint(tone, 12),
      border: `1px solid ${tint(tone, 24)}`,
    }}
  >
    {children}
  </Box>
)
