import React from 'react'
import { Box, CircularProgress, Typography } from '@mui/material'

interface LoadingScreenProps {
  message?: string
}

export const LoadingScreen: React.FC<LoadingScreenProps> = ({
  message = 'Loading data...',
}) => {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '40vh',
        gap: 2,
      }}
    >
      <CircularProgress
        size={44}
        thickness={4}
        sx={{
          color: 'primary.main',
          '& .MuiCircularProgress-circle': {
            strokeLinecap: 'round',
          },
        }}
      />
      <Typography variant="body2" sx={{ color: 'text.secondary', fontWeight: 500 }}>
        {message}
      </Typography>
    </Box>
  )
}
