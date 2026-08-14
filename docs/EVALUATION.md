# Evaluation

This project makes two separate technical claims, and each needs its own
evaluation. Conflating them is the easiest way for this documentation to
drift into overclaiming, so they're kept strictly apart here.

---

## Claim 1 — The prerequisite classifier can correctly identify which
concept requires which

### Benchmark: LectureBank

Primary sources (verify directly, don't take this doc's word for it):

- Repo: https://github.com/Yale-LILY/LectureBank
- Original paper (AAAI 2019): https://ar5iv.labs.arxiv.org/html/1811.12181
- LectureBank2.0 / cross-domain paper (ACL 2021): https://arxiv.org/pdf/2105.03505
- Author's plain-language writeup: https://ireneli.eu/2019/01/06/lecturebank-a-dataset-for-nlp-education-and-prerequisite-chain-learning/
- Quick reference: https://paperswithcode.com/dataset/lecturebank

There are actually three related resources here, and this project uses a
specific one — this distinction matters and was previously stated
imprecisely in early planning discussion, so it's called out explicitly:

| Version | Size | Domain coverage |
|---|---|---|
| **LectureBank 1.0 (used by this project)** | 1,352 files, 60 courses, 208 labeled prerequisite pairs | Spread across NLP, ML, AI, DL, IR |
| LectureBank2.0 | 1,717 files, 322 labeled concepts | Described by its own authors as "largely from NLP" |
| LectureBankCD (cross-domain extension) | +201 CV concepts, +100 Bioinformatics concepts | Built specifically to test cross-domain transfer |

LectureBank 1.0 is used because its five-domain spread is a closer match
to this project's test lectures (ML/DL coursework), rather than the
NLP-heavy LectureBank2.0.

### Method

- Fine-tune a pretrained embedding model (not train from scratch — 208
  labeled pairs is too small to train a classifier reliably from zero)
  on LectureBank's labeled prerequisite pairs.
- Cross-validate rather than a single train/test split, given the small
  dataset size.
- Report precision/recall/F1 against LectureBank's held-out pairs.
- The LLM reasoning cross-check (Stage 3) is evaluated separately for
  agreement rate with the classifier, not treated as ground truth itself.

### Scope of this claim

Rigorous evaluation is bounded to the domains LectureBank covers (NLP,
ML, AI, DL, IR). The extraction and classification pipeline itself does
not check domain before running — it is domain-agnostic in operation —
but outside these domains there is currently no labeled data to prove
accuracy against. This is documented as a stated boundary, not hidden:
*"The concept-extraction and prerequisite-classification pipeline is
domain-agnostic by design. Quantitative evaluation is conducted within
the domains covered by LectureBank; extending rigorous evaluation to
other domains is future work."*

---

## Claim 2 — The refinement loop actually makes the graph more accurate
over time using real usage signals

This is the project's most original claim, and the hardest to prove
honestly without a real classroom at scale. The method below is a
**controlled recovery experiment** — it proves the *mechanism* works, not
that real human students behave exactly like the simulation. That
distinction must stay explicit in the report; it is the difference
between an honest claim and an overstated one.

### Method

1. **Define a hidden ground-truth graph.** A known prerequisite structure
   for a test course (e.g. 30 concepts with defined "A requires B"
   relationships) is created and kept separate from anything the system's
   own pipeline can see directly — it functions only as an answer key for
   scoring, never as an input.

2. **Generate synthetic students via LLM personas.** Rather than
   simulating quiz answers as a weighted random correct/incorrect roll,
   each synthetic student is realized as an LLM prompted to roleplay a
   student who has been taught a defined, randomized subset of the hidden
   graph's concepts. The LLM genuinely attempts each quiz question,
   reasoning through what it does and doesn't understand, which produces
   realistic, patterned errors (driven by actual gaps in the "taught"
   subset) rather than statistical noise. This was chosen specifically
   over collecting a small real pilot group, since reliably recruiting
   volunteer test users was judged unrealistic for this team.

3. **Run the refinement loop.** The system's own pipeline (Stages 2-3)
   independently guesses its own version of the graph from lecture
   content — imperfect, like a real model would be. The refinement loop
   (Stage 7) then observes the synthetic students' quiz patterns and
   updates its guessed graph accordingly, exactly as it would with real
   classroom data.

4. **Measure convergence.** Compare the system's guessed graph, before and
   after processing synthetic quiz data, against the hidden ground-truth
   graph. Report edge-accuracy before vs. after refinement (e.g. "60%
   correct edges before refinement, 85% after N rounds").

### Honest limitation, stated plainly in the report

This experiment validates that the refinement *mechanism* can recover
known structure from noisy, LLM-generated behavioral signals in a
controlled setting. It does not validate that real students produce
signals with the same statistical properties as the LLM personas do. A
real classroom pilot remains the stronger form of evidence and is noted
as future work, not attempted in the current scope, given team
constraints (see `docs/TEAM.md`).
