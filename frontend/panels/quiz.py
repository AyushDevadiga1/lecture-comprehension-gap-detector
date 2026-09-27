"""Quiz panel — generate, answer, submit, review.

Two problems this fixes:

* **A quiz was not a quiz.** ``POST /quizzes`` writes one question per course
  concept, so the ``ml`` course produced 74 questions - 74 radio buttons in one
  form, each backed by an LLM call. The quiz is now capped (default 15) via
  ``LECGAP_QUIZ_MAX_QUESTIONS``, which also cuts generation time by ~5x.
* **Feedback was a wall.** Score, per-question feedback and the remediation
  study list are now in bounded, scrollable boxes instead of one long page.

Generation is still a blocking POST; making it a queued job is checkpoint C2
(backend job registry). Until then it gets a spinner and an explicit wait
message, and the 409 "already generating" answer is explained rather than shown
as a raw failure.
"""

import os
import time

import streamlit as st

from frontend import client, layout, state

DEFAULT_STUDENT = "demo-student"
# A quiz is a quiz: `POST /quizzes` writes one question per course concept, and
# the `ml` course has 153 of them. One LLM call each, six-wide, inline in the
# POST - so the un-capped flow froze the UI for minutes and then rendered 74
# radio buttons. Overridable per deployment.
_DEFAULT_MAX_QUESTIONS = 15


def quiz_max_questions() -> int:
    raw = os.getenv("LECGAP_QUIZ_MAX_QUESTIONS", "").strip()
    if not raw:
        return _DEFAULT_MAX_QUESTIONS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_QUESTIONS


def _question_count():
    return quiz_max_questions()


def cap_violation(returned: int, requested: int):
    """Warning when the backend ignored ``max_questions``, else None.

    A backend predating the cap ignores the field and regenerates one question
    per concept. The panel says so instead of quietly rendering a 74-question
    form the reader has to scroll through.
    """
    if requested and returned > requested:
        return (f"The backend returned {returned} questions instead of the "
                f"{requested} requested, so it is an older build — restart it "
                "to pick up the quiz cap.")
    return None


def render_quiz(nav_course):
    """Student quiz flow with session-state persistence.

    The generated questions live in ``state['quiz']`` (not a function local), so
    the background-job monitor re-running the script cannot wipe a student's
    in-flight quiz. A submit 404 (server regenerated the course's questions)
    degrades to a clear 'generate again' instead of a traceback.
    """
    st.subheader("Take the quiz")

    if "quiz_student_id" not in st.session_state:
        st.session_state.quiz_student_id = state.get("quiz", "student_id",
                                                     DEFAULT_STUDENT)
    student_id = st.text_input("Student ID", key="quiz_student_id")

    cap = _question_count()
    st.caption(f"Up to {cap} questions, drawn from the course's concepts.")

    if st.button("Generate quiz"):
        state.set("quiz", course_id=nav_course, student_id=student_id,
                  questions=None, version=int(state.get("quiz", "version", 0)) + 1,
                  render_t=time.time(), result=None, error=None, cap=cap)
        quiz = _generate(nav_course, student_id, cap)
        if quiz and quiz.get("questions"):
            got = len(quiz["questions"])
            state.set("quiz", questions=quiz["questions"],
                      render_t=time.time(), result=None)
            stale = cap_violation(got, cap)
            if stale:
                state.set("quiz", error=stale)
        else:
            state.set("quiz", error=_generation_error(quiz, nav_course, cap))

    err = state.get("quiz", "error")
    if err:
        st.warning(err)

    questions = state.get("quiz", "questions")
    stale_course = state.get("quiz", "course_id") != nav_course
    if not questions or stale_course:
        if stale_course:
            state.clear("quiz")
        return

    n = len(questions)
    st.caption(f"{n} question{'s' if n != 1 else ''} ready.")
    with st.form("answers_form"):
        answers = []
        for q in questions:
            options = q.get("options") or ["correct", "incorrect", "wrong"]
            ans = st.radio(q["question"], options=options,
                           key=f"legap_q{q['id']}")
            answers.append({"question_id": q["id"], "selected": ans,
                            "latency_s": None})
        done = st.form_submit_button("Submit answers")

    if done:
        render_t = state.get("quiz", "render_t")
        if render_t:
            per_q = round((time.time() - render_t) / max(len(answers), 1), 2)
            for a in answers:
                a["latency_s"] = per_q
        result = client.post(
            "/quizzes/submit",
            json={"course_id": nav_course, "student_id": student_id,
                  "answers": answers},
        )
        err = client.take_last_error()
        if result:
            state.set("quiz", result=result)
            state.set("quiz", questions=None)  # one shot: don't re-submit stale ids
        elif err and err.get("status") == 404:
            st.error("The quiz on the server was regenerated while you were "
                     "answering — please generate the quiz again.")
            state.set("quiz", questions=None, result=None)
        else:
            st.error((err or {}).get("detail") or "Submit failed — try again.")

    result = state.get("quiz", "result")
    if result:
        render_result(result)


