/**
 * Domain wrapper — lectures.
 * Feature components import from here; they never call client.* directly.
 */
import { get, post, postForm, del, putStream } from './client'
import type {
  LectureOut,
  LectureDetailOut,
  LectureProgressOut,
  LectureDeleteOut,
  ClipBatchOut,
} from './types'

export const lectures = {
  list: (courseId: string, limit = 500): Promise<LectureOut[]> =>
    get('/lectures', { course_id: courseId, limit }),

  get: (lectureId: number): Promise<LectureDetailOut> =>
    get(`/lectures/${lectureId}`),

  progress: (lectureId: number): Promise<LectureProgressOut> =>
    get(`/lectures/${lectureId}/progress`),

  clips: (lectureId: number): Promise<ClipBatchOut> =>
    get(`/lectures/${lectureId}/clips`),

  /** Step 1 of the two-step upload — creates the row without media. */
  create: (
    courseIdOrPayload: string | { course_id: string; title?: string; whisper_backend?: string },
    title?: string,
    whisperBackend?: string,
  ): Promise<LectureOut> => {
    const form = new FormData()
    if (typeof courseIdOrPayload === 'string') {
      form.append('course_id', courseIdOrPayload)
      if (title) form.append('title', title)
      if (whisperBackend) form.append('whisper_backend', whisperBackend)
    } else {
      form.append('course_id', courseIdOrPayload.course_id)
      if (courseIdOrPayload.title) form.append('title', courseIdOrPayload.title)
      if (courseIdOrPayload.whisper_backend) form.append('whisper_backend', courseIdOrPayload.whisper_backend)
    }
    return postForm('/lectures', form)
  },


  /**
   * Step 2 of the two-step upload — stream the file to the backend.
   * Uses XHR so upload.onprogress works (fetch has no upload progress).
   */
  uploadMedia: (
    lectureId: number,
    file: File,
    onProgress: (pct: number) => void,
    signal?: AbortSignal,
    whisperBackend?: string,
  ): Promise<LectureOut> => {
    const params = new URLSearchParams({ filename: file.name })
    if (whisperBackend) params.set('whisper_backend', whisperBackend)
    return putStream(`/lectures/${lectureId}/media?${params}`, file, onProgress, signal)
  },

  extractConcepts: (lectureId: number): Promise<LectureDetailOut> =>
    post(`/lectures/${lectureId}/concepts`),

  cutClips: (lectureId: number): Promise<ClipBatchOut> =>
    post(`/lectures/${lectureId}/clips`),

  rerun: (lectureId: number, whisperBackend?: string): Promise<LectureOut> => {
    const params = whisperBackend ? `?whisper_backend=${whisperBackend}` : ''
    return post(`/lectures/${lectureId}/rerun${params}`)
  },

  delete: (lectureId: number): Promise<LectureDeleteOut> =>
    del(`/lectures/${lectureId}`),
}
