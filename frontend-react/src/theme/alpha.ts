/**
 * Token-sourced transparency.
 *
 * `rgba(255,255,255,0.06)` is a named colour just as much as a hex, so the
 * "no module names a colour" rule covers it. These two helpers are the only
 * sanctioned way to fade a token.
 *
 * `color-mix` rather than a computed `rgba()` because the second needs the
 * palette at runtime, which would mean a hook in every call site, and would
 * break the "the value comes from the token table" property: the alpha would be
 * baked at build time instead of read from `--lgc-*`.
 */

/** `tint('ok', 8)` -> an 8% wash of the `ok` token over whatever is behind it. */
export const tint = (token: string, percent = 20): string =>
  `color-mix(in srgb, var(--lgc-${token}) ${percent}%, transparent)`

/** The token itself, for `sx` values that need a string. */
export const token = (name: string): string => `var(--lgc-${name})`

/**
 * A two-stop gradient between tokens, e.g. the heatmap's
 * `info -> ok` for a healthy concept and `warn -> bad` for a struggling one.
 */
export const gradient = (from: string, to: string, angle = 90): string =>
  `linear-gradient(${angle}deg, var(--lgc-${from}), var(--lgc-${to}))`
