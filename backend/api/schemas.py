"""API schemas (Pydantic response/request models) — moved out of routes.py so
the route module stays thin. Pure declarations; no imports from routes/workers.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_s: float
    end_s: float
    text: str


class LectureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: str
    title: str
    status: str
    error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None


class LectureProgressOut(BaseModel):
    """Live job progress — the payload behind GET /lectures/{id}/progress."""

    lecture_id: int
    status: str
    stage: str
    progress_pct: int
    detail: str
    elapsed_s: float
    updated_at: str


class LectureDeleteOut(BaseModel):
    deleted: bool
    lecture_id: int
    message: str


class CourseSummaryOut(BaseModel):
    course_id: str
    total_lectures: int
    ready_lectures: int
    total_concepts: int
    has_graph: bool
    node_count: int
    edge_count: int


class CourseDeleteOut(BaseModel):
    deleted: bool
    course_id: str
    lectures_removed: int
    message: str


class ConceptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    implicit: bool
    start_s: Optional[float] = None
    end_s: Optional[float] = None


class LectureDetailOut(LectureOut):
    segments: List[SegmentOut] = []
    concepts: List[ConceptOut] = []


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    confidence: float
    source_method: str = "classifier"
    evidence: Optional[str] = None


class CourseGraphOut(BaseModel):
    course_id: str
    nodes: List[str]
    edges: List[GraphEdgeOut] = []
    node_count: int
    edge_count: int
    is_dag: bool
    topological_order: List[str]


class CourseBuildOut(BaseModel):
    status: str
    course_id: str


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    concept_name: str
    start_s: float
    end_s: float
    path: str
    ok: bool
    error: Optional[str] = None


class ClipBatchOut(BaseModel):
    lecture_id: int
    status: str
    clips: List[ClipOut] = []


class QuizQuestionOut(BaseModel):
    """A question as presented to the client. It must never reveal the answer:
    only the shuffled ``options`` are returned (the answer is exactly one of
    them). Distractor/answer columns stay server-side."""

    id: int
    concept: str
    question: str
    options: List[str] = []


class QuizOut(BaseModel):
    quiz_id: int
    course_id: str
    student_id: str
    questions: List[QuizQuestionOut] = []


class QuizAnswerIn(BaseModel):
    """One student answer. Grading is always server-side: the client submits
    only what it *selected* — the `correct` flag is deliberately not accepted
    for input (a client-reported key would defeat the quiz)."""
    question_id: int
    selected: Optional[str] = None
    latency_s: Optional[float] = None


class QuizSubmitIn(BaseModel):
    course_id: str
    student_id: str
    answers: List[QuizAnswerIn]


class WatchItemOut(BaseModel):
    concept: str
    failed: bool
    clip: Optional[str] = None


class QuestionFeedbackOut(BaseModel):
    """Per-question post-submit feedback — never disclosed by GET /quizzes."""

    question_id: int
    concept: str
    correct: bool
    selected: Optional[str] = None
    answer: Optional[str] = None
    explanation: Optional[str] = None
    rationale: Optional[str] = None


class QuizSubmitOut(BaseModel):
    quiz_id: int
    student_id: str
    score: int
    total: int
    remediation: List[WatchItemOut] = []
    feedback: List[QuestionFeedbackOut] = []