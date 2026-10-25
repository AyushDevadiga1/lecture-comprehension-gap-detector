# 🎓 LecGap Frontend — Interactive Web Application

> **Note on Branch Status:**  
> This modern React application is currently developed on the **`engine2/scaffold`** branch. It will be consolidated and merged directly into `main` after final evaluation. If you are on `main`, switch to this branch using `git checkout engine2/scaffold`.

---

## 🌟 What is LecGap?

**LecGap (Lecture Comprehension Gap Detector)** automatically analyzes lecture recordings to discover how concepts connect to each other. 

Instead of manual curriculum mapping, LecGap:
1. **Listens to the lecture** and identifies key concepts and their timestamps.
2. **Discovers dependencies** between concepts (which topics you need to understand first).
3. **Quizzes students** on those concepts using questions directly grounded in the lecture.
4. **Builds a personalized recovery plan** with bite-sized video clips arranged in the exact order you should study them.

---

## 🚀 Quickstart — How to Run Locally

Follow these 3 simple steps to get both the backend and frontend running on your computer.

### Step 1: Start the Python Backend
The backend powers AI transcription, concept extraction, and the database.

In your terminal (activate your `lecgap` environment first):
```bash
# From the project root folder:
python -m uvicorn backend.main:app --port 8000
```
> The backend will start on **`http://localhost:8000`** (Swagger docs available at `http://localhost:8000/docs`).

### Step 2: Start the React Frontend
Open a **new terminal window**:
```bash
# Navigate to the frontend folder:
cd frontend-react

# Install dependencies (only needed the first time):
npm install

# Start the interactive UI:
npm run dev
```

### Step 3: Open in Your Browser
Visit **`http://localhost:5173`** in Chrome, Edge, or Firefox.

- Vite's development proxy automatically connects all API requests to the backend on port 8000.
- A demo course (`ml`) with pre-extracted concepts is ready to explore right away!

---

## 🧭 Interactive Feature Tour

The application provides two tailored role views accessible from the top navigation bar:

```
[ LecGap ]  [ Course: ML ▼ ] [+]  |  [ Student Portal ]  [ Faculty Insights ]  |  [ ⚙ Jobs ] [ 🌓 ]
```

### 🧑‍🎓 Student Portal (`/student`)

* **📊 Overview (`/student/overview`)**:
  - **Plain-English Pipeline Guide**: Visual 4-step walkthrough explaining how your lectures become study plans.
  - **Course Summary Cards**: At-a-glance counts of ready lectures, mapped concepts, and video clips.
  - **Quick Action Grid**: One-click jumps to the next step (upload, study map, quiz, or remediation).

* **📹 Lectures & Upload (`/student/lectures`)**:
  - Click **"+ Upload lecture"** to drag-and-drop video/audio files (`.mp4`, `.webm`, `.wav`).
  - Watch real-time upload progress and track background transcription.
  - Click any lecture to see all extracted concepts, their exact time ranges, and a **"Show on map"** button.

* **🗺️ Concept Map (`/student/map`)**:
  - Interactive **prerequisite DAG (Directed Acyclic Graph)** powered by ReactFlow.
  - **Controls**: Filter weak links by confidence slider, limit top concepts, search for topics, or change colors.
  - **Inspect Edges**: Click on any connection between concepts to read the professor's verbatim sentence explaining why concept A leads to concept B.

* **📝 Quiz & Practice (`/student/quiz`)**:
  - Select a lecture and choose how many questions to attempt.
  - Diagnostic multiple-choice questions grounded in the lecture passages.
  - Submitting grades your answers on the server and immediately unlocks your personalized study sequence.

* **🎯 Video Remediation (`/student/remediation`)**:
  - Displays only the concepts you missed, arranged in **optimal learning order** (prerequisites first).
  - Watch the exact lecture video clip where the professor taught that concept.
  - Click **"Show on map"** to visualize how the gap connects to the rest of the course.

---

### 👨‍🏫 Faculty Insights (`/faculty`)

* **📈 Analytics (`/faculty/analytics`)**:
  - Review all extracted prerequisite links, extraction confidence, and spoken evidence.
  - Re-run graph builds across the course with a single click.

* **🔥 Confusion Heatmap (`/faculty/heatmap`)**:
  - Pinpoints the toughest prerequisite pairs where students consistently miss quiz questions.

* **🔀 Taught vs. Learned Divergence (`/faculty/divergence`)**:
  - Flags topics where the order the professor spoke differs from the optimal pedagogical order suggested by the data.

* **⏱️ Lecture Timeline & Coverage (`/faculty/coverage`)**:
  - Visual breakdown showing what percentage of spoken lecture time is pinned down to concepts.

---

### ⚡ Ambient System Features

- **Live Job Drawer**: Click the background jobs button in the top bar to slide open the real-time SSE task drawer. It displays live progress bars for Whisper transcription, concept extraction, and clip cutting without freezing the page.
- **Course Switcher & Creator**: Switch between active courses from the header dropdown, or click `+` to add a new course ID.
- **Dark & Light Mode**: Seamless theme switching with accessible contrast tokens and smooth transitions.

---

## 📊 Progress Summary (In Short)

| Area | Status | Summary |
|---|---|---|
| **Architecture & Routing** | ✅ Complete | 13 code-split routed views with zero monolithic re-renders. |
| **Real-time SSE Jobs** | ✅ Complete | Background worker events stream directly to the UI drawer via Server-Sent Events. |
| **Concept Graph (DAG)** | ✅ Complete | Interactive ReactFlow graph with search, zoom, confidence filters, and spoken evidence. |
| **Quiz & Video Remediation** | ✅ Complete | Asynchronous quiz synthesis, server grading, topological study ordering, and inline video cuts. |
| **Course Management** | ✅ Complete | Course switcher, course deletion with safety checks, and "+ New course" dialog. |
| **Code Quality & Tests** | ✅ Complete | **819 tests passing across 43 test suites**, 0 TypeScript errors, 0 ESLint warnings. |
| **Git & Merging** | 🔜 Next Up | Currently on `engine2/scaffold` branch; ready for merge into `main`. |

---

## 🛠️ Development & Testing Commands

All frontend scripts are run from the `frontend-react` folder:

```bash
# Run local dev server with hot reload
npm run dev

# Run comprehensive verification (TypeScript check + ESLint + Vitest)
npm run verify

# Run unit tests only
npm test

# Run tests in watch mode
npm run test:watch

# Check types without running tests
npm run type-check

# Run linter
npm run lint

# Build optimized production bundle
npm run build
```

---

*LecGap Engine 2 • Built with React, Vite, TypeScript, and Material-UI.*
