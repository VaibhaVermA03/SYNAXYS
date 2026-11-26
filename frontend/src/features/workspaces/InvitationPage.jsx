import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Card } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { useWorkspace } from '../../app/WorkspaceProvider'
import { workspaceService } from '../../services'

// /app/invitations/<token>: only the invited GitHub user can accept (the backend checks the signed-in login; anybody else gets "not found").
export default function InvitationPage() {
  const { token } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { toast } = useToast()
  const { setActive } = useWorkspace()
  const accept = useMutation({
    mutationFn: () => workspaceService.accept(token),
    onSuccess: async (ws) => { toast(`You joined ${ws.name}.`, 'success'); await qc.invalidateQueries({ queryKey: ['workspaces'] }); setActive(ws.id); navigate('/app/settings/workspaces') },
  })
  return (
    <Card className="mx-auto max-w-md space-y-4 p-6 text-sm">
      <h2 className="font-pixel text-xl">Workspace invitation</h2>
      <p className="text-muted">Accept this invitation to join the workspace with the GitHub account you are signed in with. The invitation only works for the GitHub user it was sent to.</p>
      {accept.isError && <p role="alert" className="text-danger">{describeError(accept.error)}</p>}
      <div className="flex gap-2">
        <Button loading={accept.isPending} onClick={() => accept.mutate()}>Accept invitation</Button>
        <Link to="/app/settings/workspaces"><Button variant="ghost">Not now</Button></Link>
      </div>
    </Card>
  )
}
