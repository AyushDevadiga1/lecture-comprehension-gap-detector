import { createQueryClient } from './authBanner'

/** The app-wide client. Production code uses this; tests use their own. */
export const queryClient = createQueryClient()
