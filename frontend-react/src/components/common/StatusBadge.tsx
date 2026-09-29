import React from 'react'
import { Chip, Box } from '@mui/material'
import type { JobStatus } from '../../api/types'

interface StatusBadgeProps {
  status: JobStatus | string
  size?: 'small' | 'medium'
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'small' }) => {
  const norm = status.toLowerCase()

  let color: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' = 'default'
  let label = status
  let isPulsing = false

  switch (norm) {
    case 'running':
    case 'transcribing':
      color = 'info'
      isPulsing = true
      break
    case 'ready':
    case 'completed':
      color = 'success'
      break
    case 'queued':
    case 'uploaded':
      color = 'warning'
      break
    case 'error':
      color = 'error'
      break
    case 'orphaned':
      color = 'secondary'
      label = 'orphaned (recovered)'
      break
    default:
      color = 'default'
  }

  return (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
      {isPulsing && (
        <Box
          className="pulse-indicator"
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: 'info.main',
          }}
        />
      )}
      <Chip
        label={label}
        size={size}
        color={color}
        variant={norm === 'ready' ? 'filled' : 'outlined'}
        sx={{
          fontWeight: 600,
          fontSize: '0.75rem',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      />
    </Box>
  )
}
