import { useEffect, useState } from 'react'

const supported = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

/** Reactive CSS media query. Returns false where matchMedia does not exist (e.g. jsdom). */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => (supported() ? window.matchMedia(query).matches : false))
  useEffect(() => {
    if (!supported()) return undefined
    const mq = window.matchMedia(query)
    const onChange = () => setMatches(mq.matches)
    onChange()
    if (mq.addEventListener) mq.addEventListener('change', onChange)
    else mq.addListener(onChange)
    return () => { if (mq.removeEventListener) mq.removeEventListener('change', onChange); else mq.removeListener(onChange) }
  }, [query])
  return matches
}
