import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { setActiveWorkspaceId } from '../lib/api'
import { workspaceService } from '../services'

const KEY = 'synaxys-workspace'
const Ctx = createContext({ workspaces: [], active: null, setActive: () => {}, isLoading: false })

const readStored = () => { try { return Number(localStorage.getItem(KEY)) || null } catch { return null } }  // only a workspace id, never auth data

export function WorkspaceProvider({ children }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['workspaces'], queryFn: workspaceService.list, retry: false, staleTime: 60_000 })
  const [chosen, setChosen] = useState(readStored)
  const list = useMemo(() => q.data || [], [q.data])
  // A stored id the user no longer belongs to (removed, deleted) silently falls back to the first workspace.
  const active = list.find((w) => w.id === chosen) || list[0] || null
  useEffect(() => { setActiveWorkspaceId(active?.id ?? null) }, [active?.id])
  const setActive = useCallback((id) => {
    setActiveWorkspaceId(id)
    try { localStorage.setItem(KEY, String(id)) } catch { /* private mode */ }
    setChosen(id)
    qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'me' && x.queryKey[0] !== 'workspaces' }) // everything workspace-scoped reloads
  }, [qc])
  const value = useMemo(() => ({ workspaces: list, active, setActive, isLoading: q.isPending }), [list, active, setActive, q.isPending])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useWorkspace = () => useContext(Ctx)
