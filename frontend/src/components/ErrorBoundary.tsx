import { Component, type ReactNode, type ErrorInfo } from 'react';

import { isChunkLoadError, reloadOnceAfterChunkError, reloadPage } from '../utils/chunkReload';

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null; errorInfo: ErrorInfo | null }> {
  state = { error: null as Error | null, errorInfo: null as ErrorInfo | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    console.error('React crash:', error, errorInfo);
    if (isChunkLoadError(error)) reloadOnceAfterChunkError();
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: '#ef4444', backgroundColor: '#18181b', minHeight: '100vh', fontFamily: 'monospace' }}>
          <h1 style={{ fontSize: 20, marginBottom: 12 }}>UI Crash</h1>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{this.state.error.message}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#a1a1aa', marginTop: 12 }}>
            {this.state.error.stack}
          </pre>
          {/* Die ganze Seite neu laden: React.lazy merkt sich einen gescheiterten Import, ein bloßes Neuzeichnen
              liefe immer wieder in denselben Fehler. */}
          <button
            onClick={() => reloadPage()}
            style={{ marginTop: 16, padding: '8px 16px', backgroundColor: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
