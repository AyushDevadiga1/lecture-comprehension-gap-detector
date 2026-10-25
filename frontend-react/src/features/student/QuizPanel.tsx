import React from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  FormControlLabel,
  LinearProgress,
  Radio,
  RadioGroup,
  Typography,
} from '@mui/material'
import QuizIcon from '@mui/icons-material/Quiz'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
import CloseIcon from '@mui/icons-material/Close'
import { motion } from 'framer-motion'
import type { QuizDraft } from '../../store/useQuizStore'
import type { QuizSubmitOut } from '../../api/types'
import { LoadingScreen } from '../../components/common/LoadingScreen'
import { ErrorAlert } from '../../components/common/ErrorAlert'
import { SectionIcon } from '../../components/common/SectionIcon'
import { VideoPlayer } from '../../components/media/VideoPlayer'
import { gradient, tint, token } from '../../theme/alpha'

/**
 * The comprehension quiz: idle → generating → answering → graded.
 *
 * ## Why this is a component
 *
 * It used to be ~250 lines of JSX inline in `StudentDashboard`, which meant the
 * page owned four mutually exclusive states of a single flow and could only
 * ever be read by scrolling past the upload form. Extracted, the states are
 * visible in one return, and the page passes data and intent in — no quiz
 * logic, no store wiring, no mutation knowledge.
 *
 * ## Design decisions
 *
 * - **Answer as tiles, not a radio list.** The options are still a real
 *   `RadioGroup` (the value/onChange contract and the 153-question stress test
 *   both depend on it), but each `FormControlLabel` is painted as a selectable
 *   card: the whole row is the target, the picked one is tinted and ringed.
 * - **Progress is stated, not implied.** "4 of 10 answered" plus a determinate
 *   bar, so the submit button's disabled state has an obvious cause.
 * - **The score is a gauge.** A number alone ("7 / 10") makes the reader do the
 *   arithmetic; the arc does it, and the copy under it interprets the band.
 * - **Remediation reads as a sequence**, because that is what it is: a numbered
 *   rail where each step keeps its own Watch Clip action.
 *
 * Everything is token-driven (REACT_ARCHITECTURE §4): no colour literal is
 * spelled in this file, only `tint()`/`token()`/`gradient()` and MUI slots.
 */

export interface QuizPanelProps {
  /** The cap the button and the caption must both be derived from. */
  maxQuestions: number
  generatePending: boolean
  onGenerate: () => void
  draft: QuizDraft | null
  result: QuizSubmitOut | null
  onSelectAnswer: (questionId: number, option: string) => void
  onSubmit: () => void
  submitPending: boolean
  onReset: () => void
  error: string | null
  warning: string | null
  clipUrl: string | null
  onCloseClip: () => void
  /** Play a remediation clip inside this panel. */
  onWatchClip: (url: string) => void
}

/** Human read of the score band, so the result says something, not just shows. */
function verdict(score: number, total: number): { title: string; tone: 'ok' | 'warn' | 'bad' } {
  if (total <= 0) return { title: 'No questions graded', tone: 'warn' }
  const pct = (score / total) * 100
  if (pct >= 80) return { title: 'Solid foundation — move on', tone: 'ok' }
  if (pct >= 50) return { title: 'Partial grasp — review the gaps below', tone: 'warn' }
  return { title: 'Foundational gaps — work the sequence in order', tone: 'bad' }
}

