import React, { useEffect, useRef, useState, Suspense } from 'react'
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  TextField,
  LinearProgress,
  Checkbox,
  FormControlLabel,
  Table,
  TableHead,
  TableRow,
  TableCell,
  Tooltip,
  TableBody,
  Alert,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Skeleton,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { lectures as lecturesApi } from '../../api/lectures'
import type { LectureOut } from '../../api/types'
import { quizzes as quizzesApi } from '../../api/quizzes'
import { errorMessage } from '../../api/client'
import { queryKeys, invalidateCourse } from '../../lib/queryKeys'
import {
  capViolation,
  generationError,
  latencySince,
  quizMaxQuestions,
  submitError,
} from '../../lib/quiz'
import { useJobList, useBusyLectureIds } from '../../lib/useJobFeed'
import { findDuplicate, splitStalled } from '../../lib/lectureTriage'
import { useQuizStore, draftForCourse } from '../../store/useQuizStore'
import { useAppStore } from '../../store/useAppStore'
import { StatusBadge } from '../../components/common/StatusBadge'
import { LoadingScreen } from '../../components/common/LoadingScreen'
import { ErrorAlert } from '../../components/common/ErrorAlert'
import { SectionIcon } from '../../components/common/SectionIcon'
import { Rise } from '../../components/common/Rise'
// Lazy: reactflow is ~190 KB minified and this view sits below the fold.
// The page paints and becomes interactive first; the graph chunk streams in
// after. The fallback reuses the loading screen so the two loading states
// (query vs chunk) read as one.
const DagView = React.lazy(() =>
  import('../../components/graph/DagView').then((m) => ({ default: m.DagView })),
)
import { ClipBrowser } from './ClipBrowser'
import { QuizPanel } from './QuizPanel'


