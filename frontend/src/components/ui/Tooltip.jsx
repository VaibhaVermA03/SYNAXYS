import { cn } from '../../lib/utils'

/** Hover/focus tooltip shown BELOW its child. Desktop only (hidden under 768px). Decorative: the child keeps its own aria-label. */
export default function Tooltip({ label, align = 'center', children, className }) {
  return (
    <span className={cn('group relative inline-flex', className)}>
      {children}
      <span
        aria-hidden="true"
        className={cn('pointer-events-none absolute top-full z-50 mt-2 hidden whitespace-nowrap rounded-lg bg-fg px-2.5 py-1.5 text-xs text-bg opacity-0 shadow-lg transition-opacity duration-150 md:block',
          'group-hover:opacity-100 group-hover:delay-300 group-focus-within:opacity-100', align === 'end' ? 'right-0' : 'left-1/2 -translate-x-1/2')}
      >
        {label}
      </span>
    </span>
  )
}
