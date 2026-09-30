import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../api/lectures'
import type { LectureOut } from '../../api/types'
import { queryKeys } from '../../lib/queryKeys'
import { formatClipTime } from '../../lib/format'

/**
 * Clip browser — every clip cut for one lecture, listed and playable.
 *
 * ## Why this exists
 *
 * The dashboard had a `<video>` element but no way to reach it: playback was
 * only reachable through the quiz remediation flow, so a user who had cut 24
 * clips had no browser for them. `GET /lectures/{id}/clips` already existed,
 * already returned canonical `/media/clips/...` URLs, and was called from
 * nothing.
 *
 * ## Invariants this must not break
 *
 * - **URLs, never paths.** `ClipOut.path` is the stored filesystem path and is
 *   deprecated; only `url` is rendered. A path in the payload is a contract
 *   failure (REACT_ARCHITECTURE §3) and the React client has no path→URL mapper,
 *   so there is nothing to fall back to.
 * - **§1, progress by push.** This component subscribes only to its own query,
 *   never to the job feed, so a job tick cannot re-render it. `AppLayout` stays
 *   out of it entirely.
 * - **§6, one invalidation rule.** No hand-rolled invalidation here. The feed
 *   already invalidates `queryKeys.clips(lectureId)` when a clips job finishes
 *   (`useJobFeed.ts`), which is why that entry exists and is deliberately not
 *   course-scoped.
 * - **§6, one request path.** Reads go through the `api/` wrapper, never `fetch`.
 * - **One colour system.** Only semantic MUI palette roles; no hex, no `tint()`
 *   with a literal.
 */

interface ClipBrowserProps {
  lectures: LectureOut[]
  /** Called with a lecture id so the parent can run "Cut Clips" for it. */
  onCutClips?: (lectureId: number) => void
}

export const ClipBrowser: React.FC<ClipBrowserProps> = ({ lectures, onCutClips }) => {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)

  // Default to the first lecture, and follow the list if it changes underneath
  // us (a course switch empties it). Deriving rather than storing a second copy
  // avoids a stale id pointing at a lecture that no longer exists.
  useEffect(() => {
    if (selectedId != null && lectures.some((l) => l.id === selectedId)) return
    setSelectedId(lectures.length ? lectures[0]!.id : null)
    setPlayingId(null)
  }, [lectures, selectedId])

  const {
    data: batch,
    isLoading,
    error,
  } = useQuery({
    queryKey: queryKeys.clips(selectedId ?? -1),
    queryFn: () => lecturesApi.clips(selectedId!),
    enabled: selectedId != null,
  })

  const clips = useMemo(() => batch?.clips ?? [], [batch])
  const playable = useMemo(() => clips.filter((c) => c.ok && c.url), [clips])
  const failed = useMemo(() => clips.filter((c) => !c.ok), [clips])
  const playing = useMemo(() => clips.find((c) => c.id === playingId) ?? null, [clips, playingId])

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 2, flexWrap: 'wrap' }}>
          <VideoLibraryIcon color="primary" />
          <Typography variant="h5" sx={{ fontWeight: 700, flexGrow: 1 }}>
            Clip Library
          </Typography>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="clip-browser-lecture-label">Lecture</InputLabel>
            <Select
              labelId="clip-browser-lecture-label"
              label="Lecture"
              value={selectedId ?? ''}
              onChange={(e) => {
                setSelectedId(Number(e.target.value))
                setPlayingId(null)
              }}
              disabled={lectures.length === 0}
            >
              {lectures.map((l) => (
                <MenuItem key={l.id} value={l.id}>
                  {l.title}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>

        {lectures.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No lectures in this course yet, so there are no clips to browse.
          </Typography>
        )}

        {selectedId != null && isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={28} />
          </Box>
        )}

        {selectedId != null && error != null && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Could not load clips for this lecture.
          </Alert>
        )}

        {selectedId != null && !isLoading && error == null && (
          <>
            {clips.length === 0 ? (
              <Box sx={{ py: 2 }}>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  No clips cut for this lecture yet.
                </Typography>
                {onCutClips && (
                  <Button size="small" variant="outlined" onClick={() => onCutClips(selectedId)}>
                    Cut Clips
                  </Button>
                )}
              </Box>
            ) : (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  {playable.length} playable
                  {failed.length > 0 && ` · ${failed.length} failed`}
                </Typography>

                {playing?.url && (
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                      {playing.concept_name}
                    </Typography>
                    <Box
                      sx={{
                        position: 'relative',
                        width: '100%',
                        pt: '56.25%',
                        borderRadius: 1,
                        overflow: 'hidden',
                        bgcolor: 'background.paper',
                      }}
                    >
                      {/* Keyed by clip id so switching clips remounts the element.
                          A src change alone can be swallowed by a browser that
                          considers the two URLs equivalent, which leaves the
                          previous clip playing under the new clip's name. */}
                      <video
                        key={playing.id}
                        controls
                        autoPlay
                        src={playing.url}
                        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
                      />
                    </Box>
                  </Box>
                )}

                <List dense disablePadding sx={{ maxHeight: 320, overflowY: 'auto' }}>
                  {playable.map((c) => (
                    <ListItemButton
                      key={c.id}
                      selected={c.id === playingId}
                      onClick={() => setPlayingId(c.id)}
                    >
                      <PlayCircleOutlineIcon sx={{ mr: 1.5, color: 'text.secondary' }} />
                      <ListItemText primary={c.concept_name} />
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`${formatClipTime(c.start_s)} – ${formatClipTime(c.end_s)}`}
                      />
                    </ListItemButton>
                  ))}
                  {failed.map((c) => (
                    <ListItemButton key={c.id} disabled sx={{ opacity: 0.6 }}>
                      <ListItemText
                        primary={c.concept_name}
                        secondary={c.error || 'This clip could not be cut.'}
                      />
                      <Chip size="small" color="error" label="failed" />
                    </ListItemButton>
                  ))}
                </List>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
