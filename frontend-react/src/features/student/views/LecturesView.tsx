import React, { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../../api/lectures'
import { courses as coursesApi } from '../../../api/courses'
import { errorMessage } from '../../../api/client'
import { queryKeys, invalidateCourse } from '../../../lib/queryKeys'
import { splitStalled } from '../../../lib/lectureTriage'
import { useBusyLectureIds } from '../../../lib/useJobFeed'
import { useAppStore } from '../../../store/useAppStore'
import type { LectureOut } from '../../../api/types'
import { ErrorAlert } from '../../../components/common/ErrorAlert'
import { LoadingScreen } from '../../../components/common/LoadingScreen'
import { StatusBadge } from '../../../components/common/StatusBadge'
import { UploadDialog } from '../../../components/student/UploadDialog'

/**
 * Lectures — the table, the triage of unfinished rows, and the upload entry
 * point.
 *
 * Owns `['lectures', course]`; Clips and Lecture detail read the same key. The
 * upload form moved into `UploadDialog` at P1, which is why this file no longer
 * holds upload state: ingestion is occasional, and a permanent form competes
 * with the content the page exists to show.
 */
export const LecturesView: React.FC = () => {
  const queryClient = useQueryClient()
  const { selectedCourseId } = useAppStore()

  const [uploadOpen, setUploadOpen] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<LectureOut | null>(null)
  const [dropAbandoned, setDropAbandoned] = useState(false)

  const {
    data: lectureList = [],
    isLoading: isLoadingLectures,
    error: lecturesError,
  } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  const busyLectureIds = useBusyLectureIds(selectedCourseId)
  const { resumable, abandoned } = splitStalled(lectureList, selectedCourseId ?? '')

  // Snapshot for cross-lecture isolation check: a ready lecture with 0 total
  // concepts is isolated from the concept graph.
  const { data: snapshot } = useQuery({
    queryKey: queryKeys.snapshot(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.snapshot(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })
  const totalConcepts = snapshot?.concepts ?? 0

  const handleTriggerConcepts = async (lectureId: number) => {
    setRowError(null)
    try {
      await lecturesApi.extractConcepts(lectureId)
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      setRowError(errorMessage(err, 'Could not start concept extraction'))
    }
  }

  const handleTriggerClips = async (lectureId: number) => {
    setRowError(null)
    try {
      await lecturesApi.cutClips(lectureId)
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      setRowError(errorMessage(err, 'Could not start clip cutting'))
    }
  }

  /**
   * Remove a session — and with it everything derived from it. The backend
   * cascades; this is confirmation UI over an endpoint that exists, because the
   * operation is irreversible.
   */
  const handleRemoveLecture = async () => {
    if (!removeTarget) return
    setRowError(null)
    try {
      await lecturesApi.delete(removeTarget.id)
      setRemoveTarget(null)
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      setRowError(errorMessage(err, 'Could not remove this session'))
    }
  }

  /** Restart transcription for a row whose media is already on the server. */
  const handleResumeLecture = async (lectureId: number) => {
    setRowError(null)
    try {
      await lecturesApi.rerun(lectureId)
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      setRowError(errorMessage(err, 'Could not start processing'))
    }
  }

  /** Delete every abandoned row after confirmation. Failures are per-row. */
  const handleDropAbandoned = async (ids: number[]) => {
    setRowError(null)
    try {
      for (const lid of ids) {
        try {
          await lecturesApi.delete(lid)
        } catch (err: unknown) {
          setRowError(errorMessage(err, `Delete lecture #${lid} failed`))
        }
      }
      if (selectedCourseId) invalidateCourse(queryClient, selectedCourseId)
    } finally {
      setDropAbandoned(false)
    }
  }

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: 2,
        }}
      >
        <Box>
          <Typography variant="h4">Lectures in {selectedCourseId.toUpperCase()}</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
            Upload a recording, extract concepts, cut clips, or remove a session entirely.
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<CloudUploadIcon />} onClick={() => setUploadOpen(true)}>
          Upload lecture
        </Button>
      </Box>

      <Card>
        <CardContent>
          {lecturesError && <ErrorAlert error={lecturesError} title="Failed to load lectures" />}
          {rowError && <ErrorAlert error={rowError} title="Pipeline action failed" />}
          {isLoadingLectures && <LoadingScreen message="Loading lectures..." />}

          {lectureList.length === 0 && !isLoadingLectures && (
            <Typography variant="body2" sx={{ color: 'text.secondary', py: 3, textAlign: 'center' }}>
              No lectures found for this course. Upload the first one to get started.
            </Typography>
          )}

          {lectureList.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Media</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Pipeline actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {lectureList.map((lec) => {
                  // C0's rule: while a job is in flight for this lecture the
                  // actions are disabled, so a double-click cannot queue
                  // duplicate work.
                  const busy = busyLectureIds.has(lec.id)
                  return (
                    <TableRow key={lec.id} hover>
                      <TableCell sx={{ fontFamily: 'var(--font-mono)' }}>#{lec.id}</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>{lec.title}</TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <StatusBadge status={lec.status} />
                          {/* Isolation warning: lecture is processed but the course
                              has no concepts at all — this lecture may be unrelated
                              to the rest of the course content. */}
                          {lec.status === 'ready' && totalConcepts === 0 && (
                            <Tooltip title="This lecture is ready but no concepts have been extracted yet. Run 'Extract concepts' to connect it to the course graph.">
                              <WarningAmberIcon sx={{ fontSize: 16, color: 'warning.main' }} />
                            </Tooltip>
                          )}
                        </Box>
                      </TableCell>
                      <TableCell>
                        {lec.has_media ? (
                          <CheckCircleIcon sx={{ color: 'success.main', fontSize: 18 }} />
                        ) : (
                          <CancelIcon sx={{ color: 'text.disabled', fontSize: 18 }} />
                        )}
                      </TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontSize: '0.8rem' }}>
                        {new Date(lec.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell align="right">
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
                          <Tooltip
                            title={busy ? 'A job is already running for this lecture' : ''}
                            disableHoverListener={!busy}
                          >
                            <span>
                              <Button
                                size="small"
                                variant="outlined"
                                disabled={busy}
                                onClick={() => handleTriggerConcepts(lec.id)}
                                sx={{ fontSize: '0.72rem', py: 0.25 }}
                              >
                                Extract concepts
                              </Button>
                            </span>
                          </Tooltip>
                          <Tooltip
                            title={busy ? 'A job is already running for this lecture' : ''}
                            disableHoverListener={!busy}
                          >
                            <span>
                              <Button
                                size="small"
                                variant="outlined"
                                color="secondary"
                                disabled={busy}
                                onClick={() => handleTriggerClips(lec.id)}
                                sx={{ fontSize: '0.72rem', py: 0.25 }}
                              >
                                Cut clips
                              </Button>
                            </span>
                          </Tooltip>
                          <Tooltip title="Remove this session and everything derived from it">
                            <span>
                              <IconButton
                                size="small"
                                color="error"
                                aria-label={`Remove ${lec.title}`}
                                onClick={() => {
                                  setRowError(null)
                                  setRemoveTarget(lec)
                                }}
                                sx={{ border: '1px solid', borderColor: 'divider' }}
                              >
                                <DeleteOutlineIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Box>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Stalled rows — resumable vs abandoned need opposite actions, so they
          get opposite sections, never one list or one button. */}
      {(resumable.length > 0 || abandoned.length > 0) && (
        <Card>
          <CardContent>
            {resumable.length > 0 && (
              <Box sx={{ mb: abandoned.length > 0 ? 3 : 0 }}>
                <Typography variant="h6">Ready to process, but never started</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                  These rows already have their video on the server. Transcription just never
                  ran — start it below, no re-upload needed.
                </Typography>
                {resumable.map((lec) => {
                  const busy = busyLectureIds.has(lec.id)
                  return (
                    <Box
                      key={lec.id}
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: 2,
                        p: 1.5,
                        mb: 1,
                        borderRadius: 2,
                        border: '1px solid',
                        borderColor: 'divider',
                      }}
                    >
                      <Box>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          #{lec.id} — {lec.title}
                        </Typography>
                        {lec.error && (
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            Last error: {lec.error}
                          </Typography>
                        )}
                      </Box>
                      <Tooltip
                        title={busy ? 'A job is already running for this lecture' : ''}
                        disableHoverListener={!busy}
                      >
                        <span>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={busy}
                            onClick={() => handleResumeLecture(lec.id)}
                          >
                            Start processing
                          </Button>
                        </span>
                      </Tooltip>
                    </Box>
                  )
                })}
              </Box>
            )}

            {abandoned.length > 0 && (
              <Box>
                <Typography variant="h6">Incomplete uploads (no file arrived)</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                  A row was created but the video never finished uploading, so there is nothing
                  on the server to process. Delete these to clean up.
                </Typography>
                {abandoned.map((lec) => (
                  <Typography key={lec.id} variant="body2" sx={{ color: 'text.secondary' }}>
                    #{lec.id} — {lec.title} · no media on the server
                  </Typography>
                ))}
                <Button
                  size="small"
                  color="error"
                  variant="outlined"
                  sx={{ mt: 1.5 }}
                  onClick={() => setDropAbandoned(true)}
                >
                  Delete these empty rows
                </Button>
              </Box>
            )}
          </CardContent>
        </Card>
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        courseId={selectedCourseId}
        lectures={lectureList}
      />

      {/* Removal is irreversible, so it is confirmed — and the dialog says
          exactly what travels with it. */}
      <Dialog
        open={removeTarget != null}
        onClose={() => setRemoveTarget(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Remove this session?</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>{removeTarget?.title}</strong> will be removed from{' '}
            {selectedCourseId.toUpperCase()}.
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            Everything derived from it goes too: the transcript, its extracted concepts and
            topics, every clip cut from it, and its quiz coverage. This cannot be undone.
          </Typography>
          {rowError && (
            <Alert severity="error" sx={{ mt: 1.5 }}>
              {rowError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setRemoveTarget(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleRemoveLecture} autoFocus>
            Remove session
          </Button>
        </DialogActions>
      </Dialog>

      {/* Bulk removal gets the same confirmation: same irreversibility. */}
      <Dialog
        open={dropAbandoned}
        onClose={() => setDropAbandoned(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Delete empty rows?</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            {abandoned.length} row{abandoned.length === 1 ? '' : 's'} with no media on the
            server will be deleted. This cannot be undone.
          </Typography>
          {rowError && (
            <Alert severity="error" sx={{ mt: 1.5 }}>
              {rowError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setDropAbandoned(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => handleDropAbandoned(abandoned.map((l) => l.id))}
            autoFocus
          >
            Delete empty rows
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
