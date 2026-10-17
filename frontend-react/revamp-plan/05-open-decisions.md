# 05 · Open decisions

Five choices the revamp does not settle by itself. Each is stated with its real
cost, so taking one is a decision rather than a default. Nothing here blocks P0.

---

## 1 · Which theme base greets a first-time visitor

**Open because:** `prefers-color-scheme` decides today, and the shipped default is
dark (`DEFAULT_BASE = 'dark'`). The mock review suggested the **light** theme
reads stronger — warm alabaster paper with serif headings — which is also the
theme `references/color_scheme.txt` actually describes, and the one the light
palette was built from. Most first-time visitors on a light-mode OS already see
light; the question is what someone with no OS preference gets.

| Option | Change | Cost |
|---|---|---|
| Keep dark as default | nothing | none |
| Flip default to light | `DEFAULT_BASE = 'light'` + `resolveInitialBase` fallback | e2e theme spec's dark/light assertions re-read; screenshot baselines regenerate; the Streamlit twin (`theme.py::DEFAULT_BASE`, `.streamlit/config.toml`) should follow or the two engines disagree |

**Recommendation:** decide after P0, when the sidebar is real and both themes can
be walked through the actual app rather than a mock. It is a one-line change
whenever it is taken — no reason to rush it.

---

## 2 · `accent` is a byte-for-byte duplicate of `info`

**Open because:** in both palettes, `accent === info` exactly. So
`palette.secondary` is indistinguishable from `palette.primary`, the MUI
`secondary` slot is a fake, and `gradient('info','accent')` — already used in
`JobDrawer` — is a flat wash wearing a gradient's name.

| Option | Change | Cost |
|---|---|---|
| Leave it | nothing | the app keeps a slot that does nothing; any future "accent" design is a lie until this is fixed |
| Give `accent` a real hue | one value per palette + retune node ramps if they use it | the golden node tables in `theme.test.ts` are measured from the Python with the current values; `tests/test_theme.py` and `test_theme_parity.py` need the twin constants updated in the same commit. Real work, contained, and it is *frontend-only* freedom — the node goldens pin `ink_light`/`ink_dark`/`node_light`/`node_sat`, not `accent` |

**Recommendation:** fix it, but as its own commit with the Python twins, not
folded into the revamp. It is a correctness issue (a slot that lies), which is
exactly the class of thing this session has been removing.

---

## 3 · Can a course be renamed?

**Open because:** you asked, and the honest answer today is *no* — there is no
rename path anywhere, and it is not an oversight.

`course_id` is the primary key spread across roughly ten tables (lectures,
concepts, graph nodes, graph edges, passages, links, clips, quiz items,
responses, jobs), plus the clip directory on disk
(`data/processed/clips/{lecture_id}/…` is keyed by lecture, but the course
prefix appears in paths and media), plus every client-side cache key and
`localStorage['lecgap.course.v1']`.

| Option | Change | Cost |
|---|---|---|
| No rename (rename = delete + re-upload) | nothing | a typo'd course id means re-transcribing everything |
| Rename as a copy-and-rewrite operation | a backend endpoint that inserts the new id, rewrites every FK, moves media, deletes the old rows, inside one transaction | a real backend feature: migration test, a maintenance window or a job, and a conflict rule (target id already exists). Not a button — a brick |
| Rename as *display alias only* | a `display_name` column, id never changes | cheap and safe, but URLs, caches and clip paths keep the old id, so the picker must show both, which confuses more than it helps |

**Recommendation:** leave it out of the revamp. If it is wanted, it is a backend
brick with its own plan — the UI is the easy 10% of it.

---

## 4 · Does the warm theme extend to the Streamlit baseline?

**Open because:** this branch has already changed `backend/frontend/theme.py` and
`.streamlit/config.toml`, so the **Streamlit** app's look changed along with the
React one. But `docs/streamlit-baseline/` (committed) describes the old dark
espresso baseline, and `main`'s Streamlit is untouched.

| Option | Change | Cost |
|---|---|---|
| Streamlit follows the new theme | update the baseline docs' palette section | docs are already written around measured values; they would need the new token table quoted and the theme tests re-verified |
| Streamlit reverts to its old theme | revert two files on this branch | the branch keeps a divergence that will resurface at merge time |

**Recommendation:** decide it **before merging to `main`**, not now. The docs
describe a baseline; if the baseline moves, the docs move with it in the same
change. Leaving this open is fine until the merge is planned.

---

## 5 · When does this branch merge to `main`?

**Open because:** `main` is the documented stable baseline and has not moved. This
branch carries verified fixes, a redesign in progress, and an un-reviewed
third-party rebuild.

| Option | Bar |
|---|---|
| Merge now | none — not recommended; it drags an unreviewed rebuild and an in-progress redesign into the stable baseline |
| Merge after the revamp | all gates green, both engines' themes decided (#4), the rebuild reviewed file by file, baseline docs updated |
| Never merge (branch becomes the product) | `main` stays as a frozen reference; the docs then need a note that the baseline is historical |

**Recommendation:** after the revamp, with #4 decided first. There is no rot
pressure — `main` is not receiving changes — so the only cost of waiting is
that `main` stays old, which is what a reference branch is for.

---

## Parked, with a trigger to revisit

| Item | Revisit when |
|---|---|
| Mobile / narrow-width layout | after P6 — the mock is desktop-first and the sidebar now needs a real narrow-width answer (a drawer, not `display:none`) |
| Virtualised lecture table | a real course with hundreds of lectures, if the table is measurably slow |
| `quizzes.create` (the blocking legacy generator) and other dead wrappers | they are smoke-test parity; delete them when the Python side stops referencing them |
| `dagre` (installed, never imported) | if the layered DAG layout is ever replaced by a graph-layout pass — otherwise remove |