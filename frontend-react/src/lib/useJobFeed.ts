import { useEffect } from 'react'
import { jobFeed } from './jobFeed'
import { useJobStore } from '../store/useJobStore'
import type { JobOut } from '../api/types'

/**
 * Keep the SSE subscription alive for `courseId`, and expose the snapshot.
 *
 * ## Temporary
 *
 * This hook is the seam the W1.1 transport landed on, and it is replaced in
 * W1.2: REACT_ARCHITECTURE.md §1 says the feed writes into **one React Query
 * key** and that *no component subscribes to it*. Today `AppLayout` calls this
 * hook, ignores its return value, and still subscribes — so a 1Hz job tick
 * re-renders the whole page, including any playing `<video>`. That is the exact
 * defect §0 of that document was written to prevent, so it is not left standing
 * for long.
 *
 * Until then the zustand store is the sink, and this hook is the only writer.
 */
export function useJobFeed(courseId?: string | null) {
  useEffect(() => {
    const unsubscribe = jobFeed.subscribe((state) => {
      useJobStore.getState().setJobs(state.jobs)
      useJobStore.getState().setConnected(state.mode === 'stream')
    })
    jobFeed.connect(courseId)
    return unsubscribe
  }, [courseId])

  const jobs = useJobStore((state) => state.jobs)
  const isConnected = useJobStore((state) => state.isConnected)
  const activeJobs = useJobStore((state) => state.activeJobs)

  return { jobs: jobs as JobOut[], isConnected, activeJobs }
}
