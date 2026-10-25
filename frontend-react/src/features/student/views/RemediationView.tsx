import React, { useState } from 'react'
import { Alert, Box, Button, Card, CardContent, Chip, Typography } from '@mui/material'
import MapOutlinedIcon from '@mui/icons-material/MapOutlined'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { quizzes as quizzesApi } from '../../../api/quizzes'
import { queryKeys } from '../../../lib/queryKeys'
import { useQuizStore } from '../../../store/useQuizStore'
import { useAppStore } from '../../../store/useAppStore'
import type { RemediationOut } from '../../../api/types'

/**
 * Remediation — the study plan the quiz produced, in dependency order.
 *
 * P3: the plan now survives a reload. The in-memory quiz result wins when it
 * exists (it is the freshest possible), and the server is the fallback. The
 * query key is keyed on the student id, so a reload reuses the cached plan.
 *
 * Each concept item now has two actions:
 *   ▶ Play clip  — plays the lecture clip inline in the right panel
 *   Map          — navigates to /student/map with the concept pre-selected
 *                  so the student can see exactly where it sits in the graph
 */
export const RemediationView: React.FC = () => {
  const { selectedCourseId, studentId } = useAppStore()
  const navigate = useNavigate()
  const result = useQuizStore((s) => s.result)
  const [playing, setPlaying] = useState<string | null>(null)

  const { data: serverPlan } = useQuery<RemediationOut>({
    queryKey: queryKeys.remediation(studentId),
    queryFn: () =>
      selectedCourseId
        ? quizzesApi.getRemediation(studentId, selectedCourseId)
        : Promise.reject(new Error('no course')),
    enabled: !!selectedCourseId && result == null,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  const plan  = result?.remediation ?? serverPlan?.remediation ?? []
  const score = result?.score ?? serverPlan?.score
  const total = result?.total ?? serverPlan?.total

  /** Navigate to the concept map with the concept name as a search param so
   *  DagView can auto-select it (the find-concept box already accepts the param). */
  const showOnMap = (conceptName: string) => {
    navigate(`/student/map?find=${encodeURIComponent(conceptName)}`)
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Remediation</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Concepts you missed, traced backwards through the prerequisite graph and
          ordered so you study foundations first. Each step links to the exact
          lecture clip where that concept was taught.
        </Typography>
      </Box>

      {plan.length === 0 ? (
        <Alert severity="info">
          Nothing to remediate yet — take the quiz first, and wrong answers will
          produce an ordered study plan here.
        </Alert>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {(score != null || total != null) && (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              Last attempt: {score ?? '—'} / {total ?? '—'}
            </Typography>
          )}

          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
              gap: 2,
            }}
          >
            {/* ── Study order list ─────────────────────────────────────── */}
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 1.5 }}>
                  Study in this order
                </Typography>
                {plan.map((item, idx) => (
                  <Box
                    key={`${idx}-${item.concept}`}
                    sx={{
                      display: 'flex',
                      gap: 1.5,
                      py: 1.2,
                      borderBottom: idx === plan.length - 1 ? 'none' : '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    {/* Step number */}
                    <Typography
                      sx={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.72rem',
                        color: 'text.secondary',
                        minWidth: 20,
                        pt: 0.25,
                      }}
                    >
                      {idx + 1}
                    </Typography>

                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      {/* Concept name + kind badge */}
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {item.concept}
                        </Typography>
                        <Chip
                          label={item.failed ? 'failed' : 'prerequisite'}
                          size="small"
                          color={item.failed ? 'error' : 'warning'}
                          variant="outlined"
                          sx={{ fontSize: '0.65rem', height: 18 }}
                        />
                      </Box>

                      {/* Action buttons */}
                      <Box sx={{ display: 'flex', gap: 1, mt: 0.75, flexWrap: 'wrap' }}>
                        {item.clip_url ? (
                          <Button
                            size="small"
                            startIcon={<PlayArrowIcon sx={{ fontSize: '0.9rem' }} />}
                            sx={{ px: 1, minWidth: 0, fontSize: '0.72rem' }}
                            onClick={() => setPlaying(item.clip_url ?? null)}
                            variant={playing === item.clip_url ? 'contained' : 'text'}
                          >
                            Play clip
                          </Button>
                        ) : (
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            no clip cut yet
                          </Typography>
                        )}

                        <Button
                          size="small"
                          startIcon={<MapOutlinedIcon sx={{ fontSize: '0.9rem' }} />}
                          sx={{ px: 1, minWidth: 0, fontSize: '0.72rem' }}
                          onClick={() => showOnMap(item.concept)}
                        >
                          Show on map
                        </Button>
                      </Box>
                    </Box>
                  </Box>
                ))}
              </CardContent>
            </Card>

            {/* ── Clip player ──────────────────────────────────────────── */}
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 1.5 }}>
                  Clip
                </Typography>
                {playing ? (
                  <>
                    <Box
                      component="video"
                      controls
                      src={playing}
                      sx={{
                        width: '100%',
                        borderRadius: 2,
                        backgroundColor: 'common.black',
                      }}
                    />
                    <Button
                      size="small"
                      sx={{ mt: 1, fontSize: '0.72rem' }}
                      onClick={() => setPlaying(null)}
                    >
                      Close
                    </Button>
                  </>
                ) : (
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    Click <strong>▶ Play clip</strong> on any step to watch the lecture
                    segment for that concept here.
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Box>
        </Box>
      )}
    </Box>
  )
}
