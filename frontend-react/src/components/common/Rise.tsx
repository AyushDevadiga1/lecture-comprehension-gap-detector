import { motion } from 'framer-motion'
import { useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'

/**
 * One orchestrated page-load reveal.
 *
 * The aesthetic prompt's own recipe: a single staggered entrance is worth more
 * than scattered micro-interactions. Every child gets an index, and the
 * stagger is bounded (40 ms × index, capped at 160 ms) so a long list never
 * delays a later row by a second.
 *
 * Reduced motion is the contract, not a nicety: when the user has asked for
 * less motion, everything renders in its final state immediately. No
 * animation, no delay, no opacity dip.
 */
export function Rise({ children, index = 0, delay = 0 }: {
  children: React.ReactNode
  index?: number
  delay?: number
}) {
  const reduce = useReducedMotion()
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    if (!reduce) setMounted(true)
  }, [reduce])
  if (reduce) return <>{children}</>
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: mounted ? 1 : 0, y: mounted ? 0 : 10 }}
      transition={{ duration: 0.32, delay: delay + Math.min(index, 4) * 0.04, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}