def _generate(nav_course, student_id, cap):
    """POST the quiz request, telling the reader why it is taking a while."""
    with st.spinner(f"Writing up to {cap} questions from this course's concepts…"):
        return client.post("/quizzes", json={"course_id": nav_course,
                                             "student_id": student_id,
                                             "max_questions": cap})


def _generation_error(quiz, nav_course, cap):
    err = client.take_last_error() or {}
    status = err.get("status")
    if status == 409:
        return ("A quiz is already being generated for this course — wait for it "
                "to finish, then press Generate again.")
    if status == 404:
        return "This course has no concepts yet, so there is nothing to quiz. " \
               "Extract concepts from a ready lecture first."
    return err.get("detail") or "Quiz generation failed."


def render_result(result):
    """Score, per-question feedback and remediation — each in a bounded box."""
    score = result.get("score", 0)
    total = result.get("total", 0)
    pct = (score / total * 100) if total else 0
    st.markdown(
        layout.panel(
            f'<div style="font-size:22px;font-weight:700">Score {score}/{total}</div>'
            f'<div style="color:#64748b">{pct:.0f}% correct</div>'
        ),
        unsafe_allow_html=True,
    )

    feedback = result.get("feedback") or []
    rows = []
    for f in feedback:
        tag = "correct" if f.get("correct") else "wrong"
        colour = "#15803d" if f.get("correct") else "#b91c1c"
        rows.append(
            f'<div style="padding:6px 0;border-bottom:1px solid #f1f5f9">'
            f'<span style="font-weight:600">{layout.escape(f.get("concept", ""))}</span> '
            f'<span style="color:{colour};font-weight:700">{tag}</span>'
            + (f'<div style="font-size:13px;color:#334155">✓ {layout.escape(f["explanation"])}</div>'
               if f.get("explanation") else "")
            + (f'<div style="font-size:13px">correct answer: {layout.escape(f["answer"])}</div>'
               if not f.get("correct") and f.get("answer") else "")
            + (f'<div style="font-size:13px">why your pick was wrong: {layout.escape(f["rationale"])}</div>'
               if not f.get("correct") and f.get("rationale") else "")
            + "</div>"
        )
    st.markdown("**Per-question feedback**")
    st.markdown(layout.scroll_box("".join(rows), max_height=340),
                unsafe_allow_html=True)

    remediation = result.get("remediation") or []
    st.markdown("**Remediation — study in this order**")
    if not remediation:
        st.success("Nothing to remediate — all upstream concepts mastered.")
        return
    blocks = []
    for item in remediation:
        why = "failed" if item.get("failed") else "prerequisite"
        blocks.append(
            f'<div style="font-weight:600;margin-top:8px">'
            f'{layout.escape(item.get("concept", ""))} '
            f'<span style="color:#b45309;font-weight:400">({layout.escape(why)})</span>'
            f'</div>'
        )
        url = client.media_url(item.get("clip"))
        if url:
            blocks.append(layout.video_box(url, height=210))
    st.markdown(layout.scroll_box("".join(blocks), max_height=460),
                unsafe_allow_html=True)
