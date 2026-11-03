import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'
import { cn } from '../../lib/utils'

const ToastContext = createContext({ toast: () => {} })
const ICON = { success: CheckCircle2, error: AlertTriangle, info: Info }
const TONE = { success: 'text-ok', error: 'text-danger', info: 'text-accent-ink' }

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const id = useRef(0)
  const dismiss = useCallback((i) => setItems((xs) => xs.filter((x) => x.id !== i)), [])
  const toast = useCallback((message, type = 'info') => {
    const i = ++id.current
    setItems((xs) => [...xs, { id: i, message, type }])
    setTimeout(() => dismiss(i), 6000)
  }, [dismiss])
  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => {
          const Icon = ICON[t.type] || Info
          return (
            <div key={t.id} className="flex items-start gap-2 rounded-lg border border-border bg-surface p-3 text-sm shadow-lg">
              <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', TONE[t.type])} aria-hidden />
              <p className="flex-1">{t.message}</p>
              <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="text-muted hover:text-fg"><X className="h-4 w-4" /></button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
