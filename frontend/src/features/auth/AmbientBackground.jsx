import { cn } from '../../lib/utils'

/** Decorative animated backdrop: dotted pixel grid + two slow, blurred colour blobs. Purely visual (aria-hidden), theme-aware. */
export default function AmbientBackground({ className }) {
  return (
    <div aria-hidden="true" className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}>
      <div className="pixel-grid absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />
      <div className="absolute -left-24 top-8 h-72 w-72 animate-blob rounded-full bg-accent/25 blur-3xl" />
      <div className="absolute -right-24 bottom-8 h-80 w-80 animate-blob rounded-full bg-fg/10 blur-3xl [animation-delay:-8s]" />
    </div>
  )
}
