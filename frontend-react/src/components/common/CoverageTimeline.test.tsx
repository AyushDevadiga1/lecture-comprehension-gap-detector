import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import type { ConceptOut, SegmentOut } from '../../api/types'
import { renderWithProviders } from '../../test/render'
import { token } from '../../theme/alpha'
import { CoverageTimeline } from './CoverageTimeline'

/**
 * The render half of the P2.2 port. `lib/coverageTimeline.test.ts` pins the
 * numbers against goldens measured from the Python (`frontend/render.py::
 * lecture_html` on `main`); this file pins the *rendering* of those same
 * numbers: the drawing exists, its geometry attributes match the measured
 * fixture, band order is taught order at the DOM level, labels escape, and
 * the chrome stays on tokens (`var(--lgc-*)`) rather than gaining colours.
 */

const FIXTURE_TITLE = 'Coverage — "Golden" <Fixture> · x&y'

const FIXTURE_SEGMENTS: SegmentOut[] = [
  { idx: 0, start_s: 0, end_s: 8, text: 'Welcome. Today we trace the path from moments to variance.' },
  {
    idx: 1,
    start_s: 8,
    end_s: 20,
    text: 'The  expectation value  of position is the first moment of the wavefunction.\ttwo runs collapse here',
  },
  { idx: 2, start_s: 20, end_s: 28, text: 'expectation value' },
  {
    idx: 3,
    start_s: 28,
    end_s: 40,
    text: 'Note   the spacing:   whitespace runs collapse in the support sentence.',
  },
  {
    idx: 4,
    start_s: 40,
    end_s: 60,
    text: '  Kurtosis    measures the shape of the distribution tails: the fourth moment minus three, so a normal curve scores zero, and a heavy-tailed distribution scores large positive values, which is exactly what breaks the normal-approximation shortcut   ',
  },
]

const FIXTURE_CONCEPTS: ConceptOut[] = [
  { id: 1, name: 'Wavefunction', source: 'x', implicit: false, start_s: 10, end_s: 25 },
  { id: 2, name: 'EXPECTATION VALUE', source: 'x', implicit: false, start_s: 18, end_s: 32 },
  { id: 3, name: 'the spacing', source: 'x', implicit: false, start_s: 32, end_s: 40 },
  { id: 4, name: 'Gaps', source: 'x', implicit: false, start_s: 40, end_s: 45 },
  { id: 5, name: 'Kurtosis', source: 'x', implicit: false, start_s: 48, end_s: 51 },
  { id: 6, name: 'Touching tail', source: 'x', implicit: false, start_s: 51, end_s: 51 },
  { id: 7, name: 'Isolated zero', source: 'x', implicit: false, start_s: 56, end_s: 56 },
  {
    id: 8,
    name: 'Br<&>k "x"',
    source: 'x',
    implicit: false,
    start_s: 62,
    end_s: 'oops' as unknown as number,
  },
  { id: 9, name: 'No window', source: 'x', implicit: false },
]

const BAND_ORDER = [
  'Wavefunction',
  'EXPECTATION VALUE',
  'the spacing',
  'Gaps',
  'Kurtosis',
  'Touching tail',
  'Isolated zero',
  'No window',
] as const

