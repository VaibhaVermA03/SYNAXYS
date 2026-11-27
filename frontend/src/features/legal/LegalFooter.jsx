import { Link } from 'react-router-dom'
import { cn } from '../../lib/utils'

export const LEGAL_LINKS = [['/legal/privacy', 'Privacy Policy'], ['/legal/terms', 'Terms of Service'], ['/legal/security', 'Security'], ['/legal/license', 'Licence']]

export default function LegalFooter({ className }) {
  return (
    <footer className={cn('text-xs text-muted', className)}>
      <nav aria-label="Legal" className="flex flex-wrap gap-x-4 gap-y-1">
        {LEGAL_LINKS.map(([to, label]) => <Link key={to} to={to} className="hover:text-fg hover:underline">{label}</Link>)}
      </nav>
    </footer>
  )
}
