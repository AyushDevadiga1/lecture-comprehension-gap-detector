/**
 * Resolves a clip path or URL to the canonical Range-capable media endpoint URL:
 * /media/clips/{lecture_id}/{encodeURIComponent(filename)}
 */
export function resolveClipUrl(pathOrUrl?: string | null): string | null {
  if (!pathOrUrl) return null

  // If already a media URL
  if (pathOrUrl.startsWith('/media/')) {
    return pathOrUrl
  }

  // Parse path like data/processed/clips/3/foo.mp4 or clips/3/foo.mp4
  const normalised = pathOrUrl.replace(/\\/g, '/')
  const parts = normalised.split('/').filter(Boolean)

  if (parts.length >= 2) {
    const filename = parts[parts.length - 1]
    const lectureIdStr = parts[parts.length - 2]
    const lectureId = parseInt(lectureIdStr, 10)

    if (!isNaN(lectureId)) {
      return `/media/clips/${lectureId}/${encodeURIComponent(filename)}`
    }
  }

  // Fallback: if it's just a filename or other format
  return pathOrUrl
}
