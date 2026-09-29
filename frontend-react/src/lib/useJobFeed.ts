import { useEffect, useRef, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { jobFeed } from './jobFeed'
import type { FeedState } from './jobFeed'
import { createJobsSink } from './jobsSink'
import type { JobsSink } from './jobsSink'
import { queryKeys } from './queryKeys'
import { isTerminal, recordNewCompletions } from './jobCompletions'
import { isLive } from './jobStalls'
import { useNow } from './useNow'
import { useCompletionStore } from '../store/useCompletionStore'
import type { JobOut } from '../api/types'

/**
 * Job state lives in ONE React Query key. Components read it; they do not
 * subscribe to the feed and do not hold their own copy.
 *
 * This is REACT_ARCHITECTURE.md §1. The defect it exists to prevent is §0's
 * second rule: *a value that changes must never be the reason a component
 * re-renders*. The previous wiring pushed snapshots into a zustand store that
 * `AppLayout` read — and `AppLayout` renders `<Outlet/>`, so a 1 Hz job tick
 * re-rendered the entire active page, restarting any playing `<video>`. That is
 * exactly the Streamlit defect the whole rebuild was for.
 *
 * The entry holds the whole `FeedState` (jobs + mode + changeToken) rather than
 * just the rows, because `mode` is what the drawer's Live/Disconnected chip
 * needs and `changeToken` is the "did anything actually change" marker from
 * `jobfeed.changed_since(token)`. One key, §1 as written.
 *
 * ## Why `useSyncExternalStore` and not `useQuery`
 *
 * The obvious shape is `useQuery({ queryKey, queryFn: () => empty })`. It is
 * wrong, and it was wrong here first: a query with a `queryFn` *fetches*, and
 * that resolution can land after the SSE feed's first snapshot and overwrite it
 * with the empty placeholder. A key owned by the stream must never fetch.
 *
 * `useSyncExternalStore` over the query cache subscribes to exactly the same
 * store React Query uses, with no fetch, no `staleTime` game, and no polling
 * timer — the poll-by-rerender defect at a different cadence, which is §1's
 * explicitly rejected alternative.
 *
 * So: `useJobFeedConnection` *connects* and deliberately reads nothing.
 * `useJobs` / `useJobList` / `useActiveJobs` / `useJobCards` / `useFeedStatus`
 * read the cache.
 */

/** Referentially stable, so `getSnapshot` never thrashes React's bailout. */
const EMPTY_STATE: FeedState = { jobs: [], mode: 'starting', changeToken: 0 }

let connectionRefs = 0

/**
 * Keep the single feed open while at least one component needs it.
 *
 * Ref-counted so two panels asking for jobs share one connection, and the last
 * one to unmount is the one that closes it.
 */
export function useJobFeedConnection(courseId?: string | null): void {
  const queryClient = useQueryClient()

  // Completion detection needs the previous snapshot. Held here, in the data
  // layer, rather than in a component: a component that diffed the job list
  // would have to subscribe to it, and would therefore re-render on every 1 Hz
  // snapshot. Here it costs nothing.
  const prevRef = useRef<JobOut[]>([])

  const sinkRef = useRef<JobsSink<FeedState> | null>(null)
  if (!sinkRef.current) {
    sinkRef.current = createJobsSink((state: FeedState) => {
      queryClient.setQueryData(queryKeys.jobs(courseId ?? ''), state)

      const finished = recordNewCompletions(prevRef.current, state.jobs, (list) =>
        useCompletionStore.getState().push(list),
      )
      prevRef.current = state.jobs

      // The clips follow-up: a finished clip job must refresh its own list,
      // which is not course-scoped and so is not covered by invalidateCourse.
      for (const job of finished) {
        if (job.kind === 'clips' && job.lecture_id != null) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.clips(job.lecture_id) })
        }
      }
    })
  }

  useEffect(() => {
    // A course change starts a different job set; nothing from the old one can
    // be "newly completed".
    prevRef.current = []
    connectionRefs += 1
    jobFeed.connect(courseId, (state) => sinkRef.current?.write(state))
    return () => {
      connectionRefs -= 1
      if (connectionRefs === 0) jobFeed.disconnect()
    }
  }, [courseId, queryClient])
}

/** The current feed snapshot, or an empty state before the first one arrives. */
export function useJobs(courseId?: string | null): FeedState {
  const queryClient = useQueryClient()
  const key = queryKeys.jobs(courseId ?? '')
  const cache = queryClient.getQueryCache()

  return useSyncExternalStore(
    (onStoreChange) => cache.subscribe(onStoreChange),
    () => (cache.find({ queryKey: key })?.state.data as FeedState | undefined) ?? EMPTY_STATE,
    () => EMPTY_STATE,
  )
}

/** The flat job list. */
export function useJobList(courseId?: string | null): JobOut[] {
  return useJobs(courseId).jobs
}

/**
 * Jobs still running and still worth showing.
 *
 * Terminal jobs are out (announced once by `JobCompletionHost`), and a job
 * watched past the six-hour backstop is dropped too — that is C0's fix for the
 * six-hour spinner, applied where the spinner actually was.
 */
export function useActiveJobs(courseId?: string | null): JobOut[] {
  const jobs = useJobList(courseId).filter((j) => !isTerminal(j))
  const now = useNow(jobs.length > 0)
  return jobs.filter((j) => isLive(j, now))
}

/**
 * Lecture ids with work in flight, so a panel can disable its actions and the
 * C0 rule holds: no double-fired work.
 */
export function useBusyLectureIds(courseId?: string | null): Set<number> {
  const busy = new Set<number>()
  for (const job of useActiveJobs(courseId)) {
    if (job.lecture_id != null) busy.add(job.lecture_id)
  }
  return busy
}

/**
 * One card per lecture, derived from the flat job list.
 *
 * A lecture can have more than one job (transcribe, then extract, then clips);
 * the card shows the newest one still in flight, falling back to the newest
 * overall so a lecture that just finished keeps its card until the next snapshot.
 */
export interface JobCard {
  lectureId: number
  lectureTitle: string
  courseId: string | null
  job: JobOut
  isFinal: boolean
}

export function useJobCards(courseId?: string | null): JobCard[] {
  const jobs = useJobList(courseId)

  const byLecture = new Map<number, JobOut[]>()
  for (const j of jobs) {
    if (j.lecture_id == null) continue
    const list = byLecture.get(j.lecture_id) ?? []
    list.push(j)
    byLecture.set(j.lecture_id, list)
  }

  const cards: JobCard[] = []
  for (const [lectureId, list] of byLecture) {
    const inFlight = list.filter((j) => !j.terminal)
    const pick = (inFlight.length ? inFlight : list).reduce((a, b) => (a.id >= b.id ? a : b))
    cards.push({
      lectureId,
      lectureTitle: pick.title ?? `Lecture ${lectureId}`,
      courseId: pick.course_id ?? null,
      job: pick,
      isFinal: inFlight.length === 0,
    })
  }
  return cards.sort((a, b) => a.lectureId - b.lectureId)
}

/** Connection health, for the drawer's Live/Disconnected chip. */
export function useFeedStatus(courseId?: string | null): Pick<FeedState, 'mode' | 'changeToken'> {
  const { mode, changeToken } = useJobs(courseId)
  return { mode, changeToken }
}
