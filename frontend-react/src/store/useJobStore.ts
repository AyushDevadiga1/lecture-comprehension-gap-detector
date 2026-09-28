import { create } from 'zustand'
import type { JobOut } from '../api/types'

interface JobState {
  jobs: JobOut[]
  activeJobs: JobOut[]
  isConnected: boolean
  lastUpdated: string | null
  setJobs: (jobs: JobOut[]) => void
  setConnected: (connected: boolean) => void
  getJobById: (id: number) => JobOut | undefined
}

export const useJobStore = create<JobState>((set, get) => ({
  jobs: [],
  activeJobs: [],
  isConnected: false,
  lastUpdated: null,

  setJobs: (jobs: JobOut[]) => {
    set({
      jobs,
      activeJobs: jobs.filter((j) => !j.terminal),
      lastUpdated: new Date().toISOString(),
    })
  },

  setConnected: (isConnected: boolean) => set({ isConnected }),

  getJobById: (id: number) => {
    return get().jobs.find((j) => j.id === id)
  },
}))

