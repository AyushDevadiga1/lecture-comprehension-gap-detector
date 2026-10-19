import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../api/lectures'
import { queryKeys } from './queryKeys'

/**
 * Poll `GET /lectures/{id}/progress` only while a lecture is transcribing.
 *
 * Per `02-backend-map.md` §4b: the SSE job feed already carries stage and
 * percentage for the *course*, so this hook is the fallback for a lecture
 * that is transcribing with no visible job (a tab opened mid-transcription).
 * It is a poll, not a stream — one connection, one timer, and it stops the
 * moment the lecture leaves `transcribing`. The parent view chooses the
 * enabled condition so a job-visible lecture never polls at all.
 */
export function useLectureProgress(
  lectureId: number | null,
  status: string | null | undefined,
): {
  data: Awaited<ReturnType<typeof lecturesApi.progress>> | undefined
  isLoading: boolean
  isError: boolean
  error: unknown
} {
  const isTranscribing = status === 'transcribing'
  const { data, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.lectureProgress(lectureId ?? -1),
    queryFn: () => {
      if (lectureId == null) throw new Error('no lecture selected')
      return lecturesApi.progress(lectureId)
    },
    enabled: lectureId != null && isTranscribing,
    // A transcribing lecture moves; a ready one never asks again.
    refetchInterval: isTranscribing ? 2000 : false,
    staleTime: 0,
  })
  return { data, isLoading, isError, error }
}
