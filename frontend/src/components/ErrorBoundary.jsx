import { Component } from 'react'

// Last line of defence against a render crash: show a recoverable message instead of a blank page.
export default class ErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error, info) { console.error('UI error', error, info?.componentStack) } // eslint-disable-line no-console
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <h1 className="text-lg font-semibold">Something went wrong</h1>
        <p className="max-w-md text-sm text-muted">The page hit an unexpected error. Your data is safe. Reload to continue; if it keeps happening, contact your administrator.</p>
        <button className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-fg" onClick={() => window.location.reload()}>Reload</button>
      </div>
    )
  }
}
