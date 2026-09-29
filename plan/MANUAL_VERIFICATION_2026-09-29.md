# Manual verification attempt — 2026-09-29, and why it is INCONCLUSIVE

> **Read this before trusting any statement in the handoff about the app
> "working".** The last person to open the app reported that **every button was
> dead**: no status updates, no job progress, quizzes/extraction/clips all
> non-responsive. That contradicts 297 passing React tests and 710 passing Python
> tests. Both things are true, and the reason is the most important thing on this
> page.

## What was reported

Verbatim from the user, after being asked to run the app:

> "I think all of the buttons are broken currently or hugely delayed, cause none
> of them update the status, that whether we are actually running or actually
> fetching is done or not, not only that none of the buttons are working
> including quizes, extraction clips and other."

## The evidence

The uvicorn log from the only window in which a backend was running during that
session (kept at `plan/evidence/uvicorn-2026-09-29.log`):

```
INFO:     Started server process [4876]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     127.0.0.1:63916 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:63916 - "GET /favicon.ico HTTP/1.1" 404 Not Found
INFO:     127.0.0.1:64125 - "GET / HTTP/1.1" 404 Not Found
INFO:     127.0.0.1:64125 - "GET /health HTTP/1.1" 200 OK
```

Read it carefully, because it is almost conclusive about what happened:

1. The backend **started fine**. No import error, no migration failure, no
   database problem. `Application startup complete` on the first attempt.
2. The two `/health` 200s are **mine** (the automated liveness check).
3. `GET /favicon.ico` and `GET /` are **a browser** — and they went to
   **port 8000**, i.e. to FastAPI directly, not to the Vite dev server.
4. **There are no proxied requests at all.** Not one `/courses`, `/jobs/stream`,
   `/lectures`, or `/quizzes`. If the React app at :5173 had been used while that
   backend was up, Vite would have forwarded every call here and this log would
   be full of them. It is empty.

## What that means: two hypotheses, and the test that separates them

**H1 — the browser was pointed at the wrong place.** `http://localhost:8000`
serves the FastAPI app, which has no UI. A 404 page plus a missing favicon is
exactly what the log shows, and it explains "every button is dead" perfectly: there
were no buttons. The right URL is `http://localhost:5173/student`.

**H2 — the React app was used, but the backend was already down.** The backend
process was killed at 17:48 (see below), so anything attempted after that fails
every request. The empty log is also consistent with this.

**H3 — the app is genuinely broken.** Cannot be excluded, and must not be assumed
away. The entire job-feed path is mocked in tests and has never run against a
real server, so a whole class of bugs is untested. See below.

The next session must resolve H1 vs H2 vs H3 **in the first five minutes**, before
touching any code.

## Why 297 passing tests did not catch this

Because every test of the feed injects a fake transport. `JobFeed` takes
`fetchImpl`, `sleep`, `setTimer` and `clearTimer` as constructor seams, and
`mockFetch` replaces `globalThis.fetch`. So the suite proves the *policy* — the
backoff ladder, the poll-between-failures rule, the change token, the completion
diff — and proves nothing about:

- **whether Vite's dev proxy actually streams `/jobs/stream` to the browser**;
- **whether the real server's SSE framing is parsed correctly** — `retry: 2000`,
  `event: jobs`, `: keep-alive`, and the change-gated full-array snapshot;
- **whether `requestAnimationFrame` coalescing behaves** in a real browser (jsdom
  has it; a throttled or backgrounded tab does not fire it);
- **whether the browser can read a streaming `fetch` response at all** through the
  proxy;
- **whether anything is listening on :8000 and reachable from :5173**.

That is a real and structural gap, not a test-tuning problem. The fix is Wave 4
(Playwright) and it should be brought **forward**, not deferred: until one E2E test
drives a real job against a real server, the app's central claim is unverified.

## The exact procedure to settle it

Do these in order. Do not start debugging before step 4.

**1. Start the backend and leave it running.**
```powershell
cd C:\Users\hp\Desktop\lecture-comprehension-gap-detector
& "D:\Anaconda3\envs\lecgap\python.exe" -m uvicorn backend.main:app --port 8000
```
It must print `Application startup complete`. Leave this terminal alone.

**2. Prove the backend serves real data, from the shell — not the browser.**
```powershell
Invoke-RestMethod http://127.0.0.1:8000/courses | ConvertTo-Json -Depth 3
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```
Expect a non-empty array of courses (`ml`, `prob`, `dl1`, ...). If this is empty
or errors, the problem is the **backend or database**, not React, and nothing
else matters yet.

**3. Prove the SSE stream works *without a browser*.** This is the single most
informative command in the whole procedure, and it needs no proxy, no CORS and no
React:
```powershell
curl.exe -N --max-time 5 http://127.0.0.1:8000/jobs/stream
```
Expect within a second: `retry: 2000`, then `: keep-alive` lines roughly once a
second. If this prints nothing, `GET /jobs/stream` is broken at the backend and
that alone explains every symptom in the report. If it works, the fault is between
the browser and the backend.

**4. Now start the frontend, and open the right URL.**
```powershell
cd C:\Users\hp\Desktop\lecture-comprehension-gap-detector\frontend-react
npm run dev
```
Open **`http://localhost:5173/student`** — not :8000. If :8000 renders a plain
404, that is H1 confirmed and the app was never under test.

**5. Watch the network tab, not the UI.** Open devtools → Network, filter
`jobs/stream`, and reload. Read three things:
   - the request **status** (200, or 404/401/500);
   - whether the response **stays open** (Chrome shows a pending request) or
     completes immediately;
   - whether frames **arrive** in the response body.
   Then check the Navbar dot: green "SSE Live" means the feed is live; amber means
   it is not, and the amber state is the one that would explain everything the
   user reported.

**6. Only then try a button.** Click **Start Quiz**. It should say "Queueing…",
   and a job should appear in the Background Tasks drawer. If the button
   responds but no job appears, the write path works and the feed does not — that
   pins the fault to the feed and nothing else.

## What to write down

For each of the six steps: the command, the output (trimmed), and pass/fail. The
next session's first act should be to read that, not to re-derive it.

## A note on how this happened

The instructions to run the app were correct, and the backend did start. But I
started a uvicorn instance myself, found it had not come up within 12 seconds,
reported "backend not up yet", and then **killed the process on port 8000** while
the user was trying to run things. If they tested after that point, every request
would have failed for a reason that has nothing to do with the code. The log shows
no proxied traffic from them at all, so the most likely explanation is H1, but H2
is not excluded and the process kill is a real possibility that should be
disclosed rather than glossed over.

**Lesson for next time:** when asked to hand over a runnable app, either leave the
process running and say so, or do not start one at all. Do not start something,
declare it not up, and then clean it up while the other person is mid-attempt.
