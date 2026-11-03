import { useState } from 'react'
import { cn } from '../../lib/utils'

const SIZES = { sm: ['h-5', 'text-base'], md: ['h-7', 'text-xl'], lg: ['h-9', 'text-3xl'] }
// Geist Pixel has a single weight, so "bold" is done with a thin outline in the text colour (raise/lower 0.035em to taste).
const BOLD = '[-webkit-text-stroke:0.035em_currentColor]'

/** Your logo (public/brand/synaxys-logo.svg, black artwork) + the wordmark in Geist Pixel Circle.
 *  In dark mode the black logo is inverted so it stays visible. If the SVG is missing only the wordmark is shown. */
export default function Logo({ size = 'md', showText = true, className }) {
  const [missing, setMissing] = useState(false)
  const [img, text] = SIZES[size] || SIZES.md
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      {!missing && (
        <img src="/brand/synaxys-logo.svg" alt={showText ? '' : 'SYNAXYS'} className={cn(img, 'w-auto shrink-0 dark:invert')} onError={() => setMissing(true)} />
      )}
      {(showText || missing) && <span className={cn('font-pixel leading-none tracking-wide', BOLD, text)}>SYNAXYS</span>}
    </span>
  )
}
