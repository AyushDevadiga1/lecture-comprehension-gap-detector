import React from 'react'
import { Box, IconButton, TextField, Tooltip, Typography } from '@mui/material'
import BoltIcon from '@mui/icons-material/Bolt'
import { useLocation } from 'react-router-dom'
import { useAppStore } from '../../store/useAppStore'

/**
 * The top bar: where you are, which student you are, and the drawer handle.
 *
 * Deliberately thin. Course selection, theme, feed state and quota live in the
 * sidebar (one owner each), so there is exactly one copy of every control:
 * two course pickers on one screen is how a selection starts disagreeing with
 * itself.
 *
 * The breadcrumb is derived from the route rather than passed as a prop, so a
 * new view cannot ship with a stale or missing title.
 */
export const Topbar: React.FC = () => {
  const { pathname } = useLocation()
  const { studentId, setStudentId, toggleJobDrawer } = useAppStore()

  const segments = pathname.split('/').filter(Boolean)
  const label = segments.length
    ? segments.map((s) => s.replace(/-/g, ' ')).join(' / ')
    : 'overview'

  return (
    <Box
      component="header"
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        px: { xs: 2, md: 3 },
        py: 1,
        borderBottom: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'background.default',
        position: 'sticky',
        top: 0,
        zIndex: (theme) => theme.zIndex.appBar,
      }}
    >
      <Typography
        variant="caption"
        sx={{
          fontFamily: 'var(--font-mono)',
          color: 'text.secondary',
          textTransform: 'capitalize',
          letterSpacing: '0.02em',
        }}
      >
        {label}
      </Typography>

      <Box sx={{ flex: 1 }} />

      <TextField
        size="small"
        label="Student ID"
        value={studentId}
        onChange={(e) => setStudentId(e.target.value)}
        sx={{ width: 160 }}
      />

      <Tooltip title="Background tasks">
        <IconButton
          onClick={toggleJobDrawer}
          color="inherit"
          aria-label="View Background Jobs & Pipelines"
          sx={{ border: '1px solid', borderColor: 'divider' }}
        >
          <BoltIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  )
}
