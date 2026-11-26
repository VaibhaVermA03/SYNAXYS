import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { AuthProvider } from './app/AuthProvider'
import { ThemeProvider } from './app/ThemeProvider'
import { ToastProvider } from './components/ui/Toast'
import { initMonitoring } from './lib/monitoring'
import './styles/index.css'

initMonitoring() // no-op unless VITE_SENTRY_DSN is set; never blocks rendering

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: (n, e) => n < 2 && (e?.status === undefined || e.status >= 500 || e.status === 0) } },
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <BrowserRouter>
            <AuthProvider><App /></AuthProvider>
          </BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
