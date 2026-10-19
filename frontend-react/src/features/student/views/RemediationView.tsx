import React, { useState } from 'react'
import { Alert, Box, Button, Card, CardContent, Typography } from '@mui/material'
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
 */
export const RemediationView: React.FC = () => {
  const { selectedCourseId, studentId } = useAppStore()
  const result = useQuizStore((s) => s.result)
  const [playing, setPlaying] = useState<string | null>(null)

  const { data: serverPlan } = useQuery<RemediationOut>({
    queryKey: queryKeys.remediation(studentId),
    queryFn: () =>
      selectedCourseId ? quizzesApi.getRemediation(studentId, selectedCourseId) : Promise.reject(new Error('no course')),
    enabled: !!selectedCourseId && result == null,
  })

  if (!selectedCourseId) {
    return <Typography color="text.secondary">Select a course to begin.</Typography>
  }

  const plan = result?.remediation ?? serverPlan?.remediation ?? []
  const score = result?.score ?? serverPlan?.score
  const total = result?.total ?? serverPlan?.total

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="h4">Remediation</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
          Wrong answers traced backwards along the DAG, in the order the concepts need to be
          understood. Student <span className="mono">{studentId}</span>.
        </Typography>
      </Box>

      {plan.length === 0 ? (
        <Alert severity="info">
          Nothing to remediate yet — take the quiz first, and wrong answers will produce an
          ordered study plan here.
        </Alert>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {(score != null || total != null) && (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              Last attempt: {score ?? '—'} / {total ?? '—'}
            </Typography>
          )}
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
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
                      py: 1,
                      borderBottom: idx === plan.length - 1 ? 'none' : '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Typography
                      sx={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'text.secondary', minWidth: 20 }}
                    >
                      {idx + 1}
                    </Typography>
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {item.concept}{' '}
                        <Typography
                          component="span"
                          variant="caption"
                          sx={{ color: 'warning.main', fontWeight: 600 }}
                        >
                          ({item.failed ? 'failed' : 'prerequisite'})
                        </Typography>
                      </Typography>
                      {item.clip_url ? (
                        <Button
                          size="small"
                          sx={{ px: 0, minWidth: 0, fontSize: '0.72rem' }}
                          onClick={() => setPlaying(item.clip_url ?? null)}
                        >
                          ▶ Play clip
                        </Button>
                      ) : (
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                          no clip cut for this concept yet
                        </Typography>
                      )}
                    </Box>
                  </Box>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 1.5 }}>
                  Clip
                </Typography>
                {playing ? (
                  <Box
                    component="video"
                    controls
                    src={playing}
                    sx={{ width: '100%', borderRadius: 2, backgroundColor: 'common.black' }}
                  />
                ) : (
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    Pick a step&apos;s clip to play it here.
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
