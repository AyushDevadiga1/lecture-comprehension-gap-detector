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
    id: int
    concept: str
    question: str
    options: List[str] = []
    distractor_a: Optional[str] = None
    distractor_b: Optional[str] = None
    distractor_c: Optional[str] = None


class QuizOut(BaseModel):
    quiz_id: int
    course_id: str
    student_id: str
    questions: List[QuizQuestionOut] = []


class QuizAnswerIn(BaseModel):
    question_id: int
    selected: Optional[str] = None
    correct: Optional[bool] = None
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