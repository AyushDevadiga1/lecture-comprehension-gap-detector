import React from 'react'
import { motion, useReducedMotion } from 'framer-motion'

/**
 * Entrance animation for a block: fade up once, then get out of the way.
 *
 * Shared by both dashboards so the page's rhythm is one decision rather than
 * two similar ones that drift — a card on the student page and a card on the
 * faculty page should arrive the same way.
 *
 * `useReducedMotion` is the contract, not a nicety: a user who has asked the
 * system for less motion gets the final state immediately, with no transform
 * at all (`initial={false}` skips the animation entirely rather than playing a
 * shorter one).
 *
 * `height: 100%` is load-bearing — it is what lets a card wrapped inside a
 * `Grid item` keep the row alignment it had before it was wrapped.
 */
export const Rise: React.FC<{
  delay?: number
  y?: number
  children: React.ReactNode
}> = ({ delay = 0, y = 18, children }) => {
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: 'easeOut' }}
      style={{ height: '100%' }}
    >
      {children}
    </motion.div>
  )
}