describe('CoverageTimeline (render)', () => {
  it('renders the fixture with the measured svg and caption', () => {
    renderWithProviders(
      <CoverageTimeline segments={FIXTURE_SEGMENTS} concepts={FIXTURE_CONCEPTS} title={FIXTURE_TITLE} />,
    )

    // Header + caption, bytes as the Python printed them. The caption is
    // three text nodes around the bold span, so query by the bold element
    // and read the whole element's bytes off it.
    expect(screen.getByText(FIXTURE_TITLE)).toBeInTheDocument()
    const caption = screen.getByText('61% of the lecture covered')
    expect(caption.tagName).toBe('B')
    expect(caption.parentElement?.textContent).toBe(
      '9 concepts · 5 transcript segments · ' +
        '61% of the lecture covered by extracted concepts (38s of 62s).',
    )

    // The svg is the measured size (78 + 27 * 8 drawn bands) and role-named.
    const svg = screen.getByRole('img', { name: 'Lecture coverage timeline' })
    expect(svg).toBeInTheDocument()
    expect(svg.getAttribute('height')).toBe('294')
    expect(svg.getAttribute('viewBox')).toBe('0 0 1000 294')

    // 1 track + 5 transcript ticks + 4 merged runs + 8 bands = 18 rects.
    const rects = svg.querySelectorAll('rect')
    expect(rects).toHaveLength(18)

    // 8 band labels + 2 axis labels, in DOCUMENT order: taught order is
    // visible in the DOM, not just in the model.
    const texts = [...svg.querySelectorAll('text')].map((t) => t.textContent)
    expect(texts).toHaveLength(10)
    expect(texts.slice(0, 8)).toEqual([...BAND_ORDER])
    expect(texts.slice(8)).toEqual(['0s', '62s'])
  })

  it('draws one covered rect per merged run, titled like the Python', () => {
    renderWithProviders(
      <CoverageTimeline segments={FIXTURE_SEGMENTS} concepts={FIXTURE_CONCEPTS} title={FIXTURE_TITLE} />,
    )
    const svg = screen.getByRole('img', { name: 'Lecture coverage timeline' })
    const titled = [...svg.querySelectorAll('rect')].filter((r) => r.getAttribute('rx') === '2')
    expect(titled).toHaveLength(4) // exactly the covered runs (bands rx=3, ticks have no rx)
    const runTitles = titled.map((r) => r.querySelector('title')?.textContent)
    expect(runTitles).toEqual([
      'covered: 0.0s\u20130.0s',
      'covered: 10.0s\u201345.0s',
      'covered: 48.0s\u201351.0s',
      'covered: 56.0s\u201356.0s',
    ])
  })

  it('escapes labels: the hostile name is text, never markup', () => {
    renderWithProviders(
      <CoverageTimeline segments={FIXTURE_SEGMENTS} concepts={FIXTURE_CONCEPTS} title={FIXTURE_TITLE} />,
    )
    // The unparsable concept draws no band — its escaping is exercised in the
    // one place it appears, the table row. The text survives raw: no &lt;/&amp;
    // double-escape, no attribute injection, no markup elements.
    const hit = screen.getByText('Br<&>k "x"')
    expect(hit.tagName).toBe('TD')
    // The caption's bold is the only <b> in the document.
    expect(document.querySelectorAll('b')).toHaveLength(1)
    expect(document.querySelectorAll('td b')).toHaveLength(0)
  })

  it('renders the evidence table with header and every concept row', () => {
    renderWithProviders(
      <CoverageTimeline segments={FIXTURE_SEGMENTS} concepts={FIXTURE_CONCEPTS} title={FIXTURE_TITLE} />,
    )
    const header = screen
      .getByText('Concept')
      .closest('tr')
    expect(header?.textContent).toBe(
      '#ConceptWindowQuiz-answer evidence (spoken sentence)',
    )
    const body = header?.closest('table')?.querySelectorAll('tbody tr')
    expect(body).toHaveLength(9)

    const firstRow = body?.[0]?.querySelectorAll('td')
    expect([...(firstRow ?? [])].map((td) => td.textContent)).toEqual([
      '1',
      'Wavefunction',
      '10.0 \u2013 25.0s',
      'The expectation value of position is the first moment of the wavefunction. two runs collapse here',
    ])
    // Skipped/unmatched concepts read as em dashes, not blanks.
    const gapsRow = body?.[3]?.querySelectorAll('td')
    expect([...(gapsRow ?? [])].map((td) => td.textContent)).toEqual([
      '4',
      'Gaps',
      '40.0 \u2013 45.0s',
      '\u2014',
    ])
    const brokenRow = body?.[7]?.querySelectorAll('td')
    expect([...(brokenRow ?? [])].map((td) => td.textContent)).toEqual([
      '8',
      'Br<&>k "x"',
      '\u2014',
      '\u2014',
    ])
  })

  it('keeps chrome on tokens: track, tick and run fills are var(--lgc-*)', () => {
    renderWithProviders(
      <CoverageTimeline segments={FIXTURE_SEGMENTS} concepts={FIXTURE_CONCEPTS} title={FIXTURE_TITLE} />,
    )
    const svg = screen.getByRole('img', { name: 'Lecture coverage timeline' })
    const rects = [...svg.querySelectorAll('rect')]
    expect(rects[0]?.getAttribute('fill')).toBe(token('track'))
    // Ticks and covered runs: every rect except the band fills (resolved hex)
    // reads straight from the token table.
    expect(rects[1]?.getAttribute('fill')).toBe(token('tick'))
    expect(rects[6]?.getAttribute('fill')).toBe(token('covered'))
    // Body text renders through the app palette too.
    expect(screen.getByText('0s').getAttribute('fill')).toBe(token('muted'))
  })

  it('handles the empty payload like the measured empty render', () => {
    renderWithProviders(<CoverageTimeline />)
    const caption = screen.getByText('0% of the lecture covered')
    expect(caption.parentElement?.textContent).toBe(
      '0 concepts · 0 transcript segments · ' +
        '0% of the lecture covered by extracted concepts (0s of 1s).',
    )
    const svg = screen.getByRole('img', { name: 'Lecture coverage timeline' })
    expect(svg.getAttribute('height')).toBe('78')
    expect(svg.querySelectorAll('rect')).toHaveLength(1) // the track only
    expect(document.querySelectorAll('tbody tr')).toHaveLength(0)
  })
})
