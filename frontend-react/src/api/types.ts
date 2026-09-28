/**
 * API type definitions — generated from backend/api/schemas.py (contract v2).
 *
 * Rule: every type here MUST match a Pydantic model in schemas.py.
 * Drift fails the OpenAPI snapshot test (C4 gate), not silent runtime breakage.
 *
 * v2 additions over v1:
 *   - ClipOut.url  (canonical /media/clips/{id}/{file} URL — never a fs path)
 *   - WatchItemOut.clip_url (same)
 *   - JobOut, JobListOut, JobAcceptedOut  (Engine 2 / C2)
 */

// ── Lectures ──────────────────────────────────────────────────────────────────

export interface SegmentOut {
  idx: number
  start_s: number
  end_s: number
  text: string
}

export interface ConceptOut {
  id: number
  name: string
  source: string
  implicit: boolean
  start_s?: number
  end_s?: number
}

export interface LectureOut {
  id: number
  course_id: string
  title: string
  status: 'uploaded' | 'transcribing' | 'ready' | 'error'
  error?: string | null
  created_at: string
  processed_at?: string | null
  has_media: boolean
  job_id?: number | null
}

export interface LectureDetailOut extends LectureOut {
  segments: SegmentOut[]
  concepts: ConceptOut[]
}

export interface LectureProgressOut {
  lecture_id: number
  status: string
  stage: string
  progress_pct: number
  detail: string
  elapsed_s: number
  duration_s?: number | null
  updated_at: string
}

export interface LectureDeleteOut {
  deleted: boolean
  lecture_id: number
  message: string
}

// ── Courses ───────────────────────────────────────────────────────────────────

export interface CourseSummaryOut {
  course_id: string
  total_lectures: number
  ready_lectures: number
  total_concepts: number
  has_graph: boolean
  node_count: number
  edge_count: number
}

export interface CourseDeleteOut {
  deleted: boolean
  course_id: string
  lectures_removed: number
  message: string
}

export interface GraphEdgeOut {
  source: string
  target: string
  confidence: number
  source_method: string
  evidence?: string | null
}

export interface CourseGraphOut {
  course_id: string
  nodes: string[]
  edges: GraphEdgeOut[]
  node_count: number
  edge_count: number
  is_dag: boolean
  topological_order: string[]
}

export interface CourseBuildOut {
  status: string
  course_id: string
  job_id?: number | null
}

// Snapshot (GET /courses/{id}/snapshot)
export interface CourseSnapshot {
  exists: boolean
  lectures: {
    total: number
    ready: number
    uploaded: number
    transcribing: number
    error: number
  }
  concepts: number
  graph: { has: boolean; nodes: number; edges: number }
  clips: { cut: number; ok: number }
  quiz: { questions: number; respondents: number }
  in_flight: Array<{
    lecture_id: number
    title: string
    status: string
    stage: string
    progress_pct: number
  }>
}

// Stats (GET /courses/{id}/stats)
export interface CourseStats {
  course_id: string
  heatmap: Array<{ concept: string; wrong: number; attempts: number; rate: number }>
  divergence: Array<{ concept: string; taught_idx?: number; learned_idx?: number; gap: number }>
  taught_order: string[]
  learned_order: string[]
}

// ── Clips ─────────────────────────────────────────────────────────────────────

export interface ClipOut {
  id: number
  lecture_id: number
  concept_name: string
  start_s: number
  end_s: number
  /** @deprecated — use `url` (contract v2). Only present for Streamlit compat. */
  path: string
  /** Canonical URL: /media/clips/{lecture_id}/{filename} */
  url?: string | null
  ok: boolean
  error?: string | null
}

export interface ClipBatchOut {
  lecture_id: number
  status: string
  clips: ClipOut[]
  job_id?: number | null
}

// ── Quiz ──────────────────────────────────────────────────────────────────────

export interface QuizQuestionOut {
  id: number
  concept: string
  question: string
  options: string[]
}

export interface QuizOut {
  quiz_id: number
  course_id: string
  student_id: string
  questions: QuizQuestionOut[]
}

export interface QuizAnswerIn {
  question_id: number
  selected?: string | null
  latency_s?: number | null
}

export interface QuizSubmitIn {
  course_id: string
  student_id: string
  answers: QuizAnswerIn[]
}

export interface WatchItemOut {
  concept: string
  failed: boolean
  /** @deprecated — use `clip_url` (contract v2). */
  clip?: string | null
  /** Canonical URL: /media/clips/{lecture_id}/{filename} */
  clip_url?: string | null
}

export interface QuestionFeedbackOut {
  question_id: number
  concept: string
  correct: boolean
  selected?: string | null
  answer?: string | null
  explanation?: string | null
  rationale?: string | null
}

export interface QuizSubmitOut {
  quiz_id: number
  student_id: string
  score: number
  total: number
  remediation: WatchItemOut[]
  feedback: QuestionFeedbackOut[]
}

// ── Jobs (Engine 2 / C2) ──────────────────────────────────────────────────────

export type JobStatus = 'queued' | 'running' | 'ready' | 'error' | 'orphaned' | 'cancelled'

export interface JobOut {
  id: number
  kind: string
  status: JobStatus
  course_id?: string | null
  lecture_id?: number | null
  title?: string | null
  stage?: string | null
  detail?: string | null
  progress_pct: number
  error?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  heartbeat_at?: string | null
  duration_s?: number | null
  terminal: boolean
}

export interface JobListOut {
  jobs: JobOut[]
}

export interface JobAcceptedOut {
  job_id: number
  status: 'queued'
  detail?: string | null
}

// ── Error envelope ────────────────────────────────────────────────────────────

/** Every non-2xx response from the backend carries this shape. */
export interface ApiError {
  detail: string | Array<{ msg: string; loc: string[] }>
}