export const QuizPanel: React.FC<QuizPanelProps> = ({
  maxQuestions,
  generatePending,
  onGenerate,
  draft,
  result,
  onSelectAnswer,
  onSubmit,
  submitPending,
  onReset,
  error,
  warning,
  clipUrl,
  onCloseClip,
  onWatchClip,
}) => {
  const answered = draft ? Object.keys(draft.answers).length : 0
  const total = draft ? draft.quiz.questions.length : 0
  const pctDone = total > 0 ? (answered / total) * 100 : 0

  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <SectionIcon>
              <QuizIcon sx={{ color: 'primary.main', fontSize: 20 }} />
            </SectionIcon>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Comprehension Quiz &amp; Gap Detection
            </Typography>
          </Box>
          {!draft && !result && (
            <Button
              variant="contained"
              color="secondary"
              onClick={onGenerate}
              disabled={generatePending}
            >
              {generatePending ? 'Queueing...' : 'Start Quiz'}
            </Button>
          )}
        </Box>

        {/* The cap is visible before generation, not discovered after. */}
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
          Up to {maxQuestions} questions, drawn evenly from across the course&apos;s concepts.
        </Typography>

        {error && <ErrorAlert error={error} title="Quiz Error" />}
        {warning && <ErrorAlert error={warning} title="Quiz cap not applied" />}

        {generatePending && (
          <LoadingScreen message="Queueing quiz generation. The job appears in Background Tasks and the quiz opens itself when it is ready." />
        )}

        {/* Active quiz */}
        {draft && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                border: '1px solid',
                borderColor: 'divider',
                backgroundColor: tint('text', 3),
              }}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  {answered} of {total} answered
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Incorrect answers walk the prerequisite graph backwards into your
                  remediation plan.
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={pctDone}
                sx={{
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: tint('text', 10),
                  '& .MuiLinearProgress-bar': {
                    borderRadius: 4,
                    background: gradient('info', 'ok'),
                  },
                }}
              />
            </Box>

            {/* The card is a viewport, not a runway. A 15-question quiz used to
                stretch the page to twenty screens; the questions now scroll
                inside the card, with the progress line above and the submit bar
                below both pinned outside that scroll region. */}
            <Box
              sx={{
                // Responsive height: fills remaining viewport after header (~72px),
                // card padding (2×24px), title row (~40px), caption (~20px), progress
                // bar (~56px), and submit bar (~72px). Min so it never collapses.
                maxHeight: 'clamp(220px, calc(100vh - 380px), 56vh)',
                overflowY: 'auto',
                overscrollBehavior: 'contain',
                pr: 0.5,
                display: 'flex',
                flexDirection: 'column',
                gap: 2.5,
              }}
            >
            {draft.quiz.questions.map((q, idx) => {
              const picked = draft.answers[q.id] ?? ''
              return (
                <Box
                  key={q.id}
                  sx={{
                    p: 2,
                    borderRadius: 2,
                    border: '1px solid',
                    borderColor: 'divider',
                    backgroundColor: 'background.paper',
                    boxShadow: `0 1px 3px ${tint('text', 6)}`,
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
                    <Box
                      sx={{
                        width: 26,
                        height: 26,
                        flexShrink: 0,
                        borderRadius: '50%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        backgroundColor: picked ? 'info.main' : tint('text', 10),
                        color: picked ? 'info.contrastText' : 'text.secondary',
                      }}
                    >
                      {idx + 1}
                    </Box>
                    <Chip
                      size="small"
                      variant="outlined"
                      color="info"
                      label={q.concept}
                      sx={{ maxWidth: 260, fontWeight: 600 }}
                    />
                    {picked && (
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        answered
                      </Typography>
                    )}
                  </Box>

                  <Typography variant="body1" sx={{ fontWeight: 600, mb: 1.5 }}>
                    {q.question}
                  </Typography>

                  <FormControl component="fieldset" sx={{ width: '100%' }}>
                    <RadioGroup
                      value={picked}
                      onChange={(e) => onSelectAnswer(q.id, e.target.value)}
                      name={`q-${q.id}`}
                    >
                      {(q.options?.length ? q.options : ['correct', 'incorrect', 'wrong']).map(
                        (opt, optIdx) => {
                          const isPicked = picked === opt
                          return (
                            <FormControlLabel
                              key={optIdx}
                              value={opt}
                              control={<Radio size="small" />}
                              label={
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Typography
                                    variant="caption"
                                    sx={{
                                      color: 'text.disabled',
                                      fontWeight: 600,
                                      minWidth: 14,
                                    }}
                                  >
                                    {String.fromCharCode(65 + optIdx)}
                                  </Typography>
                                  <Typography variant="body2">{opt}</Typography>
                                </Box>
                              }
                              sx={{
                                m: 0,
                                mb: 0.75,
                                width: '100%',
                                px: 1.25,
                                py: 0.6,
                                borderRadius: 2,
                                border: '1px solid',
                                borderColor: isPicked ? 'info.main' : 'divider',
                                backgroundColor: isPicked ? tint('info', 14) : 'transparent',
                                transition: 'background-color 0.15s ease, border-color 0.15s ease',
                                '&:hover': {
                                  backgroundColor: isPicked ? tint('info', 18) : tint('text', 5),
                                },
                                '& .MuiRadio-root': { py: 0 },
                              }}
                            />
                          )
                        },
                      )}
                    </RadioGroup>
                  </FormControl>
                </Box>
              )
            })}
            </Box>

            <Box
              sx={{
                pt: 1.5,
                pb: 1,
                display: 'flex',
                alignItems: 'center',
                gap: 2,
                backgroundColor: 'background.paper',
                borderTop: '1px solid',
                borderColor: 'divider',
              }}
            >
              <Button
                variant="contained"
                color="primary"
                size="large"
                onClick={onSubmit}
                disabled={submitPending || answered === 0}
                sx={{ px: 4 }}
              >
                {submitPending ? 'Grading...' : 'Submit Answers'}
              </Button>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {answered === 0
                  ? 'Pick at least one answer to submit.'
                  : `${answered} answer${answered === 1 ? '' : 's'} ready to grade.`}
              </Typography>
            </Box>
          </Box>
        )}

        {/* Result */}
        {result && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: 'easeOut' }}
            >
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 3,
                  p: 2.5,
                  borderRadius: 3,
                  border: '1px solid',
                  borderColor: tint('info', 40),
                  backgroundColor: tint('info', 12),
                }}
              >
                <Box sx={{ position: 'relative', width: 116, height: 116, flexShrink: 0 }}>
                  <svg width={116} height={116} viewBox="0 0 116 116" aria-hidden="true">
                    <circle
                      cx={58}
                      cy={58}
                      r={50}
                      fill="none"
                      strokeWidth={11}
                      style={{ stroke: token('track') }}
                    />
                    <circle
                      cx={58}
                      cy={58}
                      r={50}
                      fill="none"
                      strokeWidth={11}
                      strokeLinecap="round"
                      strokeDasharray={2 * Math.PI * 50}
                      strokeDashoffset={
                        2 * Math.PI * 50 * (1 - (result.total > 0 ? result.score / result.total : 0))
                      }
                      transform="rotate(-90 58 58)"
                      style={{ stroke: token('accent'), transition: 'stroke-dashoffset 0.7s ease' }}
                    />
                  </svg>
                  <Box
                    sx={{
                      position: 'absolute',
                      inset: 0,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Typography variant="h5" sx={{ fontWeight: 600, lineHeight: 1 }}>
                      {result.total > 0 ? Math.round((result.score / result.total) * 100) : 0}%
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      {result.score}/{result.total}
                    </Typography>
                  </Box>
                </Box>

                <Box>
                  <Typography variant="overline" sx={{ color: 'text.secondary', fontWeight: 700 }}>
                    Quiz complete
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    {verdict(result.score, result.total).title}
                  </Typography>
                  <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                    Student {result.student_id} &middot; Quiz #{result.quiz_id}
                  </Typography>
                </Box>
              </Box>
            </motion.div>

            {/* Remediation sequence */}
            {result.remediation.length > 0 && (
              <Box>
                <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
                  Remediation sequence
                </Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                  Study these in order — each step only assumes the ones above it.
                  Failed concepts come with the clip that re-teaches them.
                </Typography>

                <Box
                  sx={{
                    maxHeight: 320,
                    overflowY: 'auto',
                    overscrollBehavior: 'contain',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 1,
                  }}
                >
                  {result.remediation.map((item, idx) => (
                    <Box
                      key={idx}
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 1.5,
                        p: 1.5,
                        pl: idx === 0 ? 1.5 : 2.25,
                        borderRadius: 2,
                        border: '1px solid',
                        borderColor: item.failed ? 'warning.main' : 'divider',
                        borderLeft: `3px solid ${
                          item.failed ? token('warn') : token('border')
                        }`,
                        backgroundColor: item.failed ? tint('warn', 10) : tint('text', 3),
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, minWidth: 0 }}>
                        <Typography
                          variant="subtitle2"
                          sx={{ color: 'text.secondary', fontWeight: 600, minWidth: 26 }}
                        >
                          {String(idx + 1).padStart(2, '0')}
                        </Typography>
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="body2" sx={{ fontWeight: 700 }} noWrap>
                            {item.concept}
                          </Typography>
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            {item.failed
                              ? 'You missed this — watch before moving on'
                              : 'Prerequisite foundation'}
                          </Typography>
                        </Box>
                      </Box>

                      {item.clip_url ? (
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<PlayCircleOutlineIcon />}
                          onClick={() => {
                            // Re-narrowed here: TS does not carry the outer
                            // ternary's narrowing into a later callback.
                            if (item.clip_url) onWatchClip(item.clip_url)
                          }}
                          sx={{ flexShrink: 0 }}
                        >
                          Watch Clip
                        </Button>
                      ) : (
                        <Typography variant="caption" sx={{ color: 'text.disabled', flexShrink: 0 }}>
                          Clip not ready
                        </Typography>
                      )}
                    </Box>
                  ))}
                </Box>
              </Box>
            )}

            {/* Feedback */}
            {result.feedback.length > 0 && (
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                  Item feedback &amp; explanations
                </Typography>
                <Box
                  sx={{
                    maxHeight: 420,
                    overflowY: 'auto',
                    overscrollBehavior: 'contain',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 1,
                  }}
                >
                  {result.feedback.map((f) => (
                    <Box
                      key={f.question_id}
                      sx={{
                        p: 1.75,
                        borderRadius: 2,
                        border: '1px solid',
                        borderColor: f.correct ? 'success.main' : 'error.main',
                        borderLeft: `3px solid ${
                          f.correct ? token('ok') : token('bad')
                        }`,
                        backgroundColor: f.correct ? tint('ok', 8) : tint('bad', 8),
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                        {f.correct ? (
                          <CheckCircleIcon sx={{ color: 'success.main', fontSize: 18 }} />
                        ) : (
                          <CancelIcon sx={{ color: 'error.main', fontSize: 18 }} />
                        )}
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
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
              </Box>
            )}

            <Button variant="outlined" onClick={onReset} sx={{ alignSelf: 'flex-start' }}>
              Done / Retake Later
            </Button>
          </Box>
        )}

        {/* Remediation clip, played in the same player the library uses. */}
        {clipUrl && (
          <Box sx={{ mt: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
                <PlayCircleOutlineIcon fontSize="small" /> Remediation clip
              </Typography>
              <Button size="small" startIcon={<CloseIcon />} onClick={onCloseClip}>
                Close
              </Button>
            </Box>
            <VideoPlayer src={clipUrl} autoPlay />
          </Box>
        )}

        {!draft && !result && !generatePending && !error && (
          <Alert severity="info" sx={{ mt: 1 }}>
            Answer the diagnostic questions below. Incorrect answers trace prerequisites
            backwards along the DAG to form your personalised remediation plan.
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

