import React from 'react'
import { Alert, AlertTitle, Button, Box } from '@mui/material'

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
        border: '1px solid rgba(239, 68, 68, 0.3)',
        backgroundColor: 'rgba(239, 68, 68, 0.1)',
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
