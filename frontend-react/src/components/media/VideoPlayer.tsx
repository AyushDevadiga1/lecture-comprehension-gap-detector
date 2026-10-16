import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Button, IconButton, Tooltip, Typography } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'
import Replay10Icon from '@mui/icons-material/Replay10'
import Forward10Icon from '@mui/icons-material/Forward10'
import VolumeUpIcon from '@mui/icons-material/VolumeUp'
import VolumeOffIcon from '@mui/icons-material/VolumeOff'
import FullscreenIcon from '@mui/icons-material/Fullscreen'
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious'
import SkipNextIcon from '@mui/icons-material/SkipNext'
import ReplayIcon from '@mui/icons-material/Replay'
import { tint, token } from '../../theme/alpha'
import { formatClipTime } from '../../lib/format'

/**
 * The clip player.
 *
 * ## Why the browser's own controls were not enough
 *
 * `<video controls>` was doing all the work before this component, which meant
 * the lecture clip was at the mercy of a UI that cannot answer three questions
 * this product asks:
 *
 *   - **switching** — a clip is one file, so moving to the next one means
 *     swapping `src`; the native bar restarts, its position is lost and the
 *     keyboard shortcuts belong to the browser, not the page;
 *   - **orientation** — "which clip am I in, and what comes after it?" has no
 *     place in the native bar at all;
 *   - **failure** — a corrupt or never-written file (`ok = 0`, which the seed
 *     data and re-cut flows both produce) makes the native player show nothing
 *     but a dead rectangle, with no way to say what happened or to retry.
 *
 * So the transport is ours: play/pause, ±10s, a scrubbable timeline, volume,
 * 0.5×–2× speed, fullscreen, prev/next clip, and the shortcuts a keyboard user
 * expects (`Space`/`K`, `←`/`→`, `J`/`L`, `M`, `F`). Autoplay advances to the
 * next clip through `onEnded`, which is what makes a remediation list feel like
 * a playlist instead of twelve separate videos.
 *
 * ## Invariants
 *
 * - **No colour literals** (REACT_ARCHITECTURE §4): the scrim, the icons and
 *   the timeline fill are tokens. The scrim is `ink_dark` and the glyphs are
 *   `ink_light` — the pair `nodeColors` already keeps legible in *both* bases,
 *   so the controls stay readable over a bright lecture frame in light mode and
 *   over a dark one in dark mode.
 * - The element stays a plain `<video>` with `src` as an attribute, because
 *   `dashboard.live.test` asserts `video.getAttribute('src')` starts with the
 *   canonical `/media/clips/` prefix (ARCHITECTURE §3: never a stored path).
 * - Autoplay is attempted, never assumed: browsers reject it and a rejected
 *   promise is an unhandled-rejection failure, so the result is always caught.
 */

export interface VideoPlayerProps {
  src: string
  /** Clip title, shown over the stage. */
  title?: string
  /** e.g. "Clip 3 of 12" — orientation within the batch. */
  position?: string
  /** Source offsets of this clip within its lecture, for the header line. */
  rangeLabel?: string
  autoPlay?: boolean
  /** Fired when the clip finishes — the playlist uses it to auto-advance. */
  onEnded?: () => void
  onPrevious?: () => void
  onNext?: () => void
  hasNext?: boolean
  hasPrevious?: boolean
  /** Re-cut this clip, wired to `POST /lectures/{id}/clips`. */
  onRetry?: () => void
}

const SPEEDS = [0.5, 1, 1.25, 1.5, 2] as const

