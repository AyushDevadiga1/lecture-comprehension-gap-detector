import { useEffect } from 'react'
import { Alert, Snackbar } from '@mui/material'
import { useCompletionStore } from '../../store/useCompletionStore'
import { stoppedLabel } from '../../lib/jobCompletions'

/**
 * Announce completed jobs exactly once.
 *
 * REACT_ARCHITECTURE.md §1, and §0 rule 3: *a finished job's follow-up is
 * **recorded, then announced once by the page** — never from inside the thing
 * that re-renders.* The Streamlit engine learned this the hard way: a success
 * message rendered inside its 1 Hz `st.fragment` flashed and vanished, which is
 * why `shell.py:_record_ready` only records and `drain_ready` (called from the
 * dashboard body, outside the fragment) is what renders.
 *
 * In React the ordering hazard is different but the answer is the same: the
 * announcement lives in this host, at the top of the tree, and the progress
 * surface in `JobDrawer` shows *live* jobs only. So neither the message nor its
 * follow-up is rebuilt on every tick, and neither is torn down by navigation.
 *
 * The "once" guarantee lives in `diffCompletions` (it reports the transition
 * into a terminal state, and the feed re-sends that state forever) plus `push`
 * (which replaces rather than stacks). Nothing here re-announces.
 */
export const JobCompletionHost: React.FC = () => {
  const items = useCompletionStore((s) => s.items)
  const dismiss = useCompletionStore((s) => s.dismiss)

  // A stale queue from a previous session must not re-announce on mount.
  useEffect(() => {
    const stale = items.filter((i) => Date.now() - i.at > STALE_MS)
    for (const i of stale) dismiss(i.id)
    // Intentionally runs only on mount: a completion recorded later is fresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      {items.map((item) => (
        <Snackbar
          key={item.id}
          open
          autoHideDuration={AUTO_HIDE_MS}
          onClose={(_event, reason) => {
            // 'clickaway' would let a stray click swallow a completion notice.
            if (reason !== 'clickaway') dismiss(item.id)
          }}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        >
          <Alert
            onClose={() => dismiss(item.id)}
            severity={severityFor(item.status)}
            variant="filled"
            sx={{ width: '100%' }}
          >
            {item.status === 'ready'
              ? item.detail
              : `${item.title} — ${stoppedLabel(item.status)}${item.detail ? `: ${item.detail}` : ''}`}
          </Alert>
        </Snackbar>
      ))}
    </>
  )
}

const AUTO_HIDE_MS = 6000
/** Anything older than this in the queue on mount is from a previous session. */
const STALE_MS = 60_000

function severityFor(status: string): 'success' | 'error' | 'warning' | 'info' {
  if (status === 'ready') return 'success'
  // `orphaned` means a server restart, not a failure of the work.
  if (status === 'orphaned') return 'warning'
  if (status === 'cancelled') return 'info'
  return 'error'
}
