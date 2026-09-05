# LecGap — System Data-Flow Chart

**TL;DR — one credential, one loop.** A lecture video is uploaded, transcribed
into timestamped segments (locally or via Groq), an LLM pulls concepts out and
MiniLM merges near-duplicates, the prerequisite classifier + LLM check turn
them into a dependency graph (DAG), clips are cut per concept, a student's
wrong quiz answers are lifted through that DAG into an ordered watch-list —
and faculty see the class's confusion heatmap plus the taught-vs-learned
divergence. The only API key in the whole system is `GROQ_API_KEY`.

```mermaid
flowchart LR
    %% -------------------- Secrets & external services --------------------
    subgraph EXT["External services & keys"]
        GK(("GROQ_API_KEY<br/>the only credential<br/>loaded from .env at startup"))
        GROQCHAT["Groq · chat completions<br/>openai/gpt-oss-20b<br/>30 req · 8K tok / min"]
        GROQAUD["Groq · audio transcription<br/>whisper-large-v3-turbo<br/>≈216× real-time · $0.04/audio-hr"]
        OLLAMA["Ollama · no key · fallback<br/>llama3.2 · localhost:11434"]
        FFMPEG["ffmpeg + ffprobe<br/>downmix · chunk · cut clips"]
    end

    %% -------------------- Entry point --------------------
    FE["Streamlit app · frontend/app.py<br/>Student tab: ingest → quiz → remediation<br/>Faculty tab: heatmap + divergence"]

    %% -------------------- API surface --------------------
    API["backend/main.py · FastAPI app<br/>loads .env · creates tables · /health"]
    R["backend/api/routes.py · HTTP endpoints<br/>upload · concepts · clips · graph · quiz · stats"]

    %% -------------------- Storage --------------------
    DB[("SQLite · data/lecgap.db<br/>lectures · transcript_segments · llm_cache<br/>concepts · graph · clips · quiz · responses")]
    RAW["data/raw/ · uploaded lecture media"]
    CLIPS["data/processed/clips/ per lecture<br/>one exportable video per concept"]

    %% -------------------- ML data & models --------------------
    WHISPERL["openai-whisper · local engine<br/>WHISPER_MODEL · base · offline · no quota"]
    MINILM["MiniLM sentence encoder<br/>concept dedup · classifier encoder"]
    LB["LectureBank CSVs · data/lecturebank/<br/>prerequisite training & benchmark"]
    FT["Fine-tuned checkpoint<br/>data/models/lecgap_ft · benchmarked"]

    %% -------------------- Pipeline · Stages 1-7 --------------------
    LLM["llm.py · LLM access layer<br/>SQLite cache → Groq chat → Ollama<br/>429 backoff · quota metering"]
    TR["transcribe.py · Stage 1<br/>WHISPER_BACKEND: local / groq<br/>outputs timestamped segments"]
    EX["extract_concepts.py · Stage 2<br/>transcript chunks → LLM concepts<br/>→ MiniLM dedup"]
    CLS["classify_prerequisites.py · Stage 3<br/>candidate pairs → score → LLM check"]
    BG["build_graph.py · Stage 4<br/>prerequisite DAG · cycle fix · learning order"]
    SC["segment_clips.py · Stage 5<br/>one video clip per concept"]
    QZ["quiz.py · Stage 6<br/>ordered quiz · remediation watch-list"]
    RF["refine.py · Stage 7<br/>LLM personas · recovery-metric validation"]

    %% -------------------- Flow --------------------
    GK --> GROQCHAT
    GK --> GROQAUD
    API -->|".env + DB init at startup"| GK
    FE -->|"health probe"| API
    FE -->|"media + course_id"| R
    R -->|"store upload"| RAW
    R -->|"background task: transcribe()"| TR
    RAW -->|"source_path"| TR
    TR -->|"local engine"| WHISPERL
    TR -->|"groq: mono 16 kHz FLAC"| GROQAUD
    TR -->|"subprocess"| FFMPEG
    TR -->|"segments stored"| DB
    R -->|"segments → concept extraction"| EX
    EX -->|"one chunk at a time"| LLM
    EX -->|"cosine dedup ≥ 0.85"| MINILM
    EX -->|"concepts stored"| DB
    R -->|"course concepts"| CLS
    CLS -->|"pair scoring"| MINILM
    CLS -->|"LLM reasoning check"| LLM
    CLS -->|"evaluation"| LB
    CLS -->|"encoder backend"| FT
    CLS -->|"confirmed edges"| BG
    BG -->|"nodes + edges stored"| DB
    R -->|"concepts + timestamps"| SC
    SC -->|"ffmpeg"| FFMPEG
    SC -->|"clip videos"| CLIPS
    SC -->|"clip rows stored"| DB
    CLIPS -->|"playback paths"| QZ
    R -->|"quiz concepts · graph order"| QZ
    QZ -->|"reads learned order"| BG
    DB -->|"questions + responses"| QZ
    QZ -->|"watch-list → student"| FE
    DB -->|"responses + concepts"| R
    R -->|"heatmap + divergence → faculty"| FE
    RF -->|"personas"| LLM
    RF -->|"validates graph recovery"| BG
    LLM -->|"cache get/put · zero-cost reruns"| DB
    LLM -->|"fallback when Groq unavailable"| OLLAMA

    %% -------------------- Styling --------------------
    classDef key fill:#fde064,stroke:#b58900,stroke-width:2px,color:#111;
    classDef ext fill:#dbeafe,stroke:#3b82f6,color:#111;
    classDef mod fill:#dcfce7,stroke:#16a34a,color:#111;
    classDef store fill:#f3e8ff,stroke:#9333ea,color:#111;
    classDef ml fill:#ffe4e6,stroke:#e11d48,color:#111;
    classDef ui fill:#fff7ed,stroke:#ea580c,color:#111;
    classDef api fill:#f1f5f9,stroke:#64748b,color:#111;

    class GK key;
    class GROQCHAT,GROQAUD,OLLAMA,FFMPEG ext;
    class LLM,TR,EX,CLS,BG,SC,QZ,RF mod;
    class DB,RAW,CLIPS store;
    class MINILM,LB,FT ml;
    class FE ui;
    class API,R api;
```

