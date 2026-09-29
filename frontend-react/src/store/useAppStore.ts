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

/** env -> localStorage -> OS preference -> shipped default. Never throws. */
export function resolveInitialBase(): Base {
  return readEnvBase() ?? readStored() ?? (prefersLight() ? 'light' : DEFAULT_BASE)
}

interface AppState {
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
  selectedCourseId: 'ml', // default course; the new-course bootstrap replaces this
  studentId: 'student_1',
  jobDrawerOpen: false,
  base: resolveInitialBase(),

  setSelectedCourseId: (courseId: string | null) => set({ selectedCourseId: courseId }),
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
