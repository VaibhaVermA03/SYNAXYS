import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { notificationService } from '../../services'

// Polling (30 s) is enough here: no extra infrastructure, and it stops while the tab is hidden (react-query default).
export default function NotificationBell() {
  const q = useQuery({ queryKey: ['notifications-unread'], queryFn: notificationService.unread, refetchInterval: 30_000, retry: false })
  const n = q.data?.unread ?? 0
  return (
    <Link to="/app/notifications" aria-label={n ? `Notifications, ${n} unread` : 'Notifications'} className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg">
      <Bell className="h-4 w-4" aria-hidden />
      {n > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] font-medium leading-4 text-white">{n > 99 ? '99+' : n}</span>}
    </Link>
  )
}
