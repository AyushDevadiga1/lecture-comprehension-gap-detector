# 18 · Diagrams and presentation material

Copy-paste sources for architecture diagrams (Mermaid) and a slide outline.
All node names and flows are taken from files 01–15; nothing here invents a
component.

## Component diagram (Mermaid)

```mermaid
flowchart TB
    subgraph UI["Streamlit dashboards"]
        S["student_app.py<br/>ingest → process → clips → graph → rows → quiz"]
        F["faculty_app.py<br/>stats → DAG → timeline"]
        SH["panels/shell.py<br/>sidebar · quota · uploads · job monitor · snapshot"]
    end
    subgraph LIB["Streamlit-free library"]
        C["client.py<br/>HTTP + Tier-1 TTL cache"]
        ST["state.py<br/>Tier-2 namespaces"]
        TH["theme.py<br/>tokens + contrast"]
        L["layout.py<br/>scroll boxes · cards · escaping"]
        R["render.py<br/>SVG timeline · DAG · pyvis page"]
        JF["jobfeed.py<br/>SSE snapshot + poll fallback"]
    end
    subgraph BE["FastAPI backend :8000"]
        API["routes: courses · lectures · quizzes · jobs · media · usage"]
        PIPE["pipeline: transcribe → extract → graph → clips"]
        DB[("SQLite registry + media files")]
    end
    S --> SH
    F --> SH
    SH --> JF
    S --> C
    F --> C
    JF --> API
    C --> API
    API --> PIPE
    PIPE --> DB
    API --> DB
```

## Upload-to-remediation sequence (Mermaid)

```mermaid
sequenceDiagram
    participant U as Student browser
    participant A as student_app.py
    participant B as FastAPI backend
    participant J as SSE job feed
    U->>A: upload lecture file
    A->>B: POST /lectures (create row)
    A->>B: PUT /lectures/{id}/media (1 MiB chunks, cancellable)
    B-->>A: job_id (transcription enqueued)
    J-->>A: stream progress (fragment cards, 1 s)
    A->>B: POST /lectures/{id}/concepts
    A->>B: POST /courses/{id}/graph
    A->>B: POST /lectures/{id}/clips
    A->>B: POST /quizzes (capped, blocking)
    U->>A: answer questions
    A->>B: POST /quizzes/submit
    B-->>A: score + feedback + ordered remediation + clips
```

## State-tier diagram (Mermaid)

```mermaid
flowchart LR
    subgraph T1["Tier-1 · client.CacheStore (process-wide, TTL)"]
        direction TB
        SN["/snapshot · 5 s"]
        G["/graph · /stats · /lectures/{id} · 300 s"]
        L2["/courses · /lectures · /clips · /usage · 30–60 s"]
    end
    subgraph T2["Tier-2 · state.py namespaces (per session)"]
        direction TB
        NAV["nav"]
        Q["quiz"]
        FA["faculty"]
        JB["jobs: items + completed"]
        TL["tl + clips_view"]
    end
    MUT["any mutation"] --> INV["invalidate_for_course()"]
    INV --> T1
    FRAG["st.fragment cards (1 s)"] --> JF2["jobfeed snapshot (SSE)"]
    DONE["job finishes"] --> REC["_record_ready → jobs.completed"]
    REC --> DR["drain_ready() in page body"]
```

## Slide outline (12 slides)

1. **Title** — LecGap: Lecture Comprehension Gap Detector; one-line promise
   (upload a lecture, get a personalised study plan).
2. **Problem** — lecture content is linear; student confusion is invisible
   until the exam. Faculty can't see taught-vs-learned divergence.
3. **Pipeline** — transcribe (Whisper) → extract concepts + spoken links →
   build DAG → cut clips → quiz → remediate. Use the sequence diagram.
4. **Two dashboards** — student (do the work) vs faculty (see the learning);
   same sidebar, banner, quota row, snapshot; shared backend and database.
5. **Live without reloads** — SSE feed + 1 s fragment cards; the
   restart-every-video defect this replaced; completion announcements in the
   page body, never the fragment.
6. **Two-tier state** — Tier-1 TTL cache with one invalidation rule; Tier-2
   namespaces; 5 s snapshot as the cross-session consistency layer.
7. **Quiz → remediation** — 15-question cap (why: 74 radios, minutes frozen);
   one-shot submit; wrong answers trace prerequisites backwards into an
   ordered clip-backed study list.
8. **Faculty analytics** — confusion heatmap (block bars), taught-vs-learned
   arrows, lecture coverage timeline (green = pinned-down speech).
9. **One colour system** — semantic tokens, measured (never eyeballed) ink,
   WCAG AA pinned per token per surface; light values on a dark page as the
   motivating bug.
10. **Contracts and guards** — `{detail}` errors not tracebacks; no
    filesystem paths in players (media endpoint + range); duplicate-upload
    guard; one-pipeline-job-per-lecture rule; resumable-vs-abandoned triage.
11. **Known gaps (honest slide)** — auth banner condition never fires;
    snapshot/stats untyped; blocking quiz generation (queued job planned);
    `accent` == `info`. Each is one line with its file reference.
12. **What next** — queued quiz generation (C2), typed snapshot/stats
    schemas, auth-kind recording; the React engine now carries these forward.
