import React from 'react'
import {
  Alert,
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
import { useActiveJobs, useFeedStatus } from '../../lib/useJobFeed'
import { jobGuidance } from '../../lib/stages'
import { EXPIRED_MESSAGE, STALLED_MESSAGE, jobHealth } from '../../lib/jobStalls'
import { useNow } from '../../lib/useNow'
import { gradient, tint } from '../../theme/alpha'

export const JobDrawer: React.FC = () => {
  const { jobDrawerOpen, setJobDrawerOpen, selectedCourseId } = useAppStore()
  // Reads the query cache. The drawer is the one component that *should* react
  // to a job tick, because it is where job progress is displayed.
  //
  // Live jobs only: §1 requires a terminal job to leave this view after one
  // render. Completions are announced once by <JobCompletionHost> instead, so
  // the drawer no longer accumulates finished jobs for the whole session.
  const jobs = useActiveJobs(selectedCourseId)
  const { mode, changeToken } = useFeedStatus(selectedCourseId)
  const isConnected = mode === 'stream'

  // Ticks only while a job is in flight, so a dead worker — whose frozen
  // heartbeat stops the SSE stream entirely — can still be called out.
  const now = useNow(jobs.length > 0)

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
          backgroundColor: 'background.paper',
          borderLeft: '1px solid',
          borderColor: 'divider',
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
          {jobs.map((job) => {
            const health = jobHealth(job, now)
            return (
            <ListItem
              key={job.id}
              disableGutters
              sx={{
                flexDirection: 'column',
                alignItems: 'stretch',
                p: 2,
                borderRadius: 2,
                backgroundColor: tint('surface-alt', 40),
                border: '1px solid',
                borderColor: 'divider',
              }}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                  #{job.id} &bull; {job.kind}
                </Typography>
                <StatusBadge status={job.status} />
              </Box>

              {job.title && (
                <Typography variant="caption" sx={{ color: 'text.secondary', mb: 1 }}>
                  {job.title} {job.course_id && `[${job.course_id}]`}
                </Typography>
              )}

              {job.stage && (
                <Typography variant="body2" sx={{ fontSize: '0.825rem', color: 'text.primary', mb: 1 }}>
                  {jobGuidance(job.stage, health.elapsedS)}
                  {job.detail && ` — ${job.detail}`}
                </Typography>
              )}

              {health.health === 'stalled' && (
                <Alert severity="warning" sx={{ mb: 1, fontSize: '0.8rem' }}>
                  {STALLED_MESSAGE}
                </Alert>
              )}

              {health.health === 'expired' && (
                <Alert severity="info" sx={{ mb: 1, fontSize: '0.8rem' }}>
                  {EXPIRED_MESSAGE}
                </Alert>
              )}

              {!job.terminal && (
                <Box sx={{ my: 1 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
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
                      backgroundColor: 'divider',
                      '& .MuiLinearProgress-bar': {
                        borderRadius: 3,
                        background: gradient('info', 'accent'),
                      },
                    }}
                  />
                </Box>
              )}

              {job.error && (
                <Typography
                  variant="caption"
                  sx={{
                    color: 'error.main',
                    backgroundColor: tint('bad', 10),
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

              {!job.terminal && health.health !== 'expired' && (
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
            )
          })}
        </List>
      )}
    </Drawer>
  )
}

