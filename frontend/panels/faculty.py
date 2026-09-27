"""Faculty panel — confusion heatmap, taught-vs-learned divergence, timeline.

These read-only analytics have no in-flight state, so they are kept apart from
the student-facing panels: the student path can be reasoned about (and tested)
without dragging the faculty views along.
"""

import streamlit as st

from frontend import client, layout, state
from frontend.panels import library
from frontend.render import lecture_html


def render_faculty_stats(nav_course):
    st.subheader("Confusion heatmap + taught-vs-learned divergence")

    if st.button("Load course stats"):
        data = client.course_stats(nav_course)
        if data:
            state.set("faculty", stats=data, stats_course=nav_course)
        else:
            err = client.take_last_error()
            st.error((err or {}).get("detail")
                     or "Stats load failed — is the backend up?")

    stats = state.get("faculty", "stats")
    if not (stats and state.get("faculty", "stats_course") == nav_course):
        return

    heatmap = stats.get("heatmap") or []
    if not heatmap:
        st.caption("No graded answers yet — students must submit a quiz first.")
    else:
        st.markdown("**Wrong-answer rates (highest first)**")
        rows = []
        for h in heatmap:
            rate = h.get("rate", 0) or 0
            bar = "&#9608;" * int(round(rate * 10))
            rows.append(
                f'<div style="padding:2px 0">'
                f'<span style="display:inline-block;min-width:240px">'
                f'{layout.escape(h.get("concept", ""))}</span>'
                f'<span style="color:#b91c1c;font-family:monospace">{bar}</span> '
                f'<span style="color:#64748b">{rate:.0%} '
                f'({h.get("wrong", 0)}/{h.get("attempts", 0)})</span></div>'
            )
        st.markdown(layout.scroll_box("".join(rows), max_height=320),
                    unsafe_allow_html=True)

    divergence = stats.get("divergence") or []
    if divergence:
        st.markdown("**Taught order → learned order divergence**")
        rows = []
        for d in divergence:
            gap = d.get("gap", 0) or 0
            arrow = "→ later" if gap > 0 else ("← earlier" if gap < 0 else "=")
            ti = d.get("taught_idx")
            li = d.get("learned_idx")
            rows.append(
                f'<div style="padding:2px 0">'
                f'<span style="display:inline-block;min-width:240px">'
                f'{layout.escape(d.get("concept", ""))}</span>'
                f'taught #{ti if ti is not None else "—"} vs '
                f'learned #{li if li is not None else "—"} '
                f'({layout.escape(arrow)})</div>'
            )
        st.markdown(layout.scroll_box("".join(rows), max_height=320),
                    unsafe_allow_html=True)


def render_faculty_timeline(nav_course):
    st.subheader("Lecture timeline & coverage")
    st.caption("How much of the spoken lecture the extracted concepts actually pin "
               "down (green = covered window), with each concept's quiz-answer "
               "evidence sentence. Pick any ready lecture in the course.")
    ready = library.ready_lectures(nav_course)
    if not ready:
        st.info(f"No ready lecture in course '{nav_course}' yet.")
        return

    pick = st.selectbox("Lecture", ready, format_func=library.lecture_label,
                        key="tl_lecture")
    state.set("tl", lecture_id=pick["id"])
    detail = client.lecture_detail(pick["id"])
    if not detail:
        err = client.take_last_error()
        st.warning((err or {}).get("detail")
                   or f"Could not load lecture #{pick['id']}")
        return
    concepts = detail.get("concepts") or []
    st.markdown(
        lecture_html(detail.get("segments") or [], concepts,
                     lecture_title=f"{nav_course} — {detail.get('title', '')}"),
        unsafe_allow_html=True,
    )
