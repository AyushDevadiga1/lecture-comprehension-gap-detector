import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { NAV } from '../nav'

/**
 * Route-aware document title and focus management.
 *
 * P6 a11y pass per `revamp-plan/04-phases.md`. On every route change:
 *
 * 1. `document.title` is set from the nav table, so a screen-reader user hears
 *    the new page name and the browser tab matches the view.
 * 2. Focus moves to the `<main>` landmark's first heading (or the landmark
 *    itself), so a keyboard user lands at the start of the new content rather
 *    than at the top of the document.
 *
 * The hook reads only the router location — never job state — so it satisfies
 * §1: a route change re-renders the page once, and a job tick never does.
 */
export function useRouteFocus(mainRef: React.RefObject<HTMLElement | null>) {
  const { pathname } = useLocation()
  const prevPath = useRef(pathname)

  useEffect(() => {
    const nav = NAV.find((n) => n.to === pathname)
    const label = nav?.label ?? 'LecGap'
    document.title = `${label} · LecGap`

    if (prevPath.current !== pathname) {
      prevPath.current = pathname
      // Wait a tick so the new view has rendered before moving focus.
      requestAnimationFrame(() => {
        const main = mainRef.current
        if (!main) return
        const heading = main.querySelector<HTMLElement>('h1, h2, h3')
        const target = heading ?? main
        target.focus({ preventScroll: false })
        // jsdom has no layout engine, so `scrollIntoView` is undefined there.
        if (typeof target.scrollIntoView === 'function') {
          target.scrollIntoView({ block: 'start' })
        }
      })
    }
  }, [pathname, mainRef])
}
