import { describe, expect, it } from 'vitest'

/**
 * REACT_ARCHITECTURE.md §3: "No filesystem paths in the frontend... the React
 * client has no path→URL mapper at all, and a payload containing a filesystem
 * path is a *contract test failure*, not a runtime surprise."
 *
 * `lib/media.ts` was exactly that mapper — a faithful port of
 * `frontend/client.py::media_url`, reconstructing `/media/clips/{id}/{file}`
 * out of a stored `Clip.path`. It is deleted. These guards stop it coming back,
 * and stop the types file from re-asserting that a `path` is a path.
 */

const sources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** `import.meta.glob` keys a file in the importing directory as `./name`, so a
 * same-directory lookup has to match on the basename. */
const code = (suffix: string) => {
  const entries = Object.entries(sources)
  const hit =
    entries.find(([k]) => k.endsWith(suffix)) ??
    entries.find(([k]) => k.replace(/^\.\//, '').split('/').pop() === suffix)
  return hit ? hit[1] : ''
}
const allFiles = () => Object.keys(sources).filter((f) => !f.includes('.test.'))

describe('the React client has no path→URL mapper', () => {
  it('there are files to check', () => {
    expect(allFiles().length).toBeGreaterThan(0)
  })

  it('lib/media.ts is gone', () => {
    expect(code('lib/media.ts')).toBe('')
  })

  for (const file of allFiles()) {
    it(`${file} does not reconstruct a media URL`, () => {
      const src = code(file)
      // The one legitimate construction is the backend; on the client, building
      // `/media/clips/...` by hand means a path is still arriving in a payload.
      expect(src, `${file} hand-builds a media URL`).not.toMatch(/\/media\/clips\/\$\{/)
      expect(src, `${file} mentions data/processed`).not.toMatch(/data[\\/]processed/)
    })
  }
})

describe('the types file tells the truth', () => {
  const types = code('types.ts')

  it('the lookup found the file', () => {
    expect(types).not.toBe('')
  })

  it('does not claim to be generated when nothing generates it', () => {
    // An earlier version of this header said "generated from
    // backend/api/schemas.py... drift fails the OpenAPI snapshot test", and
    // neither a generator nor that test existed.
    expect(types).not.toMatch(/^\s*\*\s*API type definitions — generated/m)
    expect(types).toMatch(/hand-written/)
  })

  it('marks clip as an alias, not a filesystem path', () => {
    expect(types).toMatch(/@deprecated Use `clip_url`/)
    expect(types).not.toMatch(/@deprecated[^}]*filesystem path/)
  })
})
