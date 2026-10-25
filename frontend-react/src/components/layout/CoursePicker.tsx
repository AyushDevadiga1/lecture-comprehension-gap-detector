import React, { useEffect, useState } from 'react'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { errorMessage } from '../../api/client'
import { useAppStore } from '../../store/useAppStore'
import { invalidateCourse, queryKeys } from '../../lib/queryKeys'
import { tint } from '../../theme/alpha'

/** Course ID must be alphanumeric / hyphens / underscores, 1-40 chars. */
const COURSE_ID_RE = /^[\w-]{1,40}$/

/**
 * Course selection and deletion — one component, because one thing owns it.
 *
 * Extracted verbatim from `Navbar` so the new `Sidebar` can host the same
 * control without a second copy of the auto-select and delete logic. Two copies
 * of "which course is selected" is exactly how the four invalidation lists in
 * this repo drifted apart before `invalidateCourse` existed.
 *
 * Three behaviours live here and none of them is obvious:
 *
 *  1. **Auto-select.** No stored course (fresh install, private mode) selects
 *     the first available one, so the dashboards are never in a no-course state
 *     with nothing to click.
 *  2. **Fallback.** A stored id that no longer exists on the server (deleted
 *     between sessions) silently moves to the first available one. Without it
 *     every query fires with a 404-producing id — a permanently broken state.
 *  3. **Last-course guard.** Deletion is disabled when only one course remains,
 *     because with none selected there is no path to create the next one yet.
 *     That is a deliberate refusal, not a bug; the tooltip says why.
 */
