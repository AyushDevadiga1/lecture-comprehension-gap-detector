# 17 · Known gaps (verified on `main`, not rumours)

Each item below was checked against the `main` sources cited. They are
recorded so a model generating slides or plans from this folder does not
present the baseline as flawless — and so follow-up work starts from evidence.

1. **The auth banner can never fire.** `shell.render_auth_banner()` renders
   only when the recorded error has `kind == "auth"`, but `client.py` records
   exactly four kinds — `timeout`, `network`, `http`, `json` — and no code
   path ever records `"auth"`. A 401 arrives as `kind="http", status=401`, so
   a key-guarded backend produces silence where the banner should be. (The
   React rebuild's 401-banner work exists because of this failure class.)
2. **The most-read payloads are the least-typed.** `GET
   /courses/{id}/snapshot` and `GET /courses/{id}/stats` return plain `dict`
   (verified in `backend/api/routes/courses.py`); `/students/{id}/remediation`
   declares `response_model=QuizSubmitOut`, i.e. the submit shape, not a
   remediation shape. Field drift on these fails at render time, in no test.
3. **`accent` duplicates `info` in both palettes** (`theme.py`: both
   `#58a6ff` on dark, both `#0b5cad` on light). There is no true secondary
   hue; any info→accent gradient is a flat wash wearing a gradient's name.
4. **Quiz generation is a blocking POST.** The panel says so in its own
   docstring; making it a queued backend job is the recorded next step
   (checkpoint C2). Until then, generation freezes the session for minutes,
   mitigated only by a spinner and an explicit wait message.
5. **Wire format still carries filesystem paths** (`Clip.path`, remediation
   `clip`). The frontend maps path→URL at the render boundary and contract
   tests forbid the reverse mapper from returning, but traversal defence rests
   on `media_url` alone.
6. **`_record_ready` announces into Tier-2 `jobs.completed`; anything that
   clears that namespace between recording and `drain_ready` loses the
   announcement silently.** No test covers the interleaving; the window is one
   page pass wide.
