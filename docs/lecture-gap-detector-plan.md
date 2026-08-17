---

# Complete Project Plan
## Lecture Comprehension Gap Detector

---

# PART 1 — Project Identity

**Full Name:** Lecture Comprehension Gap Detector
**Short Name:** LecGap
**Tagline:** *"Stop rewatching. Start understanding."*
**Domain:** EdTech — AI/NLP
**Duration:** 12 months (Sem 7 + Sem 8)
**Team:** 3 people
**Stack:** Python, Whisper, KeyBERT, FFmpeg, Streamlit, SQLite
**Cost:** Rs. 0

---

# PART 2 — What You're Building (Scope Definition)

## The Non-Negotiable Core (Must ship by Sem 7 end)

These three features are your project. Everything else is bonus.

**Core 1 — The Transcription Pipeline**
Any YouTube URL or MP4 → audio extracted → Whisper transcribes with word-level timestamps → concepts identified → timestamps mapped → lecture clips pre-cut and stored.

**Core 2 — The Gap Detection Loop**
Student takes assessment → wrong answers identified → concept dependencies checked → personalised clip playlist generated → clips play inside the app in the correct learning order.

**Core 3 — The Faculty Heatmap**
Aggregated quiz data from all students → confusion rate per concept per timestamp → colour-coded timeline of lecture displayed to professor showing exactly where students got confused.

## The Enhancement Layer (Target for Sem 8)

These make the project research-grade. Build if Core is solid.

- Smart flashcards with clip-linked "watch explanation" button
- Concept summary cards (one-line AI summary per concept)
- Multi-session student profile and progress tracking
- DKT knowledge tracing model for predictive recommendations
- Spaced repetition scheduling based on personal forgetting history
- LLM-generated questions replacing template MCQs

## Future Scope (Write in report, don't build)

- Multilingual support for Hindi and Marathi
- Mobile app
- Institution-wide deployment API
- Integration with college LMS (Moodle)
- Research paper submission

---

# PART 3 — Full System Architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Student pastes YouTube URL  OR  uploads MP4/audio file
                    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROCESSING PIPELINE (runs once per lecture)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 — Audio Extraction
yt-dlp downloads audio-only stream from YouTube
(audio only = smaller file, faster processing)
Output: lecture_audio.mp3

Step 2 — Noise Reduction (optional pre-processing)
noisereduce library cleans background noise
Improves Whisper accuracy on low-quality recordings
Output: lecture_audio_clean.mp3

Step 3 — Transcription
Whisper (small model, CPU-compatible) processes audio
Output: transcript with word-level timestamps
{
  "text": "activation functions decide...",
  "start": 14.22,
  "end": 17.10
}

Step 4 — Concept Extraction
KeyBERT reads transcript in 5-minute chunks
Identifies top concepts per chunk
spaCy handles linguistic cleanup
Output: concept map
{
  "Activation Functions": [14.22, 17.10],
  "Backpropagation":      [24.00, 28.00],
  "Gradient Descent":     [28.00, 33.15]
}

Step 5 — Dependency Resolution
System checks concept map against dependency JSON
Adds prerequisite ordering to each concept
{
  "Backpropagation": {
    "timestamps": [24.00, 28.00],
    "requires": ["Activation Functions", "Loss Functions"]
  }
}

Step 6 — Clip Cutting
FFmpeg cuts one MP4 clip per concept
Stored locally with concept label as filename
activation_functions.mp4    (2 min 48 sec)
backpropagation.mp4         (4 min 00 sec)
gradient_descent.mp4        (5 min 15 sec)

Step 7 — Quiz Generation
Template engine creates 1 MCQ per concept
Question + 4 options (1 correct, 3 distractors)
Each question tagged internally to concept + clip

All processed data stored in SQLite database.
Next time same lecture is loaded — instant, no reprocessing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STUDENT INTERACTION LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Student logs in → selects lecture → takes assessment

Assessment modes:
  Mode A — MCQ Quiz (5-8 questions)
  Mode B — Flashcard Review
  Mode C — Concept Summary Cards

Student submits responses
System scores responses
Wrong answers → concepts identified → dependencies checked

Output: personalised clip playlist in correct learning order

Clip 1: Activation Functions    14:22–17:10   (play)
Clip 2: Backpropagation         24:00–28:00   (play)

Student watches clips inside Streamlit app
Student retakes assessment
Improvement score logged

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FACULTY LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Separate Streamlit tab (professor login)

Lecture timeline displayed horizontally
Colour intensity per timestamp:
  Green  = < 30% students confused
  Orange = 30–60% students confused
  Red    = > 60% students confused

