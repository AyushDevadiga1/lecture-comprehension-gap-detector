import React from 'react'
import { Alert, AlertTitle, Button, Box } from '@mui/material'
import { tint } from '../../theme/alpha'

interface ErrorAlertProps {
  error: Error | string | null
  title?: string
  onRetry?: () => void
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({
  error,
  title = 'API Error',
  onRetry,
}) => {
  if (!error) return null

  const message = typeof error === 'string' ? error : error.message

  return (
    <Alert
      severity="error"
      sx={{
        mb: 3,
        // `bad`, not a hardcoded red. `severity="error"` already paints
        // from `palette.error.main`, which is the `bad` token — so this used to
        // overlay a different red on top of MUI's own, and drifted from it
        // whenever the palette moved. `tint()` keeps the alpha and loses the
        // second palette.
        border: `1px solid ${tint('bad', 30)}`,
        backgroundColor: tint('bad', 10),
        backdropFilter: 'blur(8px)',
      }}
      action={
        onRetry && (
          <Button color="inherit" size="small" onClick={onRetry}>
            Retry
          </Button>
        )
      }
    >
      <AlertTitle sx={{ fontWeight: 600 }}>{title}</AlertTitle>
      <Box sx={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
        {message}
      </Box>
    </Alert>
  )
}
