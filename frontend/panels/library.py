"""Library panel — concept clips and lecture-row management.

Clips render as real players inside a bounded frame (a server-side filesystem
path is an implementation detail and is useless to a reader), and the list
scrolls inside its own box rather than stretching the page.
"""

import streamlit as st

from frontend import client, layout, state
from frontend.panels import shell


def lecture_label(l):
    return f"#{l['id']} — {l.get('title', l.get('course_id'))}"


def ready_lectures(nav_course):
    lectures = client.list_lectures() or []
    return [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]


def clip_rows(lecture_id):
    """All clip rows for a lecture, or [] when the endpoint is unreachable."""
    batch = client.get(f"/lectures/{lecture_id}/clips") or {}
    return batch.get("clips") or []


def render_clips(lecture_id, heading=None, player_height=230, max_height=520):
    """Playable concept clips for one lecture, contained in a scroll box."""
    clips = clip_rows(lecture_id)
    if heading:
        st.markdown(heading)
    if not clips:
        st.caption("No clips cut for this lecture yet.")
        return

    playable = [c for c in clips if c.get("ok")]
    unplayable = [c for c in clips if not c.get("ok")]
    st.caption(f"{len(playable)} of {len(clips)} concept clips are playable.")

    blocks = []
    for c in playable:
        name = c.get("concept_name") or "(unnamed concept)"
        start, end = c.get("start_s"), c.get("end_s")
        span = ""
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            span = f" · {start:.0f}–{end:.0f}s"
        url = client.media_url(c.get("path"))
        if not url:
            blocks.append(
                f'<div style="font-weight:600">{layout.escape(name + span)}</div>'
                f'<div style="color:#b45309;font-size:12px">clip file missing on '
                f'the server — re-cut this lecture\'s clips</div>'
            )
            continue
        blocks.append(
            f'<div style="font-weight:600;margin-top:8px">'
            f'{layout.escape(name + span)}</div>'
            + layout.video_box(url, height=player_height)
        )

    if unplayable:
        blocks.append(
            f'<div style="color:#64748b;font-size:12px;margin-top:8px">'
            f'{len(unplayable)} clip row(s) have no media file on the server, so '
            f'they cannot be played. Re-run &quot;Cut concept clips&quot; to '
            f'rebuild them.</div>'
        )

    st.markdown(layout.scroll_box("".join(blocks), max_height=max_height),
                unsafe_allow_html=True)


def clip_watch_picker(nav_course):
    """Select a ready lecture and show its clips inside a bounded panel."""
    ready = ready_lectures(nav_course)
    if not ready:
        st.caption("No ready lecture in this course yet.")
        return
    pick = st.selectbox("Lecture whose clips to watch", ready,
                        format_func=lecture_label, key="watch_clips")
    if st.button("Show clips", key="show_clips"):
        state.set("clips_view", lecture_id=pick["id"])
    if state.get("clips_view", "lecture_id") == pick["id"]:
        render_clips(pick["id"])


def clips_followup(job, lecture_id):
    """Follow-up hook for the job monitor after a clip job lands on ready."""
    if job.get("after") == "clips_list":
        render_clips(lecture_id, heading="**Clips cut for this lecture**")


# ------------------------------------------------------------- lecture rows

def stalled_rows(nav_course):
    """Split unfinished rows by what is actually wrong with them.

    Two very different situations both surface as status ``uploaded``:

    * **resumable** - the media is registered and on disk (``has_media``), only
      transcription never started. Fixable with POST /lectures/{id}/rerun.
    * **abandoned** - no file ever arrived; the client created the row and the
      stream died. Nothing to resume, so the row is clutter to delete.
    """
    lectures = client.list_lectures() or []
    resumable, abandoned = [], []
    for lec in lectures:
        if lec.get("course_id") != nav_course:
            continue
        if lec.get("status") in ("uploaded", "error"):
            (resumable if lec.get("has_media") else abandoned).append(lec)
    return resumable, abandoned


def render_stalled_rows(nav_course):
    """Actionable panel for rows the pipeline never finished."""
    resumable, abandoned = stalled_rows(nav_course)
    if not resumable and not abandoned:
        return

    if resumable:
        st.subheader("Ready to process, but never started")
        st.caption("These rows already have their video on the server. "
                   "Transcription just never ran — start it below, no re-upload "
                   "needed.")
        for lec in resumable:
            lid = lec["id"]
            busy = shell.active_job(lid)
            col1, col2 = st.columns([3, 1])
            col1.markdown(f"**#{lid} — {lec.get('title')}**")
            if col2.button("Start processing", key=f"resume_{lid}", disabled=busy):
                resp = client.post(f"/lectures/{lid}/rerun")
                err = client.take_last_error()
                if resp:
                    shell.start_job(nav_course, lid,
                                    f"#{lid} — {lec.get('title')}",
                                    kind="transcribe")
                    client.invalidate_for_course(nav_course)
                    st.success(f"Transcription queued for #{lid}.")
                else:
                    st.error((err or {}).get("detail")
                             or f"Could not start #{lid}.")
            if lec.get("error"):
                st.caption(f"Last error: {lec['error']}")

    if abandoned:
        st.subheader("Incomplete uploads (no file arrived)")
        st.caption("A row was created but the video never finished uploading, so "
                   "there is nothing on the server to process. Delete these to "
                   "clean up.")
        for lec in abandoned:
            st.write(f"#{lec['id']} — {lec.get('title')} · no media on the server")
        ids = [lec["id"] for lec in abandoned]
        if st.button("Delete these empty rows", key="drop_abandoned"):
            for lid in ids:
                if client.delete(f"/lectures/{lid}"):
                    st.success(f"Deleted #{lid}.")
                else:
                    st.error((client.take_last_error() or {}).get("detail")
                             or f"Delete #{lid} failed.")
            client.invalidate_all()
            shell.rerun()


def render_lecture_rows(nav_course):
    """Delete lecture rows. Checked rows go via DELETE /lectures/{id}."""
    st.subheader("Lecture rows")
    lectures = client.list_lectures() or []
    rows = [l for l in lectures if l.get("course_id") == nav_course]
    if not rows:
        st.caption("No lecture rows for this course.")
        return

    wanted = [
        lec["id"] for lec in rows
        if st.checkbox(
            f"Delete #{lec['id']} — {lec.get('title')} ({lec.get('status')})",
            key=f"delrow_{lec['id']}",
        )
    ]

    if st.button("Delete checked rows", disabled=not wanted):
        deleted_any = False
        for lid in wanted:
            res = client.delete(f"/lectures/{lid}")
            if res:
                deleted_any = True
            else:
                err = client.take_last_error()
                st.error((err or {}).get("detail") or f"Delete lecture #{lid} failed.")
        if deleted_any:
            client.invalidate_all()
            shell.rerun()
