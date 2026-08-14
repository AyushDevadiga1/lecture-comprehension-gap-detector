# Known Limitations

Stated plainly, on purpose — an honest limitation documented up front is
far stronger than one discovered by a panelist during the viva.

## 1. The base "watch a lecture, get quizzed, review weak spots" loop is
not novel

Products already do this at scale: YouLearn (reported 2M+ users) and
Knowt both do transcript-based quiz/flashcard generation and weak-spot
review from a video link. NotebookLM (Google) also generates quizzes,
flashcards, and a "Mind Map" visualization from ingested sources,
including video. This project does not claim to have invented this loop
— it is necessary infrastructure for the actual contribution, not the
contribution itself.

## 2. The prerequisite-learning problem itself is an established research
area, not a discovery

"Which concept requires which" as an NLP problem has been studied since
at least 2015, with a dedicated benchmark (LectureBank) and a steady
stream of published methods, including recent LLM-based approaches. This
project applies and evaluates recent techniques inside a full working
system — it does not claim to have originated the underlying research
direction.

## 3. Evaluation is domain-bounded

Rigorous, benchmarked evaluation of the prerequisite classifier is
limited to the domains LectureBank covers (NLP, ML, AI, DL, IR). The
pipeline runs on any lecture content, but accuracy outside these domains
is unproven. See `docs/EVALUATION.md`.

## 4. The concept graph is scoped per-course, not a universal concept bank

The system does not attempt to build one global, fully-linked graph of
all human knowledge — that is a separate, much harder research problem
(the kind of effort projects like Wikidata or ConceptNet have spent years
on). Each course's graph only ever contains concepts that have actually
appeared in that course's ingested lectures.

## 5. The refinement loop is validated via controlled simulation, not a
real classroom

See `docs/EVALUATION.md` Claim 2 for full detail. The synthetic-student
recovery experiment proves the mechanism can work; it does not prove real
student behavior matches the simulation's statistical properties. A real
pilot is future work, not current scope.

## 6. Team execution risk

The team has 4 members, but reliability of full participation from all
members is uncertain, and the project may end up being executed largely
solo. See `docs/TEAM.md`. Scope should be revisited against this risk
rather than assumed fixed.

## 7. Decoupled architecture specifics are not yet finalized

See `docs/DECISIONS.md` — the backend/frontend split proposed in
`docs/ARCHITECTURE.md` is a default suggestion, not a confirmed decision.
