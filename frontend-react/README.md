# LecGap Frontend (Engine 2 — React Architecture)

Modern, reactive single-page application for the **Lecture Comprehension Gap Detector**, replacing the initial Streamlit interface per `plan/ENGINE2_REBUILD_PLAN.md` and `plan/FRONTEND_REACT_ROADMAP.md`.

## Features

- **Decoupled Asynchronous State**: Background jobs (Whisper transcription, concept extraction, prerequisite DAG construction, clip segmentation, and quiz synthesis) are tracked via real-time **Server-Sent Events (SSE)** through `/jobs/stream`. The UI never reloads or polls by whole-page re-renders.
- **Student Portal (`/student`)**:
  - Lecture upload with byte-level streaming progress (XHR `upload.onprogress`).
  - Adaptive comprehension diagnostic quiz driven by LLM question generation.
  - Topological prerequisite remediation sequence with inline byte-range-capable video clip playback (`/media/clips/{lecture_id}/{filename}`).
- **Faculty Insights (`/faculty`)**:
  - Prerequisite DAG exploration with verbatim spoken transcript evidence and extraction confidence.
  - Taught vs. Learned order divergence table highlighting student comprehension blind spots.
  - Concept comprehension gap heatmap indicating high-failure learning objectives.
- **Background Tasks Drawer**: Slide-over drawer displaying live stages, progress bars, and cancellation controls for all course jobs.

## Tech Stack

- **Build / Framework**: Vite 6, React 18, TypeScript (Strict)
- **Routing**: `react-router-dom` v6
- **Server State & Caching**: `@tanstack/react-query` v5
- **Client & UI State**: `zustand` v5
- **UI & Styling**: Material-UI (MUI v6) with custom dark mode glassmorphism theme + CSS variables
- **Testing**: Vitest + Testing Library + JSDOM

## Getting Started

### 1. Start the FastAPI Backend
Ensure your backend is running on `http://localhost:8000`:
```bash
uvicorn backend.main:app --reload
```

### 2. Run the React Development Server
```bash
cd frontend-react
npm install
npm run dev
```

Open `http://localhost:5173` in your browser. All API requests (`/courses`, `/lectures`, `/jobs`, `/quizzes`, `/students`, `/media`) are automatically forwarded to `http://localhost:8000` via Vite's development proxy.

### 3. Run Tests
```bash
npm run test
```