export const StudentDashboard: React.FC = () => {
  const queryClient = useQueryClient()
  const { selectedCourseId, studentId, setStudentId } = useAppStore()

  // Upload state
  const [uploadTitle, setUploadTitle] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  /**
   * Explicit "upload anyway" for the duplicate guard below. Reset whenever
   * the file changes — an ack for one filename must never carry over to the
   * next, or the guard warns without protecting.
   */
  const [dedupeAck, setDedupeAck] = useState(false)
  /**
   * Upload progress. `null` = idle; a number = measured percent; `'streaming'`
   * = bytes are flowing but unmeasurable (or nothing has reported yet). The
   * third state is the honest one the old code lacked: previously the bar was
   * set to 0 and only ever moved on computable events, so a whole upload sat
   * at 0% in every browser that reports lengthComputable: false for File
   * bodies. An indeterminate bar says "working, unmeasured"; a frozen 0%
   * says "stalled".
   */
  const [uploadProgress, setUploadProgress] = useState<number | 'streaming' | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // Quiz state
  // Quiz state lives in the draft store (§2): the selections are the user's,
  // the questions are re-readable from the server.
  const draft = useQuizStore((s) => draftForCourse(s, selectedCourseId))
  const quizResult = useQuizStore((s) => s.result)
  const startQuiz = useQuizStore((s) => s.start)
  const finishQuiz = useQuizStore((s) => s.finish)
  const clearQuiz = useQuizStore((s) => s.clear)
  const resetQuiz = useQuizStore((s) => s.reset)
  const selectAnswer = useQuizStore((s) => s.select)
  const [quizError, setQuizError] = useState<string | null>(null)
  const [quizWarning, setQuizWarning] = useState<string | null>(null)
  /** The id of the quiz job we started, so we can watch it for completion. */
  const quizJobIdRef = useRef<number | null>(null)

  // Per-lecture row action errors (extract concepts / cut clips)
  const [rowError, setRowError] = useState<string | null>(null)

  /** The session a removal is pending confirmation for. */
  const [removeTarget, setRemoveTarget] = useState<LectureOut | null>(null)

  /** Bulk removal of abandoned rows, pending the same confirmation. */
  const [dropAbandoned, setDropAbandoned] = useState(false)


  // Remediation playback state
  const [playingClipUrl, setPlayingClipUrl] = useState<string | null>(null)

  // Load course snapshot & lectures
  const {
    data: snapshot,
    error: snapshotError,
  } = useQuery({
    queryKey: queryKeys.snapshot(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.snapshot(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })

  // The prerequisite DAG payload. Same query the faculty view runs; the
  // drawing itself is DagView, shared by both dashboards.
  const {
    data: graphData,
    isLoading: isLoadingGraph,
    error: graphError,
  } = useQuery({
    queryKey: queryKeys.graph(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? coursesApi.graph(selectedCourseId) : null),
    enabled: !!selectedCourseId,
  })


  const {
    data: lectureList = [],
    isLoading: isLoadingLectures,
    error: lecturesError,
  } = useQuery({
    queryKey: queryKeys.lectures(selectedCourseId ?? ''),
    queryFn: () => (selectedCourseId ? lecturesApi.list(selectedCourseId) : []),
    enabled: !!selectedCourseId,
  })

  // Mutations
  const generateQuizMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCourseId) throw new Error('No course selected')
      const cap = quizMaxQuestions()
      // Queues the work and returns a job id. The blocking POST /quizzes was
      // the endpoint that froze the page; the drawer shows this instead.
      const accepted = await quizzesApi.createJob(selectedCourseId, studentId, cap)
      setQuizError(null)
      quizJobIdRef.current = accepted.job_id
      return accepted
    },
    onError: (err: unknown) => {
      setQuizError(generationError(err))
    },
  })

  /**
   * Fetch the generated quiz once its job is done. Reading `GET /quizzes` is
   * cheap — no generation calls — so this also serves as "resume the quiz I was
   * already taking" on reload.
   */
  const loadQuizMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCourseId) throw new Error('No course selected')
      const quiz = await quizzesApi.current(selectedCourseId, studentId)
      const cap = quizMaxQuestions()
      const stale = capViolation(quiz.questions.length, cap)
      if (stale) setQuizWarning(stale)
      startQuiz({
        quiz,
        courseId: selectedCourseId,
        studentId,
        answers: {},
        renderedAt: Date.now(),
      })
      return quiz
    },
    onError: (err: unknown) => {
      setQuizError(generationError(err, 'Could not load the quiz for this course.'))
    },
  })

  const submitQuizMutation = useMutation({
    mutationFn: async () => {
      if (!draft || !selectedCourseId) throw new Error('No active quiz')
      const answers = Object.entries(draft.answers).map(([qid, sel]) => ({
        question_id: Number(qid),
        selected: sel,
        // Stamped on every answer, as panels/quiz.py:118-122 does.
        latency_s: latencySince(draft.renderedAt, Object.keys(draft.answers).length),
      }))
      return quizzesApi.submit({
        course_id: selectedCourseId,
        student_id: studentId,
        answers,
      })
    },
    onSuccess: (data) => {
      // One-shot: a stale id set must not be resubmittable.
      finishQuiz(data)
    },
    onError: (err: unknown) => {
      setQuizError(submitError(err))
    },
  })

  /**
   * Fetch the quiz once the job we queued finishes.
   *
   * This is the "start a lecture job mid-quiz, finish the quiz, nothing was
   * regenerated or lost" property from REACT_ARCHITECTURE §6, and it holds for
   * free: the draft is UI state, and a job completing only invalidates the
   * graph/lecture keys. The Streamlit engine needed a dedicated `completed`
   * record and a `drain_ready` to get this right.
   */
  const jobs = useJobList(selectedCourseId)
  const busyLectureIds = useBusyLectureIds(selectedCourseId)
  useEffect(() => {
    const id = quizJobIdRef.current
    if (id === null) return
    const job = jobs.find((j) => j.id === id)
    if (!job) return
    if (job.status === 'ready') {
      quizJobIdRef.current = null
      void loadQuizMutation.mutate()
    } else if (job.status === 'error' || job.status === 'cancelled') {
      quizJobIdRef.current = null
      setQuizError(job.error || 'Quiz generation failed.')
    }
  }, [jobs, loadQuizMutation])

  // A course change invalidates the draft: panels/quiz.py:99-103.
  useEffect(() => {
    quizJobIdRef.current = null
    setQuizError(null)
    setQuizWarning(null)
    clearQuiz()
  }, [selectedCourseId, clearQuiz])

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedCourseId || !selectedFile || !uploadTitle.trim()) return

    setUploadError(null)
    setUploadProgress('streaming')

    try {
      // Step 1: Create lecture row
      const lecture = await lecturesApi.create({
        course_id: selectedCourseId,
        title: uploadTitle.trim(),
      })

      // Step 2: Stream media PUT with real XHR progress
      await lecturesApi.uploadMedia(
        lecture.id,
        selectedFile,
        (pct) => setUploadProgress(pct === null ? 'streaming' : pct),
      )

      // Reset form
      setUploadTitle('')
      setSelectedFile(null)
      setUploadProgress(null)
      invalidateCourse(queryClient, selectedCourseId)
    } catch (err: unknown) {
      setUploadError(errorMessage(err, 'Upload failed'))
      setUploadProgress(null)
    }
  }

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
   * Remove a session — and with it everything derived from it.
   *
   * Uploading the wrong course into a playlist (a SQL session in a
   * deep-learning list) is a real failure mode, and the backend already
   * cascades: DELETE /lectures/{id} drops the row plus its segments,
   * concepts, clips, passages and links. So this is confirmation UI over an
   * endpoint that exists — the dialog is here because the operation is
   * irreversible and the derived work would have to be redone from scratch.
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

  /**
   * Restart transcription for a row whose media is already on the server.
   * The busy guard (one pipeline job per lecture) applies here exactly as on
   * the table buttons — the UI disables, so this never double-queues.
   */
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
      // Close regardless: partial progress must be visible, not hidden
      // behind a still-open dialog.
      setDropAbandoned(false)
    }
  }

  // Duplicate guard + stalled split, recomputed per render from the lecture
  // list (small arrays; no memo needed). Both are pure lib functions with
  // their own unit tests.
  const duplicateId = selectedCourseId
    ? findDuplicate(lectureList, selectedCourseId, selectedFile?.name)
    : null
  const { resumable, abandoned } = splitStalled(lectureList, selectedCourseId ?? '')

  if (!selectedCourseId) {
    return (
      <Alert severity="info" sx={{ mt: 4 }}>
        Please select a course from the header to view student materials.
      </Alert>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header and Snapshot Overview */}
      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
          <Box>
            <Typography variant="h4" sx={{ fontWeight: 800 }}>
              Student Portal: {selectedCourseId.toUpperCase()}
            </Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
              Upload lectures, take adaptive comprehension checks, and stream prerequisite remediation clips.
            </Typography>
          </Box>

          <TextField
            size="small"
            label="Student ID"
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            sx={{ width: 180 }}
          />
        </Box>

        {snapshotError && <ErrorAlert error={snapshotError} title="Failed to load course snapshot" />}

        {snapshot && (
          <Grid container spacing={2} sx={{ mt: 2 }}>
            <Grid item xs={12} sm={6} md={3}>
              <Rise delay={0}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                  Total Lectures
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.lectures.total} ({snapshot.lectures.ready} ready)
                </Typography>
              </Card>
              </Rise>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Rise delay={0.05}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                  Extracted Concepts
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.concepts}
                </Typography>
              </Card>
              </Rise>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Rise delay={0.1}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                  Prerequisite Graph
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5, fontVariantNumeric: 'tabular-nums', color: snapshot.graph.has ? 'success.main' : 'warning.main' }}>
                  {snapshot.graph.has ? `${snapshot.graph.edges} Edges` : 'Not Built'}
                </Typography>
              </Card>
              </Rise>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Rise delay={0.15}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                  Video Clips Cut
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5, fontVariantNumeric: 'tabular-nums' }}>
                  {snapshot.clips.ok} / {snapshot.clips.cut} OK
                </Typography>
              </Card>
              </Rise>
            </Grid>
          </Grid>
        )}
      </Box>

      {/* Main Grid: Upload & Quiz */}
      <Grid container spacing={3}>
        {/* Upload Lecture Card */}
        <Grid item xs={12} md={5}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
                <SectionIcon>
                  <CloudUploadIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                </SectionIcon>
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  Upload Lecture
                </Typography>
              </Box>

              <form onSubmit={handleFileUpload}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField
                    label="Lecture Title"
                    placeholder="e.g. Lecture 1 — Introduction to Vectors"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    size="small"
                    required
                    fullWidth
                  />

                  <Button
                    variant="outlined"
                    component="label"
                    sx={{
                      p: 1.5,
                      borderStyle: 'dashed',
                      borderColor: selectedFile ? 'primary.main' : 'divider',
                    }}
                  >
                    {selectedFile ? selectedFile.name : 'Select Video / Audio File (.mp4, .mp3, .wav)'}
                    <input
                      type="file"
                      hidden
                      accept="video/*,audio/*"
                      onChange={(e) => {
                        setSelectedFile(e.target.files?.[0] || null)
                        // An ack is per-filename: choosing another file must
                        // re-arm the guard, or the warning protects nothing.
                        setDedupeAck(false)
                      }}
                    />
                  </Button>

                  {duplicateId != null && (
                    <Box>
                      <Alert severity="warning" sx={{ mb: 1 }}>
                        A lecture in this course already looks like this file
                        (#{duplicateId}). Uploading will create a second row.
                      </Alert>
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={dedupeAck}
                            onChange={(e) => setDedupeAck(e.target.checked)}
                            size="small"
                          />
                        }
                        label="Upload anyway (I know it's a duplicate)"
                      />
                    </Box>
                  )}

                  {uploadProgress !== null && (
                    <Box>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="caption">Uploading media stream...</Typography>
                        <Typography variant="caption" sx={{ fontWeight: 600 }}>
                          {uploadProgress === 'streaming' ? 'Uploading…' : `${uploadProgress}%`}
                        </Typography>
                      </Box>
                      <LinearProgress
                        variant={uploadProgress === 'streaming' ? 'indeterminate' : 'determinate'}
                        value={typeof uploadProgress === 'number' ? uploadProgress : 0}
                        sx={{ height: 6, borderRadius: 3 }}
                      />
                    </Box>
                  )}

                  {uploadError && <ErrorAlert error={uploadError} title="Upload failed" />}

                  <Button
                    type="submit"
                    variant="contained"
                    disabled={
                      !selectedFile ||
                      !uploadTitle.trim() ||
                      uploadProgress !== null ||
                      (duplicateId != null && !dedupeAck)
                    }
                    startIcon={<CloudUploadIcon />}
                  >
                    Upload &amp; Transcribe
                  </Button>
                </Box>
              </form>
            </CardContent>
          </Card>
        </Grid>

        {/* Adaptive Quiz Trigger & Display — the flow itself lives in
            QuizPanel: idle → generating → answering → graded. */}
        <Grid item xs={12} md={7}>
          <QuizPanel
            maxQuestions={quizMaxQuestions()}
            generatePending={generateQuizMutation.isPending}
            onGenerate={() => generateQuizMutation.mutate()}
            draft={draft}
            result={quizResult}
            onSelectAnswer={selectAnswer}
            onSubmit={() => submitQuizMutation.mutate()}
            submitPending={submitQuizMutation.isPending}
            onReset={() => resetQuiz()}
            error={quizError}
            warning={quizWarning}
            clipUrl={playingClipUrl}
            onCloseClip={() => setPlayingClipUrl(null)}
            onWatchClip={setPlayingClipUrl}
          />
        </Grid>
      </Grid>

      {/* Lectures List for Course */}
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>
          Lectures in {selectedCourseId.toUpperCase()}
        </Typography>

        {lecturesError && <ErrorAlert error={lecturesError} title="Failed to load lectures" />}
        {rowError && <ErrorAlert error={rowError} title="Pipeline action failed" />}
        {isLoadingLectures && <LoadingScreen message="Loading lectures..." />}

        {lectureList.length === 0 && !isLoadingLectures && (
          <Card sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
            <Typography variant="body1">No lectures found for this course.</Typography>
            <Typography variant="body2" sx={{ mt: 1 }}>
              Use the upload form above to add your first lecture video or audio file.
            </Typography>
          </Card>
        )}

        {lectureList.length > 0 && (
          <Card>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Media</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Pipeline Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {lectureList.map((lec) => (
                  <TableRow key={lec.id} hover>
                    <TableCell sx={{ fontFamily: 'var(--font-mono)' }}>#{lec.id}</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{lec.title}</TableCell>
                    <TableCell>
                      <StatusBadge status={lec.status} />
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
                        {(() => {
                          // C0's rule, enforced: while a job is in flight for
                          // this lecture the actions are disabled, so a
                          // double-click cannot queue duplicate work.
                          const busy = busyLectureIds.has(lec.id)
                          return (
                            <>
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
                                    Extract Concepts
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
                                    Cut Clips
                                  </Button>
                                </span>
                              </Tooltip>
                            </>
                          )
                        })()}
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </Box>

      {/* Stalled rows — resumable vs abandoned need opposite actions, so they
          get opposite sections, never one list or one button. */}
      {(resumable.length > 0 || abandoned.length > 0) && (
        <Box>
          {resumable.length > 0 && (
            <Box sx={{ mb: 3 }}>
              <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>
                Ready to process, but never started
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                These rows already have their video on the server. Transcription
                just never ran — start it below, no re-upload needed.
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
              <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>
                Incomplete uploads (no file arrived)
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                A row was created but the video never finished uploading, so
                there is nothing on the server to process. Delete these to
                clean up.
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
        </Box>
      )}

      {/* Course graph — the prerequisite DAG, drawn rather than listed.
          Sits between the lectures that produced it and the clips cut from
          those lectures. `key` resets the view's control state on a course
          switch so a filter chosen for one course never silently scopes
          another. */}
      <Box sx={{ mt: 4 }}>
        <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
          Course graph
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
          Prerequisites sit above what they unlock. Drag to pan, scroll to
          zoom, click a concept for its links and evidence.
        </Typography>

        {graphError && <ErrorAlert error={graphError} title="Failed to load graph" />}
        {isLoadingGraph && <LoadingScreen message="Loading prerequisite graph..." />}
        {graphData && (
          // The chunk fallback is scoped to the graph card's own shape — a
          // skeleton, not the full LoadingScreen. On a slow connection the
          // lecture table above stays visually present and interactive while
          // the graph chunk streams in; a page-level spinner would cover work
          // the reader could already be doing.
          <Suspense
            fallback={
              <Skeleton
                variant="rounded"
                height={480}
                role="status"
                aria-label="Loading prerequisite graph"
              />
            }
          >
            <DagView key={selectedCourseId} graph={graphData} idPrefix="student-graph" />
          </Suspense>
        )}
      </Box>

      {/* Clip Library — every clip cut for one lecture, listed and playable.
          Sits after the lecture list because it browses one of those lectures,
          and the picker above is where the default selection comes from. */}
      <Box sx={{ mt: 4 }}>
        <ClipBrowser lectures={lectureList} onCutClips={handleTriggerClips} />
      </Box>

      {/* Removal is irreversible, so it is confirmed — and the dialog says
          exactly what travels with it. */}
      <Dialog
        open={removeTarget != null}
        onClose={() => setRemoveTarget(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle sx={{ fontWeight: 800 }}>Remove this session?</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>{removeTarget?.title}</strong> will be removed from{' '}
            {selectedCourseId?.toUpperCase()}.
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            Everything derived from it goes too: the transcript, its extracted concepts
            and topics, every clip cut from it, and its quiz coverage. This cannot be
            undone.
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
        <DialogTitle sx={{ fontWeight: 800 }}>Delete empty rows?</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            {abandoned.length} row{abandoned.length === 1 ? '' : 's'} with no
            media on the server will be deleted. This cannot be undone.
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
