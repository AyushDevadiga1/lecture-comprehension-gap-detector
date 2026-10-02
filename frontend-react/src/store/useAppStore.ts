import { create } from 'zustand'
import type { Base } from '../theme/tokens'
import { DEFAULT_BASE } from '../theme/tokens'

/**
 * Which theme base the app is rendering in.
 *
 * ## Where the answer comes from, and why it is a decision
 *
 * The Streamlit engine has one place that decides: `current_base()` reads
 * `[theme] base` from `.streamlit/config.toml` through Streamlit's own config
 * resolver, so every browser follows the same setting. A browser app has no
 * such config, and there are two defensible answers:
 *
 *   - the **server** decides, so every client is identical (the Streamlit
 *     behaviour), or
 *   - each client **follows its own OS**, so a user whose OS is light gets a
 *     light app.
 *
 * OPEN decision #2 in `plan/REACT_ARCHITECTURE.md` (§11), resolved as the
 * second: an explicit choice, remembered in `localStorage`, defaulting to
 * `prefers-color-scheme`, falling back to the shipped default. A build-time env
 * var is honoured first so a deployment can pin it.
 *
 * `DEFAULT_BASE` is dark, which is what the Streamlit config declares and what
 * the tokens were tuned for.
 */

const STORAGE_KEY = 'lecgap.theme'

/**
 * Persist the last selected course across reloads so the app is always in a
 * useful state after a refresh.
 *
 * The key is versioned (`v1`) so a schema change can invalidate old entries
 * without a blank-screen regression — bump the suffix to `v2` and the old
 * value is silently discarded, not misread as a new one.
 *
 * Course ids are free-form strings, so validation is minimal: we only reject
 * obviously invalid values (empty, non-string) and trust the backend to 404
 * on anything that no longer exists. That 404 is caught by the AuthBanner /
 * query error path — it is not a silent failure.
 */
const COURSE_KEY = 'lecgap.course.v1'

// ── Storage helpers (always wrapped in try/catch — private mode, storage-full,
// and browser quota errors are real production cases) ─────────────────────────

const readEnvBase = (): Base | null => {
  const raw = (import.meta.env.VITE_LECGAP_THEME_BASE as string | undefined)?.toLowerCase()
  return raw === 'light' || raw === 'dark' ? raw : null
}

const readStored = (): Base | null => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw === 'light' || raw === 'dark' ? raw : null
  } catch {
    // Private mode / disabled storage. Not a failure — fall through.
    return null
  }
}

const prefersLight = (): boolean => {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches
  } catch {
    return false
  }
}

/**
 * Read the last-selected course id from localStorage.
 *
 * Returns `null` on any error (private mode, malformed data, quota failure)
 * so the Navbar's auto-select-first-course logic always has a clean fallback.
 */
const readStoredCourse = (): string | null => {
  try {
    const raw = window.localStorage.getItem(COURSE_KEY)
    if (typeof raw !== 'string' || !raw.trim()) return null
    return raw
  } catch {
    return null
  }
}

/**
 * Write the selected course to localStorage. Failure is always silent — the
 * store still updates, only the persistence across reloads is lost.
 */
const writeStoredCourse = (courseId: string | null): void => {
  try {
    if (courseId == null) {
      window.localStorage.removeItem(COURSE_KEY)
    } else {
      window.localStorage.setItem(COURSE_KEY, courseId)
    }
  } catch {
    // Quota / private mode — non-fatal.
  }
}

/** env -> localStorage -> OS preference -> shipped default. Never throws. */
export function resolveInitialBase(): Base {
  return readEnvBase() ?? readStored() ?? (prefersLight() ? 'light' : DEFAULT_BASE)
}

/**
 * Initial course id:
 *   1. Environment override (`VITE_LECGAP_DEFAULT_COURSE`) — lets a deployment
 *      pin a specific course without a code change.
 *   2. Last selection from `localStorage` — survives page reloads.
 *   3. `null` — Navbar's `useEffect` will auto-select the first course returned
 *      by `GET /courses` once the list loads.
 *
 * Never hard-codes a course name: that was the original bug (defaulting to 'ml'
 * caused 404s on every install that didn't have that course).
 */
export function resolveInitialCourse(): string | null {
  const envOverride = (import.meta.env.VITE_LECGAP_DEFAULT_COURSE as string | undefined)?.trim()
  if (envOverride) return envOverride
  return readStoredCourse()
}

interface AppState {
  /** Currently selected course. `null` means «no course picked yet». Queries
   *  that depend on a course use `enabled: !!selectedCourseId` so nothing fires
   *  until the Navbar auto-selects one (or the user picks one). */
  selectedCourseId: string | null
  studentId: string
  jobDrawerOpen: boolean
  base: Base
  setSelectedCourseId: (courseId: string | null) => void
  setStudentId: (id: string) => void
  setJobDrawerOpen: (open: boolean) => void
  toggleJobDrawer: () => void
  setBase: (base: Base) => void
  toggleBase: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  // Start from env override or last stored choice; Navbar fills in null via
  // auto-selection once GET /courses resolves. No hard-coded course name.
  selectedCourseId: resolveInitialCourse(),
  studentId: 'student_1',
  jobDrawerOpen: false,
  base: resolveInitialBase(),

  setSelectedCourseId: (courseId: string | null) => {
    writeStoredCourse(courseId)
    set({ selectedCourseId: courseId })
  },
  setStudentId: (studentId: string) => set({ studentId }),
  setJobDrawerOpen: (jobDrawerOpen: boolean) => set({ jobDrawerOpen }),
  toggleJobDrawer: () => set((state) => ({ jobDrawerOpen: !state.jobDrawerOpen })),

  setBase: (base) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, base)
    } catch {
      // Remembering the choice is a nicety; rendering must not depend on it.
    }
    set({ base })
  },

  toggleBase: () => {
    const next = get().base === 'dark' ? 'light' : 'dark'
    get().setBase(next)
  },
}))
