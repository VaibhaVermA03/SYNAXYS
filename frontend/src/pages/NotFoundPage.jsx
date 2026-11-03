import { Link } from 'react-router-dom'
import { Card, EmptyState, Button } from '../components/ui'

export default function NotFoundPage() {
  return (
    <Card>
      <EmptyState title="Page not found" description="The page you are looking for does not exist or you do not have access to it."
        action={<Link to="/app/dashboard"><Button>Back to the dashboard</Button></Link>} />
    </Card>
  )
}