Below timeline:
  Per-concept wrong answer rate table
  "Backpropagation — 71% of students confused (24:00–28:00)"
  "Consider supplementing or re-recording this segment"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATABASE LAYER (SQLite)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tables:
  lectures      — video URL, title, processed status
  concepts      — concept name, timestamps, lecture ID
  clips         — file path, concept ID, duration
  questions     — question text, options, correct, concept ID
  students      — student ID, name, email
  responses     — student ID, question ID, answer, correct, timestamp
  sessions      — student ID, lecture ID, score, date
```

---

# PART 4 — Tech Stack (Every Tool Explained)

| Tool | Purpose | Why this one | Cost |
|---|---|---|---|
| Python 3.10+ | Everything | Universal ML/NLP language | Free |
| Whisper (small) | Audio transcription | Runs on CPU, free, offline | Free |
| yt-dlp | YouTube audio download | Actively maintained, supports time ranges | Free |
| noisereduce | Audio cleaning | Simple Python library, 2 lines of code | Free |
| KeyBERT | Concept extraction | Semantic keyword extraction, not frequency | Free |
| spaCy | NLP preprocessing | Fast, production-grade, en_core_web_sm model | Free |
| FFmpeg | Clip cutting | Industry standard, lossless cutting | Free |
| Streamlit | Web app | Python-native, no frontend knowledge needed | Free |
| SQLite | Database | Zero setup, built into Python | Free |
| Plotly | Faculty heatmap chart | Interactive timeline visualisation | Free |
| sentence-transformers | Flashcard generation | Semantic similarity for distractor generation | Free |
| Ollama + Gemma-2B | Concept summary cards | Runs locally, no API cost | Free |

**Total infrastructure cost: Rs. 0**

---

# PART 5 — Team Division

| Person | Owns | Why |
|---|---|---|
| **Aayush (you)** | Pipeline infrastructure, SQLite database, Streamlit app, deployment | MLOps track — pipeline + serve is your strength |
| **Person 2 (GPU access)** | Whisper transcription, KeyBERT concept extraction, quiz generation, DKT model (Sem 8) | Compute-heavy tasks |
| **Person 3** | FFmpeg clip cutting, faculty dashboard, flashcard system, spaced repetition | Frontend + data visualisation |

**Rule:** Nobody works in isolation. Every feature is reviewed by all three before it's merged.

---

# PART 6 — Month by Month Build Plan

## Semester 7 — Build the Engine

---

**Month 1 — Foundation & Research**

Week 1:
- Set up shared GitHub repository with proper branch structure
- Every member installs Python environment with all libraries
- Read 2 base papers (Gabajiwala 2022, Das 2021) — everyone, not just one person
- Watch 3 NPTEL lectures you'll use as test data throughout Sem 7

Week 2:
- Build audio extraction — yt-dlp downloads audio from YouTube URL
- Test on 5 different YouTube lectures — different quality, different accents
- Document which lecture qualities work and which don't (this becomes your limitations section)

Week 3:
- Integrate Whisper transcription
- Test on the same 5 lectures
- Measure accuracy by comparing transcript to actual lecture content
- Tune model size — tiny vs small vs medium — find CPU-friendly sweet spot

Week 4:
- Build the SQLite schema — all tables defined, migrations written
- Build lecture ingestion — URL in, transcript out, stored in DB
- End of month deliverable: paste any YouTube URL, get a timestamped transcript stored in database

---

**Month 2 — Concept Extraction & Dependency Map**

Week 1:
- Integrate KeyBERT — extract top 10 concepts per lecture
- Test on your 5 NPTEL lectures — are the concepts actually meaningful?
- Tune chunk size (5-minute chunks vs 10-minute chunks) based on results

Week 2:
- Map concepts to timestamp ranges
- Build concept-to-timestamp table in SQLite
- Manual review — check if extracted concepts match what the lecture actually covered

Week 3:
- Build the dependency JSON for 3 domains: ML fundamentals, DSA, Computer Networks
- Structure: concept → list of prerequisites
- 50-100 concepts per domain is sufficient for a demo

Week 4:
- Integrate dependency resolution into pipeline
- Given a set of failed concepts, system outputs ordered rewatch list
- End of month deliverable: given any lecture + list of failed concepts, outputs ordered concept sequence

---

**Month 3 — FFmpeg Clip Cutting + Quiz Generation**

Week 1:
- Build FFmpeg clip cutter — given timestamps, extract MP4 clip
- Store clips with concept label as filename
- Test: does the clip start and end at the right moment?

Week 2:
- Build template-based MCQ generator
- One question per concept
- 3 distractor options using WordNet or nearby transcript terms
- Store questions in SQLite linked to concept and clip

Week 3:
- Build quiz interface in Streamlit
- Student sees questions, selects answers, submits
- System scores and identifies wrong answers

Week 4:
- Connect wrong answers to dependency resolver to clip playlist
- End of month deliverable: student takes quiz → gets personalised clip playlist

---

**Month 4 — In-App Clip Playback + Student Experience**

Week 1:
- Embed clips in Streamlit using `st.video()`
- Clips play in sequence — clip 1 finishes, clip 2 starts
- Student never leaves the app

Week 2:
- Add student login (simple email + password, no OAuth needed)
- Sessions stored in SQLite — student can return and see their history
- Add before/after score comparison

Week 3:
- Add flashcard mode — front: concept name, back: one-line definition + "Watch clip" button
- Add concept summary card mode — Ollama generates one-paragraph summary per concept

Week 4:
- Full integration test — every feature working end to end
- Test on 5 different lectures from scratch
- End of month deliverable: complete student-facing system working

---

**Month 5 — Faculty Dashboard**

Week 1:
- Build faculty login (separate role from student)
- Faculty can upload lecture and see which students have watched and quizzed

Week 2:
- Build confusion aggregation — per concept, calculate % students who got it wrong
- Build Plotly timeline chart — lecture duration on X axis, confusion rate as colour intensity

Week 3:
- Add per-concept table below timeline
- "Backpropagation — 71% confusion — timestamp 24:00–28:00 — Consider reviewing"
- Add export to PDF option (optional but impressive)

Week 4:
- End of month deliverable: working faculty dashboard with real aggregated data from at least 10 simulated student sessions

---

**Month 6 — Polish, Testing, Documentation**

Week 1-2:
- User testing — get 10-15 actual students from your college to use it
- Collect feedback — what confuses them, what they love, what breaks
- Fix the top 5 issues they report

Week 3:
- Write the Sem 7 report — problem statement, architecture, results, limitations, future scope
- Record a 3-minute demo video of the complete system working

Week 4:
- Sem 7 submission
- End of Sem 7 deliverable: complete working system, tested on real users, documented

---

## Semester 8 — Make It Intelligent

---

**Month 7 — DKT Knowledge Tracing**

- Install pyKT library
- Feed student response history from SQLite into DKT model
- DKT predicts probability of knowing each concept for each student
- System uses predictions to proactively schedule review before the student asks
- Test: does DKT predict forgetting accurately after 1-2 weeks?

---

**Month 8 — Spaced Repetition Scheduler**

- Implement SM-2 algorithm (10 lines of code)
- Every concept gets a next-review date per student
- System sends reminder notifications (Streamlit notification or email)
- DKT + SM-2 combined: personalised review schedule that adapts to actual performance

---

**Month 9 — LLM Quiz Upgrade**

- Integrate Ollama + Mistral 7B locally (GPU peer handles this)
- Replace template MCQs with LLM-generated contextual questions
- Questions are now based on what the professor actually said, not just the concept name in general
- A/B comparison — do LLM questions lead to better learning outcomes than template questions?

---

**Month 10 — Experiment Tracking + Validation Study**

- Integrate MLflow for experiment tracking
- Run a proper user study — 30 students, split into two groups
  - Group A uses your system
  - Group B rewatches lectures normally
- Compare quiz improvement scores between groups
- This data is your results section and the basis for a paper

---

**Month 11 — Report Writing + Paper Draft**

- Write complete Sem 8 report
- Draft research paper — target ICACCI or IEEE EDUCON
- Prepare viva presentation — 15 slides, 10-minute demo rehearsal

---

**Month 12 — Final Viva Preparation**

- Practice demo until it runs in under 5 minutes from URL paste to clip playing
- Prepare answers to every possible viva question (we've already covered most of them)
- Final submission

---

# PART 7 — Demo Script (Exactly What to Show in Viva)

This is the 5-minute demo that wins the room.

**Minute 0-1 — Setup**
Open Streamlit app in browser. Say: "This is LecGap. I'm going to paste a real NPTEL lecture link right now."

Paste the URL. Click process. Show the progress bar running. (Pre-processed — it loads in 10 seconds.)

**Minute 1-2 — Show the concept map**
Transcript appears. Concept map appears. Say: "The system has identified 7 key concepts in this 45-minute lecture and mapped each one to its exact timestamp. Watch what happens when a student takes the quiz."

**Minute 2-3 — Take the quiz live**
Log in as a student. Take the 7-question quiz. Deliberately get 2 questions wrong — Activation Functions and Backpropagation.

**Minute 3-4 — Show the gap detection**
Submit quiz. Show the dependency check running. Say: "The system noticed that Backpropagation requires Activation Functions. So it's showing Activation Functions first, then Backpropagation — not in the order I got them wrong, but in the order I need to learn them."

Two clips appear. Click clip 1. It plays instantly inside the app.

**Minute 4-5 — Show the faculty dashboard**
Switch to faculty tab. Show the lecture timeline with a red zone at 24:00. Say: "This student is the 8th person to get Backpropagation wrong. The system has now flagged this segment as a high-confusion zone for the professor." 

Stop. Let it sit. Don't say anything for 3 seconds.

That silence is your close.

---

# PART 8 — Answers to Every Viva Question

**Q: YouTube already has timestamps.**
A: YouTube timestamps tell every viewer where topics are. Our system tells each student which concept they personally didn't understand and plays only that clip. YouTube has no idea whether you understood the content.

**Q: YouLearn/Knowt already does quiz generation.**
A: They generate quizzes and stop. They don't connect your wrong answer back to the lecture clip. They don't check concept dependencies. They don't show the professor where their class got confused. We do all three.

**Q: What if Whisper gives wrong transcription?**
A: We pre-process audio with noise reduction. We tested on 5 lecture quality levels. The system displays the transcript before quiz generation so the user can verify. For our demo we use NPTEL lectures which have studio quality. Handling poor audio is documented as a known limitation and future work.

**Q: How is the concept dependency map built?**
A: For Sem 7 — manually curated JSON for ML, DSA, and Networks. 200 concepts, well-known prerequisites. In Sem 8 we automate this using co-occurrence analysis on the transcript. Manual curation is a practical engineering decision, not a flaw.

**Q: What's the ML in this project?**
A: Three ML components. Whisper — deep learning ASR model. KeyBERT — transformer-based semantic keyword extraction. DKT in Sem 8 — LSTM-based knowledge tracing. Plus the data pipeline, serving layer, and experiment tracking — full MLOps stack.

**Q: How is this better than a professor just adding chapters to their video?**
A: Chapters are static — same for every student. Our system is dynamic and personalised — two students watching the same lecture get different clip playlists based on their individual quiz performance. A professor would need to manually quiz every student and manually map their answers to chapters. We do this automatically for every student every session.

**Q: Did you validate this actually helps students learn?**
A: In Sem 7 — before/after quiz score comparison shows improvement after watching recommended clips. In Sem 8 — formal user study with 30 students, control group vs system group, measuring actual exam score correlation. That validation data is in our report.

---

# PART 9 — GitHub Repository Structure

```
lecgap/
│
├── pipeline/
│   ├── downloader.py       # yt-dlp audio extraction
│   ├── transcriber.py      # Whisper integration
│   ├── concept_extractor.py# KeyBERT + spaCy
│   ├── clip_cutter.py      # FFmpeg wrapper
│   └── quiz_generator.py   # Template MCQ generation
│
├── models/
│   ├── dependency_graph.json  # Concept prerequisites
│   └── dkt_model.py           # DKT (Sem 8)
│
├── app/
│   ├── main.py             # Streamlit entry point
│   ├── student_view.py     # Quiz + clip playlist
│   ├── faculty_view.py     # Confusion heatmap
│   └── auth.py             # Login system
│
├── database/
│   ├── schema.sql          # SQLite table definitions
│   └── db_manager.py       # All DB operations
│
├── data/
│   ├── clips/              # Generated video clips
│   └── transcripts/        # Stored transcripts
│
├── tests/
│   └── test_pipeline.py    # Unit tests
│
├── requirements.txt
├── README.md
└── demo_video.mp4          # 3-minute demo for submission
```

---

# PART 10 — The Three Rules That Keep This Project on Track

**Rule 1 — Core before enhancement.**
If Core 1, 2, and 3 are not fully working, no team member touches enhancement features. Not even a line of DKT code before the faculty heatmap is live.

**Rule 2 — Demo on real data from Week 4 onwards.**
Every monthly milestone must be demonstrated on a real NPTEL lecture, not synthetic data. If it only works on test data you wrote yourself, it's not done.

**Rule 3 — Every limitation is documented, not hidden.**
When something doesn't work perfectly — audio quality, wrong concept extraction, slow processing — write it in the report as a known limitation with a proposed solution. An honest limitation is strong. A hidden failure discovered in viva is catastrophic.

---