export const CoursePicker: React.FC = () => {
  const { selectedCourseId, setSelectedCourseId } = useAppStore()
  const queryClient = useQueryClient()

  // The error is read too, so a failed course list never renders as
  // "No courses found" — that text reads as *your data is gone* rather than
  // *you are not authorised*, and sends the reader hunting in the wrong place.
  // The 401 case is covered by the AuthBanner; this covers everything else.
  const { data: courseList = [], isError: coursesFailed } = useQuery({
    queryKey: queryKeys.courses(),
    queryFn: () => coursesApi.list(),
  })

  useEffect(() => {
    if (selectedCourseId == null && courseList.length > 0) {
      setSelectedCourseId(courseList[0]!.course_id)
    }
  }, [courseList, selectedCourseId, setSelectedCourseId])

  useEffect(() => {
    if (
      selectedCourseId != null &&
      courseList.length > 0 &&
      !courseList.some((c) => c.course_id === selectedCourseId)
    ) {
      setSelectedCourseId(courseList[0]!.course_id)
    }
  }, [courseList, selectedCourseId, setSelectedCourseId])

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // ── Create new course ──────────────────────────────────────────────────
  const [createOpen, setCreateOpen] = useState(false)
  const [newCourseId, setNewCourseId] = useState('')
  const newCourseIdValid = COURSE_ID_RE.test(newCourseId.trim())
  const newCourseIdTaken = courseList.some(
    (c) => c.course_id === newCourseId.trim().toLowerCase(),
  )

  const handleCreateCourse = () => {
    const id = newCourseId.trim().toLowerCase()
    if (!newCourseIdValid || newCourseIdTaken) return
    setSelectedCourseId(id)
    setCreateOpen(false)
    setNewCourseId('')
  }

  const canDelete = selectedCourseId != null && courseList.length > 1 && !deleting

  const handleConfirmDelete = async () => {
    if (selectedCourseId == null) return
    const removed = selectedCourseId
    setDeleting(true)
    setDeleteError(null)
    try {
      await coursesApi.delete(removed)
      setConfirmDelete(false)
      // Move off the deleted course *before* invalidating, so no query fires
      // once against an id that no longer exists. Then the one invalidation
      // rule: it already clears ['courses'] and every course-scoped key for
      // `removed`, which is exactly the set a deletion invalidates. A blanket
      // wipe here would also clear every other course's cache, and the
      // queryKeys guard rightly forbids a panel doing its own invalidation.
      const remaining = courseList.filter((c) => c.course_id !== removed)
      setSelectedCourseId(remaining[0]?.course_id ?? null)
      invalidateCourse(queryClient, removed)
    } catch (err: unknown) {
      setDeleteError(errorMessage(err, 'Could not delete course'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 150, flex: 1 }}>
          <InputLabel id="course-select-label" sx={{ color: 'text.secondary' }}>
            Course
          </InputLabel>
          <Select
            labelId="course-select-label"
            value={selectedCourseId || ''}
            label="Course"
            onChange={(e) => setSelectedCourseId(e.target.value)}
            sx={{
              borderRadius: '10px',
              // A wash of `text`, not a hardcoded white at 4%. A white wash is
              // invisible the moment anyone flips to the light base.
              backgroundColor: tint('text', 4),
              '& .MuiSelect-select': { py: 1, fontWeight: 600 },
            }}
          >
            {selectedCourseId && !courseList.some((c) => c.course_id === selectedCourseId) && (
              <MenuItem value={selectedCourseId} sx={{ display: 'none' }}>
                {selectedCourseId.toUpperCase()}
              </MenuItem>
            )}
            {courseList.map((c) => (
              <MenuItem key={c.course_id} value={c.course_id}>
                {c.course_id.toUpperCase()} ({c.total_lectures}{' '}
                {c.total_lectures === 1 ? 'lec' : 'lecs'})
              </MenuItem>
            ))}
            {courseList.length === 0 && !selectedCourseId && (
              <MenuItem value="" disabled>
                {coursesFailed ? 'Could not load courses' : 'No courses found'}
              </MenuItem>
            )}
          </Select>
        </FormControl>

        <Tooltip title="Create a new course">
          <IconButton
            onClick={() => {
              setNewCourseId('')
              setCreateOpen(true)
            }}
            color="inherit"
            aria-label="Create a new course"
            size="small"
            sx={{ border: '1px solid', borderColor: 'divider' }}
          >
            <AddCircleOutlineIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Tooltip
          title={
            selectedCourseId == null
              ? 'Select a course first'
              : courseList.length <= 1
                ? 'Keep at least one course'
                : `Delete course ${selectedCourseId.toUpperCase()}`
          }
        >
          <span>
            <IconButton
              onClick={() => {
                setDeleteError(null)
                setConfirmDelete(true)
              }}
              disabled={!canDelete}
              color="inherit"
              aria-label="Delete this course"
              sx={{ border: '1px solid', borderColor: 'divider' }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* ── Create course dialog ───────────────────────────────────────── */}
      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle sx={{ fontWeight: 600 }}>Create a new course</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
            Enter an ID for the new course (letters, numbers, hyphens, underscores — max 40
            characters). The course is created automatically when you upload the first lecture.
          </Typography>
          <TextField
            label="Course ID"
            placeholder="e.g. ml-2025"
            value={newCourseId}
            onChange={(e) => setNewCourseId(e.target.value.replace(/\s/g, '-'))}
            size="small"
            fullWidth
            autoFocus
            error={newCourseId.length > 0 && (!newCourseIdValid || newCourseIdTaken)}
            helperText={
              newCourseIdTaken
                ? 'A course with this ID already exists.'
                : newCourseId.length > 0 && !newCourseIdValid
                  ? 'Only letters, numbers, hyphens, and underscores (1–40 chars).'
                  : ''
            }
            inputProps={{ 'aria-label': 'New course ID', maxLength: 40 }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newCourseIdValid && !newCourseIdTaken) handleCreateCourse()
            }}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreateCourse}
            disabled={!newCourseIdValid || newCourseIdTaken}
            autoFocus
          >
            Create &amp; Switch
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 600 }}>
          Delete course {selectedCourseId?.toUpperCase()}?
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            Every lecture, concept, graph edge, clip, quiz question and job for this
            course goes too. This cannot be undone.
          </Typography>
          {deleteError && (
            <Typography variant="body2" sx={{ color: 'error.main', mt: 1.5 }}>
              {deleteError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleConfirmDelete}
            disabled={deleting}
            autoFocus
          >
            {deleting ? 'Deleting…' : 'Delete course'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
