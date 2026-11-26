import { Link } from 'react-router-dom'
import { Select } from '../ui'
import { useAuth } from '../../app/AuthProvider'
import { useWorkspace } from '../../app/WorkspaceProvider'

export default function WorkspaceSwitcher() {
  const { user } = useAuth()
  const { workspaces, active, setActive } = useWorkspace()
  if (!active) return <span className="hidden text-xs text-muted md:inline">Workspace: <span className="font-medium text-fg">{user?.login}</span></span>
  return (
    <div className="hidden items-center gap-2 md:flex">
      <Select ariaLabel="Workspace" className="w-48" value={String(active.id)} onChange={(v) => setActive(Number(v))} options={workspaces.map((w) => ({ value: String(w.id), label: w.name }))} />
      <Link to="/app/settings/workspaces" className="text-xs text-accent-ink hover:underline">Manage</Link>
    </div>
  )
}
