import React, { useEffect, useRef, useState } from 'react'
import { Box, Typography } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { quizzes as quizzesApi } from '../../../api/quizzes'
import {
  capViolation,
  generationError,
  latencySince,
  quizMaxQuestions,
  submitError,
} from '../../../lib/quiz'
import { useJobList } from '../../../lib/useJobFeed'
import { draftForCourse, useQuizStore } from '../../../store/useQuizStore'
import { useAppStore } from '../../../store/useAppStore'
import { QuizPanel } from '../QuizPanel'

/**
 * The diagnostic quiz — start, answer, submit, review.
 *
 * Lifted from `StudentDashboard` verbatim at P0: the state machine is the same
 * and the wire is the same (`POST /quizzes/jobs` → watch the job → `GET
 * /quizzes` → `POST /quizzes/submit`). `quizWiring.test.tsx` renders this view
 * directly, which is strictly better than rendering the whole dashboard to
 * reach the button.
 */
export const QuizView: React.FC = () => {
  const { selectedCourseId, studentId } = useAppStore()

  const draft = useQuizStore((s) => draftForCourse(s, selectedCourseId))
  const quizResult = useQuizStore((s) => s.result)
  const startQuiz = useQuizStore((s) => s.start)
  const finishQuiz = useQuizStore((s) => s.finish)
  const clearQuiz = useQuizStore((s) => s.clear)
  const resetQuiz = useQuizStore((s) => s.reset)
  const selectAnswer = useQuizStore((s) => s.select)

  const [quizError, setQuizError] = useState<string | null>(null)
  const [quizWarning, setQuizWarning] = useState<string | null>(null)
  const [playingClipUrl, setPlayingClipUrl] = useState<string | null>(null)

  /** The id of the quiz job we started, so we can watch it for completion. */
  const quizJobIdRef = useRef<number | null>(null)

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

  const jobs = useJobList(selectedCourseId)
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

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Comprehension quiz</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Wrong answers trace prerequisites backwards along the DAG into an ordered
          remediation plan. The cap is stated on the panel below, once.
        </Typography>
      </Box>

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
    </Box>
  )
}
