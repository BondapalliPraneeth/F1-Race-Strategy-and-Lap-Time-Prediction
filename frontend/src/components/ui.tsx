import type { ReactNode } from 'react'
import type { ApiError } from '../api'

export type DataKind = 'actual' | 'predicted' | 'simulated' | 'derived' | 'assumption'
const KIND_TEXT: Record<DataKind, string> = {
  actual: 'ACTUAL', predicted: 'PREDICTED', simulated: 'SIMULATED', derived: 'ACTUAL · DERIVED', assumption: 'ASSUMPTION',
}

export function Badge({ kind }: { kind: DataKind }) {
  return <span className={`badge badge-${kind}`} data-testid={`badge-${kind}`}>{KIND_TEXT[kind]}</span>
}

/** Every chart/table declares what kind of values it shows and where they come from. */
export function Panel({ title, kind, source, children, actions }: { title: string; kind?: DataKind; source?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="panel" aria-label={title}>
      <header className="panel-head">
        <h3>{title}</h3>
        {kind && <Badge kind={kind} />}
        <span className="spacer" />
        {actions}
      </header>
      {children}
      {source && <footer className="source">Source: {source}</footer>}
    </section>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return <div className="spinner" role="status" aria-live="polite"><span className="dot" />{label}</div>
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="error" role="alert">
      <strong>{error.status === 0 ? 'Connection problem' : `Error ${error.status}`}</strong>
      <p>{error.message}</p>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty" data-testid="empty-state"><strong>{title}</strong>{children && <p>{children}</p>}</div>
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string | null }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && !error && <small>{hint}</small>}
      {error && <small className="err" role="alert">{error}</small>}
    </label>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return <div className="stat"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>
}
