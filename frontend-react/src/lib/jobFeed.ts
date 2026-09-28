import { useEffect } from 'react'
import { useJobStore } from '../store/useJobStore'
import type { JobOut } from '../api/types'

const BASE = (import.meta.env.VITE_LECGAP_API_URL as string | undefined) ?? ''

class JobFeedManager {
  private eventSource: EventSource | null = null
  private currentCourseId: string | null = null
  private reconnectTimer: number | null = null

  public connect(courseId?: string | null) {
    if (this.eventSource && this.currentCourseId === (courseId || null)) {
      return
    }

    this.disconnect()
    this.currentCourseId = courseId || null

    const url = new URL(`${BASE}/jobs/stream`, window.location.origin)
    if (courseId) {
      url.searchParams.set('course_id', courseId)
    }

    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      return
    }

    try {
      this.eventSource = new EventSource(url.toString())


      this.eventSource.onopen = () => {
        useJobStore.getState().setConnected(true)
      }

      this.eventSource.addEventListener('jobs', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data) as JobOut[]
          useJobStore.getState().setJobs(data)
        } catch (err) {
          console.error('[JobFeed] Failed to parse jobs event payload:', err)
        }
      })

      this.eventSource.onerror = () => {
        useJobStore.getState().setConnected(false)
        // EventSource will automatically retry in modern browsers, but we also ensure state tracks failure
      }
    } catch (err) {
      console.error('[JobFeed] Failed to create EventSource:', err)
      useJobStore.getState().setConnected(false)
    }
  }

  public disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.eventSource) {
      this.eventSource.close()
      this.eventSource = null
    }
    useJobStore.getState().setConnected(false)
  }
}

export const jobFeedManager = new JobFeedManager()

/**
 * React hook to maintain an active SSE subscription for the specified course.
 */
export function useJobFeed(courseId?: string | null) {
  useEffect(() => {
    jobFeedManager.connect(courseId)
    return () => {
      // We keep connection alive during session or disconnect on unmount if needed
    }
  }, [courseId])

  const jobs = useJobStore((state) => state.jobs)
  const isConnected = useJobStore((state) => state.isConnected)
  const activeJobs = useJobStore((state) => state.activeJobs)

  return { jobs, isConnected, activeJobs }
}

