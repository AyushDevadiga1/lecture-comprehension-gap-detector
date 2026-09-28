import { create } from 'zustand'
import type { JobAnnouncement } from '../lib/jobCompletions'

/**
 * Completed-job announcements: a short-lived queue the page body renders.
 *
 * ## Why this is zustand and not React Query
 *
 * REACT_ARCHITECTURE.md §2 splits state on "if losing it loses information the
 * server has, it is server state; if losing it loses nothing but the user's
 * typing, it is UI state". An announcement is neither: it is a record of a
 * transition the server has already told us about, and it is consumed once. It
 * belongs in neither cache, so it gets its own tiny store.
 *
 * This is *not* the §1 violation that `useJobStore` was. That store held
 * progress, and a component subscribed to it, so a 1 Hz tick re-rendered the
 * page. This store only changes when a job **completes** — a handful of times
 * per session — and its consumers are the snackbar host and nothing else.
 *
 * "Announced once" is guaranteed by two things working together:
 *   - `diffCompletions` only reports the *transition* into a terminal state, so
 *     the feed re-sending the same snapshot forever does not re-announce; and
 *   - `push` replaces any existing entry for the same `jobId`, so a second
 *     announcement cannot stack.
 */

export interface Announcement extends JobAnnouncement {
  /** Stable key for the snackbar. */
  id: string
  at: number
}

interface CompletionState {
  items: Announcement[]
  push: (announcements: JobAnnouncement[]) => void
  dismiss: (id: string) => void
  clear: () => void
}

export const useCompletionStore = create<CompletionState>((set) => ({
  items: [],

  push: (announcements) =>
    set((state) => {
      if (announcements.length === 0) return state
      const incoming = announcements.map((a) => ({
        ...a,
        id: `job-${a.jobId}`,
        at: Date.now(),
      }))
      const ids = new Set(incoming.map((a) => a.id))
      return {
        items: [
          // Replace a re-announcement of the same job rather than stacking it.
          ...state.items.filter((existing) => !ids.has(existing.id)),
          ...incoming,
        ],
      }
    }),

  dismiss: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),

  clear: () => set({ items: [] }),
}))
