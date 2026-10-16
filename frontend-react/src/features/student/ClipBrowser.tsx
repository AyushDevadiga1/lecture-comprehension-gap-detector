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
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious'
import SkipNextIcon from '@mui/icons-material/SkipNext'
import ContentCutIcon from '@mui/icons-material/ContentCut'
import { useQuery } from '@tanstack/react-query'
import { lectures as lecturesApi } from '../../api/lectures'
import type { LectureOut } from '../../api/types'
import { queryKeys } from '../../lib/queryKeys'
import { formatClipTime } from '../../lib/format'
import { VideoPlayer } from '../../components/media/VideoPlayer'
import { tint } from '../../theme/alpha'

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
 * ## What the second pass changed, and why
 *
 * The first version put the browser's native controls on a bare `<video>` and
 * a plain list beside it. Three things made that feel broken in use:
 *
 *   - **switching** — selecting another clip swapped `src` under a control bar
 *     that kept the old position and state, so clips appeared not to switch;
 *   - **controls** — the native bar gives no prev/next, no speed, no shortcuts
 *     and no way to say which clip of how many is playing;
 *   - **corruption** — a clip whose ffmpeg cut never wrote a usable file
 *     (`ok = false`) rendered as a dead rectangle with no explanation and no
 *     way back. The user-facing fix for a bad batch is to re-cut it, so the
 *     failure now carries the button that queues exactly that.
 *
 * The player is `VideoPlayer` (transport, scrubber, speed, shortcuts,
 * auto-advance), the list is a playlist with a highlighted current row, and
 * every failure row offers "Re-cut clip" through `onCutClips`.
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

  // Which clip of how many — the orientation the native controls never had.
  const position = useMemo(() => {
    if (playingId == null) return null
    const index = playable.findIndex((c) => c.id === playingId)
    return index < 0 ? null : { index, total: playable.length }
  }, [playable, playingId])

  const goTo = (delta: number) => {
    if (position == null) return
    const next = playable[position.index + delta]
    if (next) setPlayingId(next.id)
  }

  const rangeLabel = playing ? `${formatClipTime(playing.start_s)} – ${formatClipTime(playing.end_s)}` : undefined

  return (
    <Card>
      <CardContent sx={{ p: 3 }}>
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
              <Box
                sx={{
                  py: 4,
                  px: 2,
                  textAlign: 'center',
                  borderRadius: 2,
                  border: '1px dashed',
                  borderColor: 'divider',
                  backgroundColor: tint('text', 3),
                }}
              >
                <ContentCutIcon sx={{ color: 'text.disabled', fontSize: 32, mb: 1 }} />
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  No clips cut for this lecture yet.
                </Typography>
                {onCutClips && (
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<ContentCutIcon />}
                    onClick={() => onCutClips(selectedId)}
                  >
                    Cut Clips
                  </Button>
                )}
              </Box>
            ) : (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {playable.length} playable
                  {failed.length > 0 && ` · ${failed.length} failed`}
                </Typography>

                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1.7fr) minmax(0, 1fr)' },
                    gap: 3,
                    alignItems: 'start',
                  }}
                >
                  {/* Stage + transport. Keyed inside the player by src, so a
                      switch is always a fresh element, never a reused one. */}
                  <Box>
                    {playing?.url ? (
                      <>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                          <Button
                            size="small"
                            startIcon={<SkipPreviousIcon />}
                            disabled={!position || position.index <= 0}
                            onClick={() => goTo(-1)}
                          >
                            Previous
                          </Button>
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            {position ? `Clip ${position.index + 1} of ${position.total}` : ''}
                          </Typography>
                          <Button
                            size="small"
                            endIcon={<SkipNextIcon />}
                            disabled={!position || position.index >= (position.total ?? 0) - 1}
                            onClick={() => goTo(1)}
                          >
                            Next
                          </Button>
                        </Box>
                        <VideoPlayer
                          src={playing.url}
                          title={playing.concept_name}
                          rangeLabel={rangeLabel}
                          position={position ? `Clip ${position.index + 1} of ${position.total}` : undefined}
                          autoPlay
                          hasPrevious={!!position && position.index > 0}
                          hasNext={!!position && position.index < position.total - 1}
                          onPrevious={() => goTo(-1)}
                          onNext={() => goTo(1)}
                          onEnded={() => goTo(1)}
                          onRetry={onCutClips ? () => onCutClips(selectedId) : undefined}
                        />
                      </>
                    ) : (
                      <Box
                        sx={{
                          position: 'relative',
                          width: '100%',
                          pt: '56.25%',
                          borderRadius: 2,
                          border: '1px dashed',
                          borderColor: 'divider',
                          backgroundColor: tint('text', 3),
                        }}
                      >
                        <Box
                          sx={{
                            position: 'absolute',
                            inset: 0,
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 1,
                            textAlign: 'center',
                            px: 2,
                          }}
                        >
                          <PlayCircleOutlineIcon sx={{ fontSize: 40, color: 'text.disabled' }} />
                          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                            Pick a clip from the list to play it here.
                          </Typography>
                          <Typography variant="caption" sx={{ color: 'text.disabled' }}>
                            Space plays/pauses · ←/→ seek · J/L skip 10s · F fullscreen
                          </Typography>
                        </Box>
                      </Box>
                    )}
                  </Box>

                  {/* Playlist */}
                  <List dense disablePadding sx={{ maxHeight: 360, overflowY: 'auto' }}>
                    {playable.map((c, i) => (
                      <ListItemButton
                        key={c.id}
                        selected={c.id === playingId}
                        onClick={() => setPlayingId(c.id)}
                        sx={{
                          borderRadius: 1.5,
                          mb: 0.5,
                          border: '1px solid',
                          borderColor: 'transparent',
                          '&.Mui-selected': {
                            backgroundColor: tint('info', 14),
                            borderColor: tint('info', 45),
                          },
                        }}
                      >
                        <Box
                          sx={{
                            width: 24,
                            height: 24,
                            borderRadius: '50%',
                            flexShrink: 0,
                            mr: 1.25,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.7rem',
                            fontWeight: 800,
                            backgroundColor: 'text.disabled',
                            color: 'background.paper',
                            ...(c.id === playingId
                              ? { backgroundColor: 'info.main', color: 'info.contrastText' }
                              : {}),
                          }}
                        >
                          {i + 1}
                        </Box>
                        <PlayCircleOutlineIcon
                          sx={{
                            mr: 1,
                            fontSize: 20,
                            color: c.id === playingId ? 'info.main' : 'text.secondary',
                          }}
                        />
                        <ListItemText
                          primary={c.concept_name}
                          primaryTypographyProps={{ sx: { fontWeight: 600, fontSize: '0.9rem' } }}
                        />
                        <Chip
                          size="small"
                          variant={c.id === playingId ? 'filled' : 'outlined'}
                          color={c.id === playingId ? 'info' : 'default'}
                          label={`${formatClipTime(c.start_s)} – ${formatClipTime(c.end_s)}`}
                          sx={{ ml: 1, fontVariantNumeric: 'tabular-nums' }}
                        />
                      </ListItemButton>
                    ))}

                    {failed.length > 0 && (
                      <Box sx={{ mt: 1.5 }}>
                        <Typography
                          variant="caption"
                          sx={{ color: 'error.main', fontWeight: 700, display: 'block', mb: 0.5, px: 1 }}
                        >
                          {failed.length} clip{failed.length === 1 ? '' : 's'} failed to cut
                        </Typography>
                        {failed.map((c) => (
                          <Box
                            key={c.id}
                            sx={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 1,
                              py: 0.75,
                              px: 1,
                              mb: 0.5,
                              borderRadius: 1.5,
                              border: '1px solid',
                              borderColor: 'divider',
                              backgroundColor: tint('bad', 8),
                            }}
                          >
                            <ListItemText
                              primary={c.concept_name}
                              secondary={c.error || 'This clip could not be cut.'}
                              primaryTypographyProps={{ sx: { fontWeight: 600, fontSize: '0.88rem' } }}
                              secondaryTypographyProps={{ sx: { fontSize: '0.75rem' } }}
                            />
                            {onCutClips && (
                              <Button
                                size="small"
                                variant="outlined"
                                color="error"
                                startIcon={<ContentCutIcon />}
                                onClick={() => onCutClips(selectedId)}
                                sx={{ flexShrink: 0 }}
                              >
                                Re-cut
                              </Button>
                            )}
                          </Box>
                        ))}
                      </Box>
                    )}
                  </List>
                </Box>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
