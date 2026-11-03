import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, FolderGit2, Info, Search } from 'lucide-react'
import { Badge, Button, Card, EmptyState, ErrorState, Input, Select, Skeleton } from '../../components/ui'
import { describeError } from '../../lib/api'
import { githubService, searchService } from '../../services'

const LANGS = ['python', 'javascript', 'typescript', 'java', 'go', 'rust', 'ruby', 'php', 'csharp', 'kotlin', 'sql', 'shell']
const lines = (h) => (h.start_line ? (h.end_line && h.end_line !== h.start_line ? `${h.start_line}–${h.end_line}` : `${h.start_line}`) : null)

export default function CodeSearchPage() {
  const [query, setQuery] = useState('')
  const [repo, setRepo] = useState('')
  const [language, setLanguage] = useState('')
  const repos = useQuery({ queryKey: ['repositories', 'search-scope'], queryFn: () => githubService.repositories({ page_size: 100 }) })
  const indexed = (repos.data?.items || []).filter((r) => r.is_enabled && r.index_status === 'indexed')
  const search = useMutation({ mutationFn: searchService.query })
  const submit = (e) => {
    e.preventDefault()
    if (query.trim().length < 2) return
    search.mutate({ query: query.trim(), repository_id: repo ? Number(repo) : null, language: language || null, top_k: 10 })
  }

  if (repos.isSuccess && indexed.length === 0) {
    return (
      <Card>
        <EmptyState icon={FolderGit2} title="No indexed repositories yet"
          description="Connect a repository and run “Index code” on the Repositories page. Search only covers repositories you can access that have finished indexing."
          action={<Link to="/app/repositories"><Button>Go to repositories</Button></Link>} />
      </Card>
    )
  }
  const data = search.data
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2" role="search">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
          <Input className="pl-9" placeholder="Describe what you are looking for, e.g. “where do we validate webhook signatures”" aria-label="Search query" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={500} />
        </div>
        <Select ariaLabel="Repository" className="sm:w-60" value={repo} onChange={setRepo}
          options={[{ value: '', label: 'All indexed repositories' }, ...indexed.map((r) => ({ value: String(r.id), label: r.full_name }))]} />
        <Select ariaLabel="Language" className="sm:w-44" value={language} onChange={setLanguage}
          options={[{ value: '', label: 'Any language' }, ...LANGS.map((l) => ({ value: l, label: l }))]} />
        <Button type="submit" loading={search.isPending} disabled={query.trim().length < 2}>Search</Button>
      </form>
      <p className="text-xs text-muted">Searches the default branch of repositories you can access, as of their last indexing.</p>

      {search.isPending && <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div>}
      {search.isError && <Card><ErrorState message={describeError(search.error)} onRetry={() => search.mutate(search.variables)} /></Card>}
      {data?.note && <p role="status" className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm"><Info className="h-4 w-4 shrink-0" aria-hidden />{data.note}</p>}
      {data && data.results.length === 0 && <Card><EmptyState title="No matches" description={data.searched_repositories.length ? `Nothing relevant found in ${data.searched_repositories.join(', ')}. Try different words.` : 'There are no indexed repositories to search.'} /></Card>}
      {data && data.results.length > 0 && (
        <>
          <p className="text-xs text-muted">{data.results.length} result(s) from {data.searched_repositories.join(', ')} · {data.backend}</p>
          <ul className="space-y-3">
            {data.results.map((h) => (
              <li key={h.id}>
                <Card className="p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono font-medium">{h.path}{lines(h) ? `:${lines(h)}` : ''}</span>
                    <Badge>{h.repository}</Badge>{h.language && <Badge>{h.language}</Badge>}<Badge tone="accent">score {h.score.toFixed(2)}</Badge>
                    {h.github_url && <a href={h.github_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-accent-ink hover:underline">Open on GitHub<ExternalLink className="h-3 w-3" aria-hidden /></a>}
                  </div>
                  <pre className="mt-2 max-h-60 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-xs whitespace-pre-wrap">{h.snippet}</pre>
                  <p className="mt-2 text-xs text-muted">{h.explanation}</p>
                </Card>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
