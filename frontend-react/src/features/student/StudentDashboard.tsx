import React, { useEffect, useRef, useState } from 'react'
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  TextField,
  LinearProgress,
  Table,
  TableHead,
  TableRow,
  TableCell,
  Tooltip,
  TableBody,
  Radio,
  RadioGroup,
  FormControlLabel,
  FormControl,
  Alert,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import QuizIcon from '@mui/icons-material/Quiz'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { lectures as lecturesApi } from '../../api/lectures'
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
import { useQuizStore, draftForCourse } from '../../store/useQuizStore'
import { useAppStore } from '../../store/useAppStore'
import { StatusBadge } from '../../components/common/StatusBadge'
import { LoadingScreen } from '../../components/common/LoadingScreen'
import { ErrorAlert } from '../../components/common/ErrorAlert'
import { ClipBrowser } from './ClipBrowser'


export const StudentDashboard: React.FC = () => {
  const queryClient = useQueryClient()
  const { selectedCourseId, studentId, setStudentId } = useAppStore()

  // Upload state
  const [uploadTitle, setUploadTitle] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
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
    setUploadProgress(0)

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
        (pct) => setUploadProgress(pct),
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
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Total Lectures
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5 }}>
                  {snapshot.lectures.total} ({snapshot.lectures.ready} ready)
                </Typography>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Extracted Concepts
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5 }}>
                  {snapshot.concepts}
                </Typography>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Prerequisite Graph
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5, color: snapshot.graph.has ? 'success.main' : 'warning.main' }}>
                  {snapshot.graph.has ? `${snapshot.graph.edges} Edges` : 'Not Built'}
                </Typography>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Video Clips Cut
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5 }}>
                  {snapshot.clips.ok} / {snapshot.clips.cut} OK
                </Typography>
              </Card>
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
                <CloudUploadIcon sx={{ color: 'primary.light' }} />
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
                      onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                    />
                  </Button>

                  {uploadProgress !== null && (
                    <Box>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="caption">Uploading media stream...</Typography>
                        <Typography variant="caption" sx={{ fontWeight: 600 }}>{uploadProgress}%</Typography>
                      </Box>
                      <LinearProgress variant="determinate" value={uploadProgress} sx={{ height: 6, borderRadius: 3 }} />
                    </Box>
                  )}

                  {uploadError && <ErrorAlert error={uploadError} title="Upload failed" />}

                  <Button
                    type="submit"
                    variant="contained"
                    disabled={!selectedFile || !uploadTitle.trim() || uploadProgress !== null}
                    startIcon={<CloudUploadIcon />}
                  >
                    Upload &amp; Transcribe
                  </Button>
                </Box>
              </form>
            </CardContent>
          </Card>
        </Grid>

        {/* Adaptive Quiz Trigger & Display */}
        <Grid item xs={12} md={7}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                  <QuizIcon sx={{ color: 'secondary.light' }} />
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    Comprehension Quiz &amp; Gap Detection
                  </Typography>
                </Box>
                {!draft && !quizResult && (
                  <Button
                    variant="contained"
                    color="secondary"
                    onClick={() => generateQuizMutation.mutate()}
                    disabled={generateQuizMutation.isPending}
                  >
                    {generateQuizMutation.isPending ? 'Queueing...' : 'Start Quiz'}
                  </Button>
                )}
              </Box>

              {/* The cap is visible before generation, not discovered after. */}
              <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
                Up to {quizMaxQuestions()} questions, drawn evenly from across the course's concepts.
              </Typography>

              {quizError && <ErrorAlert error={quizError} title="Quiz Error" />}
              {quizWarning && <ErrorAlert error={quizWarning} title="Quiz cap not applied" />}

              {generateQuizMutation.isPending && (
                <LoadingScreen message="Queueing quiz generation. The job appears in Background Tasks and the quiz opens itself when it is ready." />
              )}

              {/* Active Quiz Form */}
              {draft && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <Alert severity="info">
                    Answer the diagnostic questions below. Incorrect answers will trace prerequisites backwards along the DAG to form your personalised remediation plan.
                  </Alert>

                  {draft.quiz.questions.map((q, idx) => (
                    <Box
                      key={q.id}
                      sx={{
                        p: 2,
                        borderRadius: 2,
                        backgroundColor: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.06)',
                      }}
                    >
                      <Typography variant="subtitle2" sx={{ color: 'secondary.light', mb: 0.5, fontWeight: 700 }}>
                        Question {idx + 1} &bull; Concept: {q.concept}
                      </Typography>
                      <Typography variant="body1" sx={{ fontWeight: 600, mb: 1.5 }}>
                        {q.question}
                      </Typography>

                      <FormControl component="fieldset">
                        <RadioGroup
                          value={draft.answers[q.id] || ''}
                          onChange={(e) => selectAnswer(q.id, e.target.value)}
                        >
                          {(q.options?.length ? q.options : ['correct', 'incorrect', 'wrong']).map(
                            (opt, optIdx) => (
                              <FormControlLabel
                                key={optIdx}
                                value={opt}
                                control={<Radio size="small" />}
                                label={<Typography variant="body2">{opt}</Typography>}
                              />
                            ),
                          )}
                        </RadioGroup>
                      </FormControl>
                    </Box>
                  ))}

                  <Button
                    variant="contained"
                    color="primary"
                    size="large"
                    onClick={() => submitQuizMutation.mutate()}
                    disabled={submitQuizMutation.isPending || Object.keys(draft.answers).length === 0}
                  >
                    {submitQuizMutation.isPending ? 'Grading...' : 'Submit Answers'}
                  </Button>
                </Box>
              )}

              {/* Quiz Results & Remediation */}
              {quizResult && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <Box
                    sx={{
                      p: 2.5,
                      borderRadius: 2,
                      background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%)',
                      border: '1px solid rgba(99, 102, 241, 0.3)',
                    }}
                  >
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>
                      Score: {quizResult.score} / {quizResult.total} (
                      {quizResult.total > 0
                        ? Math.round((quizResult.score / quizResult.total) * 100)
                        : 0}
                      %)
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                      Student: {quizResult.student_id} &bull; Quiz ID: #{quizResult.quiz_id}
                    </Typography>
                  </Box>

                  {/* Remediation sequence */}
                  {quizResult.remediation.length > 0 && (
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>
                        Recommended Remediation Sequence (Topological Prerequisite Order)
                      </Typography>
                      <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                        Review these prerequisite concepts in the order indicated to repair foundational comprehension gaps:
                      </Typography>

                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                        {quizResult.remediation.map((item, idx) => (
                          <Box
                            key={idx}
                            sx={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              p: 1.5,
                              borderRadius: 1.5,
                              backgroundColor: 'rgba(255,255,255,0.03)',
                              border: '1px solid rgba(255,255,255,0.06)',
                            }}
                          >
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                              <Typography variant="subtitle2" sx={{ color: 'secondary.light', fontWeight: 700 }}>
                                #{idx + 1}
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {item.concept}
                              </Typography>
                              {item.failed ? (
                                <CancelIcon sx={{ color: 'error.main', fontSize: 18 }} />
                              ) : (
                                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                  (Prerequisite foundation)
                                </Typography>
                              )}
                            </Box>

                            {item.clip_url ? (
                              <Button
                                size="small"
                                variant="outlined"
                                startIcon={<PlayCircleOutlineIcon />}
                                onClick={() => setPlayingClipUrl(item.clip_url ?? null)}
                              >
                                Watch Clip
                              </Button>
                            ) : (

                              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                Clip not ready
                              </Typography>
                            )}
                          </Box>
                        ))}
                      </Box>
                    </Box>
                  )}

                  {/* Feedback on questions */}
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                      Item Feedback &amp; Explanations
                    </Typography>
                    {quizResult.feedback.map((f) => (
                      <Box
                        key={f.question_id}
                        sx={{
                          p: 1.5,
                          borderRadius: 1,
                          mb: 1,
                          backgroundColor: f.correct ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                          border: `1px solid ${f.correct ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                          {f.correct ? (
                            <CheckCircleIcon sx={{ color: 'success.main', fontSize: 18 }} />
                          ) : (
                            <CancelIcon sx={{ color: 'error.main', fontSize: 18 }} />
                          )}
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            {f.concept}: {f.correct ? 'Correct' : 'Missed'}
                          </Typography>
                        </Box>
                        {!f.correct && f.answer && (
                          <Typography variant="body2" sx={{ fontSize: '0.85rem', mb: 0.5 }}>
                            <strong>Correct answer: {f.answer}</strong>
                          </Typography>
                        )}
                        {!f.correct && f.rationale && (
                          <Typography variant="body2" sx={{ color: 'text.secondary', fontSize: '0.85rem' }}>
                            Why your pick was wrong: {f.rationale}
                          </Typography>
                        )}
                        {f.explanation && (
                          <Typography variant="body2" sx={{ color: 'text.secondary', fontSize: '0.85rem' }}>
                            {f.explanation}
                          </Typography>
                        )}
                      </Box>
                    ))}
                  </Box>

                  <Button variant="outlined" onClick={() => resetQuiz()}>
                    Done / Retake Later
                  </Button>
                </Box>
              )}

              {/* Video Player Modal/Inline when clip is clicked */}
              {playingClipUrl && (
                <Box
                  sx={{
                    mt: 3,
                    p: 2,
                    borderRadius: 2,
                    backgroundColor: 'background.default',
                    border: '1px solid rgba(255,255,255,0.15)',
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
                      <VideoLibraryIcon fontSize="small" /> Remediation Clip Stream (Byte-Range Capable)
                    </Typography>
                    <Button size="small" onClick={() => setPlayingClipUrl(null)} sx={{ color: 'primary.contrastText' }}>
                      Close Video
                    </Button>
                  </Box>
                  <Box sx={{ position: 'relative', width: '100%', pt: '56.25%', borderRadius: 1, overflow: 'hidden' }}>
                    <video
                      controls
                      autoPlay
                      src={playingClipUrl}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100%',
                      }}
                    />
                  </Box>
                </Box>
              )}
            </CardContent>
          </Card>
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

      {/* Clip Library — every clip cut for one lecture, listed and playable.
          Sits after the lecture list because it browses one of those lectures,
          and the picker above is where the default selection comes from. */}
      <Box sx={{ mt: 4 }}>
        <ClipBrowser lectures={lectureList} onCutClips={handleTriggerClips} />
      </Box>
    </Box>
  )
}