## How it flows, step by step

1. **Upload** — the Streamlit app (or `POST /lectures`) stores the file in
   `data/raw/` and kicks off a background transcription task.
2. **Transcribe (Stage 1)** — `transcribe.py` produces the same
   `[start, end, text]` segments from either the local Whisper engine or
   Groq-hosted Whisper (≈216× real-time; mono 16 kHz FLAC, auto-chunked).
3. **Extract concepts (Stage 2)** — the transcript is chunked and an LLM names
   explicit + implicit concepts; MiniLM merges near-duplicates.
4. **Build the prerequisite graph (Stages 3-4)** — candidate concept pairs are
   scored by the MiniLM classifier (LectureBank-trained), cross-checked by an
   LLM, and assembled into a cycle-free DAG with a learning order.
5. **Cut clips (Stage 5)** — ffmpeg exports one video per concept for playback.
6. **Quiz + remediation (Stage 6)** — a student's wrong answers are lifted
   through the DAG into a dependency-ordered watch-list of clips.
7. **Learn + refine (Stages 7-8)** — LLM personas validate the refinement
   mechanic, and the faculty tab reads the same tables for the confusion
   heatmap and taught-vs-learned divergence.

## Reading the chart

| Colour | Meaning |
|---|---|
| Yellow | API keys / secrets — the **only** credential is `GROQ_API_KEY`; Ollama needs none |
| Blue | External services (Groq chat, Groq Whisper, Ollama, ffmpeg) |
| Green | Pipeline logic (Stages 1-7) |
| Purple | Storage (SQLite + media files) |
| Pink | ML artifacts (MiniLM, LectureBank, fine-tuned checkpoint) |
| Orange | Frontend (Streamlit) |
| Grey | FastAPI surface |

## Every API key in the system

| Key | Where | Used by |
|---|---|---|
| `GROQ_API_KEY` | `.env` (also in the OS environment for convenience) | `llm.py` chat (`openai/gpt-oss-20b`) and `transcribe.py` Whisper (`whisper-large-v3-turbo`) |

No other credentials exist — Ollama is a local keyless fallback and
ffmpeg/MiniLM run on-device.

---

> **Maintenance note:** this exact diagram is also embedded in the project
> README (section "System data flow"). Keep the two copies in sync when the
> architecture changes.