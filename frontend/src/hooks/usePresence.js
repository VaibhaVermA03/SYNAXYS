import { useEffect, useState } from 'react'

/** Keeps an element mounted long enough to play its exit animation.
 *  mounted: render it; shown: apply the "visible" classes (flips a tick after mount, and before unmount). */
export function usePresence(open, ms = 180) {
  const [mounted, setMounted] = useState(open)
  const [shown, setShown] = useState(open)
  useEffect(() => {
    let t
    if (open) { setMounted(true); t = setTimeout(() => setShown(true), 15) }
    else { setShown(false); t = setTimeout(() => setMounted(false), ms) }
    return () => clearTimeout(t)
  }, [open, ms])
  return { mounted, shown }
}
