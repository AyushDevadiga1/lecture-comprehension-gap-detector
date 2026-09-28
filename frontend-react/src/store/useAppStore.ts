import { create } from 'zustand'

interface AppState {
  selectedCourseId: string | null
  studentId: string
  jobDrawerOpen: boolean
  setSelectedCourseId: (courseId: string | null) => void
  setStudentId: (id: string) => void
  setJobDrawerOpen: (open: boolean) => void
  toggleJobDrawer: () => void
}

export const useAppStore = create<AppState>((set) => ({
  selectedCourseId: 'ml', // default course
  studentId: 'student_1',
  jobDrawerOpen: false,

  setSelectedCourseId: (courseId: string | null) => set({ selectedCourseId: courseId }),
  setStudentId: (studentId: string) => set({ studentId }),
  setJobDrawerOpen: (jobDrawerOpen: boolean) => set({ jobDrawerOpen }),
  toggleJobDrawer: () => set((state) => ({ jobDrawerOpen: !state.jobDrawerOpen })),
}))
