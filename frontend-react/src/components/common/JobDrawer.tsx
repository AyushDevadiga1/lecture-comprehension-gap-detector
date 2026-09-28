import React from 'react'
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  Divider,
  LinearProgress,
  List,
  ListItem,
  Chip,
  Button,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'

import { useAppStore } from '../../store/useAppStore'
import { StatusBadge } from './StatusBadge'
import { jobs as jobsApi } from '../../api/jobs'
import { useJobList, useFeedStatus } from '../../lib/useJobFeed'

export const JobDrawer: React.FC = () => {
  const { jobDrawerOpen, setJobDrawerOpen, selectedCourseId } = useAppStore()
  // Reads the query cache. The drawer is the one component that *should* react
  // to a job tick, because it is where job progress is displayed.
  const jobs = useJobList(selectedCourseId)
  const { mode, changeToken } = useFeedStatus(selectedCourseId)
  const isConnected = mode === 'stream'

  const handleCancelJob = async (jobId: number) => {
    try {
      await jobsApi.cancel(jobId)
    } catch (err) {
      console.error('Failed to cancel job:', err)
    }
  }

  return (
    <Drawer
      anchor="right"
      open={jobDrawerOpen}
      onClose={() => setJobDrawerOpen(false)}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: 460 },
          backgroundColor: '#0f172a',
          borderLeft: '1px solid rgba(255, 255, 255, 0.08)',
          p: 3,
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            Background Tasks
          </Typography>
          <Chip
            size="small"
            label={isConnected ? 'SSE Live' : 'Disconnected'}
            color={isConnected ? 'success' : 'default'}
            variant="outlined"
            sx={{ fontSize: '0.7rem' }}
          />
        </Box>
        <IconButton onClick={() => setJobDrawerOpen(false)} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {changeToken > 0 && (
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 2 }}>
          Snapshot #{changeToken}
        </Typography>
      )}

      <Divider sx={{ mb: 2 }} />

      {jobs.length === 0 ? (
        <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
          <Typography variant="body2">No background jobs registered yet.</Typography>
          <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
            Upload a lecture or trigger graph generation to see live progress.
          </Typography>
        </Box>
      ) : (
        <List sx={{ p: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {jobs.map((job) => (
            <ListItem
              key={job.id}
              disableGutters
              sx={{
                flexDirection: 'column',
                alignItems: 'stretch',
                p: 2,
                borderRadius: 2,
                backgroundColor: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
              }}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, color: '#e2e8f0' }}>
                  #{job.id} &bull; {job.kind}
                </Typography>
                <StatusBadge status={job.status} />
              </Box>

              {job.title && (
                <Typography variant="caption" sx={{ color: '#94a3b8', mb: 1 }}>
                  {job.title} {job.course_id && `[${job.course_id}]`}
                </Typography>
              )}

              {job.stage && (
                <Typography variant="body2" sx={{ fontSize: '0.825rem', color: '#cbd5e1', mb: 1 }}>
                  Stage: <strong>{job.stage}</strong>
                  {job.detail && ` — ${job.detail}`}
                </Typography>
              )}

              {!job.terminal && (
                <Box sx={{ my: 1 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                    <Typography variant="caption" sx={{ color: '#94a3b8' }}>
                      Progress
                    </Typography>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      {job.progress_pct}%
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={job.progress_pct}
                    sx={{
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: 'rgba(255, 255, 255, 0.1)',
                      '& .MuiLinearProgress-bar': {
                        borderRadius: 3,
                        background: 'linear-gradient(90deg, #6366f1, #a855f7)',
                      },
                    }}
                  />
                </Box>
              )}

              {job.error && (
                <Typography
                  variant="caption"
                  sx={{
                    color: '#f87171',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    p: 1,
                    borderRadius: 1,
                    mt: 1,
                    display: 'block',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {job.error}
                </Typography>
              )}

              {!job.terminal && (
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
                  <Button
                    size="small"
                    color="error"
                    variant="text"
                    onClick={() => handleCancelJob(job.id)}
                    sx={{ fontSize: '0.75rem', py: 0.25 }}
                  >
                    Cancel Task
                  </Button>
                </Box>
              )}
            </ListItem>
          ))}
        </List>
      )}
    </Drawer>
  )
}
