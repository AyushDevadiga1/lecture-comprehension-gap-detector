# 11 · Quiz panel — `frontend/panels/quiz.py`

**File:** `frontend/panels/quiz.py` (222 lines). Generate, answer, submit,
review. Fixes two named problems: a quiz was not a quiz (one question per
concept → 74 radio buttons, one LLM call each, minutes of frozen UI), and
feedback was an unbounded wall (now three bounded scroll boxes).

## The cap

`quiz_max_questions()` reads `LECGAP_QUIZ_MAX_QUESTIONS` (default 15, minimum
1, garbage → default). `cap_violation(returned, requested)` warns when the
backend ignored `max_questions` and regenerated per-concept — the signature of
an older backend build — instead of silently rendering a 74-question form.

## Generate flow (`render_quiz`)

Student ID persists via `quiz_student_id` (default `"demo-student"`). "Generate
quiz" bumps a Tier-2 version, clears questions/result/error, and POSTs
`/quizzes` under a spinner that says why it takes a while (generation is still
a **blocking** POST; making it a queued job is the recorded next step, and the
409 "already generating" answer is explained rather than shown raw).
Backend-missing-concepts (404) maps to "extract concepts first".

Generated questions live in `state["quiz"]`, **not** a function local, so the
job monitor re-running the script cannot wipe an in-flight quiz. Switching
course clears the quiz namespace. Each option list falls back to
`["correct", "incorrect", "wrong"]` when the backend sends none.

## Submit

Answers carry `question_id`, the selected option, and `latency_s` — stamped as
the *average* per-question time since render (total elapsed ÷ answer count),
mirroring the panels' approach to response-time evidence. Submit posts
`/quizzes/submit` and then clears `questions` immediately: **one-shot**, so
stale ids can never be resubmitted. A submit-404 (server regenerated the
questions mid-quiz) degrades to "generate again" instead of a traceback; other
failures show `{detail}`.

## Result (`render_result`)

Score header (`Score s/t`, `% correct`), then per-question feedback rows
(correct/wrong tag in `ok`/`bad`, explanation, correct answer and
why-your-pick-was-wrong when wrong), then the remediation list in study order —
each concept tagged `failed` vs `prerequisite`, each with its clip player when
a clip URL maps. Empty remediation renders success ("all upstream concepts
mastered"), not an empty box.
