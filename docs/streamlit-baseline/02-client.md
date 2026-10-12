# 02 · Transport and Tier-1 cache — `frontend/client.py`

**File:** `frontend/client.py` (427 lines). **No Streamlit imports** — this is
the frontend↔backend boundary defined by `plan/FRONTEND_API_CONTRACT.md`, and
it is unit-testable without any Streamlit machinery.

## Responsibilities

1. Validated base URL (`LECGAP_API_URL`, default `http://127.0.0.1:8000`).
2. Auth header (`X-API-Key` from `LECGAP_API_KEY`, when set).
3. Error-safe `get`/`post`/`delete`/`put` that always extract the backend
   `{detail}` envelope.
4. A TTL `CacheStore` (module singleton) shared by every session in the
   process, with one explicit invalidation rule.
5. `media_url` mapping of server clip paths → the Range-capable media endpoint.
6. Chunked, cancellable media upload + Whisper quota maths.

## Base URL and auth

- `validated_api_url()` accepts only `http(s)` URLs with a host; anything else
  raises `ValueError`. This is a stated security control (audit #25).
- `_auth_headers()` sends `X-API-Key` only when the env var is set.

## The request core

`_request(method, path, …)` is the **only place that touches `requests`**, so
tests replace exactly one seam (`client.requests`):

- one retry on transient `requests.ConnectionError` (1 s sleep, neutralisable
  in tests via `RETRY_DELAY_S` / `ENABLE_RETRY`); timeouts are recorded and
  re-raised, not retried;
- HTTP ≥ 400 → records the error and returns `(status, None)` instead of
  raising — callers branch on truthiness, never on exceptions;
- non-JSON success bodies are recorded as errors and return `(status, None)`;
- success clears the recorded error.

The public verbs (`get`, `post`, `delete`, `put`) catch
`requests.RequestException` and return `None`. Note the timeouts: reads 30 s,
writes 600 s (LLM-backed generation is slow).

## Error model

One-shot structured record of the last failed request: `{kind, status, detail,
path}`. `take_last_error()` returns **and clears** it. Kinds are `timeout`,
`network`, `http`, `json`. Two properties matter:

- **Thread-local source of truth.** Two browser sessions (each running the
  script in its own thread) and the upload worker thread can never consume or
  clobber each other's errors. The module-level `LAST_ERROR` remains only as a
  test-seam fallback for single-threaded tests.
- **`{detail}` extraction, never tracebacks.** `_extract_detail` reads the
  backend's `{"detail": …}` envelope and falls back to response text.

## Tier-1 cache (`CacheStore`)

TTL-keyed, lock-guarded, process-wide. Three rules:

1. **Returned values are deep copies** — callers can never poison the cache by
   mutating a payload.
2. **Failures are never cached** — a `None` loader result is not stored.
3. **One invalidation rule** — `invalidate_for_course(course_id)` clears the
   `/courses` and `/lectures` namespaces. Everything course-relevant lives
   under those two prefixes, so both are cleared; the data is small and safe.

Per-endpoint TTLs (the freshness policy, all in one place):

| Reader | Endpoint | TTL |
|---|---|---|
| `course_summaries` | `GET /courses` | 60 s |
| `list_lectures` | `GET /lectures` | 60 s |
| `lecture_detail` | `GET /lectures/{id}` | 300 s |
| `lecture_clips` | `GET /lectures/{id}/clips` | 60 s |
| `course_stats` | `GET /courses/{id}/stats` | 300 s |
| `course_graph` | `GET /courses/{id}/graph` | 300 s |
| `course_snapshot` | `GET /courses/{id}/snapshot` | **5 s** |
| `usage` | `GET /usage` | 30 s |

The 5 s snapshot TTL is the live-consistency layer: both dashboards poll it,
so a change made in one session surfaces in the other within seconds.

## Course-ID rules

- `normalize_course_id`: `strip → UPPER → whitespace→'-' → collapse repeats`.
  Applied to **new** identifiers, so one course never fragments into `ML1` vs
  `ml1` vs `ml 1`. Existing keys in any case are left untouched.
- `valid_course_id`: backend pattern (letters/digits/underscore/hyphen,
  1–128 chars) — existing keys stay usable.
- `is_canonical_key`: the uppercase-slug form for new keys.
- `canonical_compare`: case-insensitive identity for duplicate detection
  (never sent to the backend).

## Media URLs and uploads

- `media_url(path)` maps a server clip path such as
  `data/processed/clips/3/clip_name.mp4` to
  `{API}/media/clips/3/{percent-encoded filename}`. The lecture id is read from
  the path's second-to-last segment. Returns `None` for empty paths, path
  traversal (`..`/`.`), or non-integer lecture ids. Filenames are
  percent-encoded because concept names routinely contain spaces
  ("INNER JOIN"), which break unencoded media requests — previously clips
  rendered but never played.
- `upload_media(lecture_id, filename, file_bytes, …)` streams the body lazily
  in 1 MiB slices with an explicit `Content-Length` (no second full copy in
  memory), publishes `uploading` progress server-side, and stops between chunks
  when a `threading.Event` cancel flag is set. Empty input records a 400-class
  error and returns `None`.

## Quota maths

`whisper_requests_for(duration_s)` estimates Groq Whisper calls for a lecture
(one per 300 s window, mirroring the backend's FLAC split); `videos_left`
turns remaining quota into "how many more lectures like this fit". Both feed
the usage row (file 07).