export const VideoPlayer: React.FC<VideoPlayerProps> = ({
  src,
  title,
  position,
  rangeLabel,
  autoPlay = true,
  onEnded,
  onPrevious,
  onNext,
  hasNext = false,
  hasPrevious = false,
  onRetry,
}) => {
  const stageRef = useRef<HTMLDivElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)
  const [rate, setRate] = useState<(typeof SPEEDS)[number]>(1)
  const [failed, setFailed] = useState<string | null>(null)

  // A new clip is a new file: every measurement belongs to the old one. Reset
  // before the element loads, or the first paint shows the previous clip's
  // duration against the new clip's zero-second position.
  useEffect(() => {
    setPlaying(false)
    setCurrent(0)
    setDuration(0)
    setFailed(null)
  }, [src])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.load()
    if (autoPlay) {
      // Autoplay policy can reject this (and jsdom never plays media). Catch it
      // so a refused autoplay surfaces as "paused", not an unhandled rejection.
      void video.play().catch(() => setPlaying(false))
    }
  }, [src, autoPlay])

  const toggle = useCallback(() => {
    const video = videoRef.current
    if (!video || failed) return
    if (video.paused) void video.play().catch(() => setPlaying(false))
    else video.pause()
  }, [failed])

  const seekBy = useCallback((delta: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.min(
      Math.max(0, video.currentTime + delta),
      Number.isFinite(video.duration) ? video.duration : delta,
    )
  }, [])

  const seekTo = useCallback((fraction: number) => {
    const video = videoRef.current
    if (!video || !Number.isFinite(video.duration)) return
    video.currentTime = fraction * video.duration
  }, [])

  const cycleSpeed = useCallback(() => {
    setRate((prev) => {
      const next = SPEEDS[(SPEEDS.indexOf(prev) + 1) % SPEEDS.length] ?? 1
      if (videoRef.current) videoRef.current.playbackRate = next
      return next
    })
  }, [])

  const toggleFullscreen = useCallback(() => {
    const stage = stageRef.current
    if (!stage) return
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined)
    else void stage.requestFullscreen?.().catch(() => undefined)
  }, [])

  /** Keyboard transport. `J`/`L` are the seek-10s pair editors expect. */
  const onKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement
    const inScrubber = target.tagName === 'INPUT'
    switch (e.key) {
      case ' ':
      case 'k':
      case 'K':
        e.preventDefault()
        toggle()
        break
      case 'ArrowLeft':
        if (inScrubber) return // let the range input own its own arrows
        e.preventDefault()
        seekBy(-5)
        break
      case 'ArrowRight':
        if (inScrubber) return
        e.preventDefault()
        seekBy(5)
        break
      case 'j':
      case 'J':
        e.preventDefault()
        seekBy(-10)
        break
      case 'l':
      case 'L':
        e.preventDefault()
        seekBy(10)
        break
      case 'm':
      case 'M':
        setMuted((v) => !v)
        break
      case 'f':
      case 'F':
        toggleFullscreen()
        break
      default:
        break
    }
  }

  const pct = duration > 0 ? (current / duration) * 100 : 0

  return (
    <Box
      ref={stageRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-label={title ? `Video player: ${title}` : 'Video player'}
      sx={{
        position: 'relative',
        width: '100%',
        pt: '56.25%',
        borderRadius: 2,
        overflow: 'hidden',
        // The stage is a screen: it reads as one in both bases.
        backgroundColor: 'background.default',
        border: '1px solid',
        borderColor: 'divider',
        outline: 'none',
        '&:focus-visible': { outline: '2px solid', outlineColor: 'info.main' },
      }}
    >
      <video
        ref={videoRef}
        key={src}
        src={src}
        preload="metadata"
        playsInline
        onError={() =>
          setFailed('This clip file could not be loaded — it may be missing or corrupt.')
        }
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onEnded={() => {
          setPlaying(false)
          onEnded?.()
        }}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      />

      {/* Failure state — the corrupted-clip case, said out loud. */}
      {failed && (
        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 1.5,
            px: 3,
            textAlign: 'center',
            backgroundColor: tint('ink_dark', 88),
          }}
        >
          <Typography variant="subtitle2" sx={{ color: token('ink_light'), fontWeight: 700 }}>
            Playback failed
          </Typography>
          <Typography variant="caption" sx={{ color: token('ink_light'), opacity: 0.85 }}>
            {failed}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
            <Button
              size="small"
              variant="outlined"
              onClick={() => {
                setFailed(null)
                videoRef.current?.load()
                void videoRef.current?.play().catch(() => undefined)
              }}
              sx={{ color: token('ink_light'), borderColor: token('ink_light') }}
            >
              Try again
            </Button>
            {onRetry && (
              <Button
                size="small"
                variant="contained"
                onClick={onRetry}
                sx={{ backgroundColor: 'secondary.main', color: 'secondary.contrastText' }}
              >
                Re-cut this clip
              </Button>
            )}
          </Box>
        </Box>
      )}

      {/* Center transport — the whole stage is a play/pause target. */}
      {!failed && !playing && (
        <Box
          onClick={toggle}
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            backgroundColor: tint('ink_dark', 35),
            transition: 'opacity 0.2s ease',
          }}
        >
          <Box
            sx={{
              width: 72,
              height: 72,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'secondary.main',
              color: 'secondary.contrastText',
              boxShadow: `0 8px 24px ${tint('ink_dark', 60)}`,
              transform: 'translateX(4px)',
            }}
          >
            <PlayArrowIcon sx={{ fontSize: 42 }} />
          </Box>
        </Box>
      )}

      {/* Clip identity, so a switched clip always says which one it is. */}
      {(title || position || rangeLabel) && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            px: 1.5,
            py: 1,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            gap: 1,
            background: `linear-gradient(180deg, ${tint('ink_dark', 80)}, transparent)`,
            pointerEvents: 'none',
          }}
        >
          <Typography
            variant="subtitle2"
            noWrap
            sx={{ color: token('ink_light'), fontWeight: 700, maxWidth: '60%' }}
          >
            {title}
          </Typography>
          <Typography variant="caption" sx={{ color: token('ink_light'), opacity: 0.85, whiteSpace: 'nowrap' }}>
            {rangeLabel}
            {rangeLabel && position ? ' · ' : ''}
            {position}
          </Typography>
        </Box>
      )}

      {/* Transport bar */}
      <Box
        sx={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          px: 1.5,
          pt: 1,
          pb: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: 0.75,
          background: `linear-gradient(0deg, ${tint('ink_dark', 92)}, ${tint('ink_dark', 70)} 70%, transparent)`,
        }}
      >
        <input
          type="range"
          min={0}
          max={1000}
          step={1}
          value={duration > 0 ? Math.round((current / duration) * 1000) : 0}
          onChange={(e) => seekTo(Number(e.target.value) / 1000)}
          aria-label="Seek"
          style={{
            width: '100%',
            appearance: 'none',
            height: 6,
            borderRadius: 3,
            cursor: 'pointer',
            background: `linear-gradient(90deg, ${token('accent')} ${pct}%, ${token('track')} ${pct}%)`,
          }}
          className="lgc-seek"
        />

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <IconButton
            size="small"
            aria-label={playing ? 'Pause' : 'Play'}
            onClick={toggle}
            sx={{ color: token('ink_light') }}
          >
            {playing ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
          </IconButton>
          <IconButton size="small" aria-label="Back 10 seconds" onClick={() => seekBy(-10)} sx={{ color: token('ink_light') }}>
            <Replay10Icon fontSize="small" />
          </IconButton>
          <IconButton size="small" aria-label="Forward 10 seconds" onClick={() => seekBy(10)} sx={{ color: token('ink_light') }}>
            <Forward10Icon fontSize="small" />
          </IconButton>

          <Typography
            variant="caption"
            sx={{ color: token('ink_light'), fontVariantNumeric: 'tabular-nums', ml: 0.5, minWidth: 88 }}
          >
            {formatClipTime(current)} / {formatClipTime(duration)}
          </Typography>

          <Box sx={{ flex: 1 }} />

          <Tooltip title="Playback speed">
            <Button
              size="small"
              onClick={cycleSpeed}
              aria-label={`Playback speed ${rate}x`}
              sx={{
                color: token('ink_light'),
                minWidth: 0,
                px: 1,
                fontSize: '0.72rem',
                fontWeight: 700,
                borderRadius: 1.5,
              }}
            >
              {rate}×
            </Button>
          </Tooltip>

          <IconButton
            size="small"
            aria-label={muted || volume === 0 ? 'Unmute' : 'Mute'}
            onClick={() => setMuted((v) => !v)}
            sx={{ color: token('ink_light') }}
          >
            {muted || volume === 0 ? <VolumeOffIcon fontSize="small" /> : <VolumeUpIcon fontSize="small" />}
          </IconButton>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            onChange={(e) => {
              const v = Number(e.target.value)
              setVolume(v)
              setMuted(v === 0)
              if (videoRef.current) {
                videoRef.current.volume = v
                videoRef.current.muted = v === 0
              }
            }}
            aria-label="Volume"
            style={{
              width: 64,
              appearance: 'none',
              height: 4,
              borderRadius: 2,
              cursor: 'pointer',
              background: `linear-gradient(90deg, ${token('ink_light')} ${(muted ? 0 : volume) * 100}%, ${token('track')} ${(muted ? 0 : volume) * 100}%)`,
            }}
            className="lgc-seek"
          />

          {hasPrevious && (
            <IconButton size="small" aria-label="Previous clip" onClick={onPrevious} sx={{ color: token('ink_light') }}>
              <SkipPreviousIcon fontSize="small" />
            </IconButton>
          )}
          {hasNext && (
            <IconButton size="small" aria-label="Next clip" onClick={onNext} sx={{ color: token('ink_light') }}>
              <SkipNextIcon fontSize="small" />
            </IconButton>
          )}
          <IconButton size="small" aria-label="Replay clip" onClick={() => seekTo(0)} sx={{ color: token('ink_light') }}>
            <ReplayIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" aria-label="Fullscreen" onClick={toggleFullscreen} sx={{ color: token('ink_light') }}>
            <FullscreenIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>
    </Box>
  )
}
