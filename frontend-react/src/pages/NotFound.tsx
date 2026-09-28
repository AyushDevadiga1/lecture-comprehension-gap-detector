import React from 'react'
import { Box, Typography, Button } from '@mui/material'
import { Link } from 'react-router-dom'
import HomeIcon from '@mui/icons-material/Home'

export const NotFound: React.FC = () => {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        textAlign: 'center',
        gap: 2,
      }}
    >
      <Typography
        variant="h1"
        sx={{
          fontSize: '6rem',
          fontWeight: 900,
          background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
        }}
      >
        404
      </Typography>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Page Not Found
      </Typography>
      <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 460 }}>
        The requested URL was not found in the LecGap dashboard.
      </Typography>
      <Button
        component={Link}
        to="/student"
        variant="contained"
        startIcon={<HomeIcon />}
        sx={{ mt: 2 }}
      >
        Return to Student Portal
      </Button>
    </Box>
  )
}
