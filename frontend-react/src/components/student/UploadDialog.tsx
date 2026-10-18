import React, { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  LinearProgress,
  TextField,
  Typography,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import { useQueryClient } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../api/lectures'
import { errorMessage } from '../../api/client'
import { invalidateCourse } from '../../lib/queryKeys'
import { findDuplicate } from '../../lib/lectureTriage'
import type { LectureOut } from '../../api/types'
import { ErrorAlert } from '../common/ErrorAlert'

export interface UploadDialogProps {
  open: boolean
  onClose: () => void
  courseId: string
  /**
   * The course's lectures, for the duplicate guard. Passed in rather than
   * fetched: the caller already has the list, and a dialog that opened its own
   * `['lectures']` query would be a second request for data on screen behind it.
   */
  lectures: readonly LectureOut[]
}

/**
 * Upload a lecture — a dialog, not a card on the page.
 *
 * The approved layout moves ingestion off the dashboard: uploading is an
 * occasional action, and a permanently visible form competes with the content
 * the page exists to show.
 *
 * Two behaviours travel with it, both from `frontend/panels/ingest.py`:
 *
 *  1. **The duplicate guard.** `findDuplicate` matches the file stem against the
 *     course's lecture titles. A duplicate warns and blocks submit until
 *     acknowledged — and the acknowledgement is per-filename, so choosing a
 *     different file re-arms the guard. An ack that survived a file change would
 *     protect nothing.
 *  2. **Two-step upload.** `POST /lectures` creates the row, then the media
 *     streams with real progress. The bar is indeterminate until bytes are
 *     measurable, because a frozen 0% reads as *stalled*.
 */
export const UploadDialog: React.FC<UploadDialogProps> = ({ open, onClose, courseId, lectures }) => {
  const queryClient = useQueryClient()

  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [ack, setAck] = useState(false)
  const [progress, setProgress] = useState<number | 'streaming' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const duplicateId = findDuplicate(lectures, courseId, file?.name)
  const busy = progress !== null
  const canSubmit = !!file && !!title.trim() && !busy && (duplicateId == null || ack)

  const reset = () => {
    setTitle('')
    setFile(null)
    setAck(false)
    setProgress(null)
    setError(null)
  }

  const close = () => {
    // Never leave a half-finished state behind: the next open starts clean.
    reset()
    onClose()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || !file) return

    setError(null)
    setProgress('streaming')
    try {
      const lecture = await lecturesApi.create({ course_id: courseId, title: title.trim() })
      await lecturesApi.uploadMedia(lecture.id, file, (pct) =>
        setProgress(pct === null ? 'streaming' : pct),
      )
      invalidateCourse(queryClient, courseId)
      close()
    } catch (err: unknown) {
      setError(errorMessage(err, 'Upload failed'))
      setProgress(null)
    }
  }

  return (
    <Dialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <Box component="form" onSubmit={handleSubmit}>
        <DialogTitle sx={{ fontWeight: 600 }}>Upload lecture</DialogTitle>
        <DialogContent dividers>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Lecture title"
              placeholder="e.g. Lecture 1 — Introduction to Vectors"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              size="small"
              required
              fullWidth
              autoFocus
            />

            <Button
              variant="outlined"
              component="label"
              sx={{
                p: 1.5,
                borderStyle: 'dashed',
                borderColor: file ? 'primary.main' : 'divider',
              }}
            >
              {file ? file.name : 'Select Video / Audio File (.mp4, .mp3, .wav)'}
              <input
                type="file"
                hidden
                accept="video/*,audio/*"
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null)
                  // An ack is per-filename: another file must re-arm the guard.
                  setAck(false)
                }}
              />
            </Button>

            {duplicateId != null && (
              <Box>
                <Alert severity="warning" sx={{ mb: 1 }}>
                  A lecture in this course already looks like this file (#{duplicateId}).
                  Uploading will create a second row.
                </Alert>
                <FormControlLabel
                  control={
                    <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} size="small" />
                  }
                  label="Upload anyway (I know it's a duplicate)"
                />
              </Box>
            )}

            {progress !== null && (
              <Box>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                  <Typography variant="caption">Uploading media stream...</Typography>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>
                    {progress === 'streaming' ? 'Uploading…' : `${progress}%`}
                  </Typography>
                </Box>
                <LinearProgress
                  variant={progress === 'streaming' ? 'indeterminate' : 'determinate'}
                  value={typeof progress === 'number' ? progress : 0}
                  sx={{ height: 6, borderRadius: 3 }}
                />
              </Box>
            )}

            {error && <ErrorAlert error={error} title="Upload failed" />}
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button type="button" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={!canSubmit} startIcon={<CloudUploadIcon />}>
            Upload &amp; transcribe
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  )
}
