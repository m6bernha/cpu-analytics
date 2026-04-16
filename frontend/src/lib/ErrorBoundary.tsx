// Simple error boundary that catches render-phase crashes in its subtree.
// Without this, a single malformed API response or unexpected null can
// white-screen the whole app. With it, the offending tab shows a
// recoverable error message while the rest of the shell keeps working.

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

type Props = {
  children: ReactNode
  label?: string
}

type State = {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught', this.props.label ?? '', error, info)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (this.state.error) {
      return (
        <div className="p-4 border border-red-900 bg-red-950/30 rounded text-sm">
          <div className="text-red-300 font-semibold mb-1">Something went wrong</div>
          <div className="text-red-400 text-xs mb-3">
            {this.props.label ? `In ${this.props.label}: ` : ''}
            {this.state.error.message}
          </div>
          <button
            onClick={this.reset}
            className="px-3 py-1 bg-red-900/50 hover:bg-red-900 text-red-200 text-xs rounded border border-red-800"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
