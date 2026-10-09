// Small building blocks reused across screens.
import { STATUS_TONE } from '../lib/format'

export function StatusBadge({ status, label }) {
  return <span className={`badge tone-${STATUS_TONE[status] || 'info'}`}>{label || status}</span>
}

const RISK_TONE = { low: 'ok', medium: 'wait', high: 'bad' }

export function RiskBadge({ level, probability }) {
  if (!level) return null
  return (
    <span className={`badge tone-${RISK_TONE[level]}`}>
      {level[0].toUpperCase() + level.slice(1)} risk{probability != null && ` ${Math.round(probability * 100)}%`}
    </span>
  )
}

export function Notice({ tone = 'warn', title, items, children }) {
  if (!children && (!items || items.length === 0)) return null
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {title && <strong>{title}</strong>}
      {items && items.length > 0 && (
        <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
      )}
      {children}
    </div>
  )
}

export function ErrorNotice({ error }) {
  if (!error) return null
  return <Notice tone="error" items={error.messages || [String(error)]} />
}

export function Loading({ label = 'Loading…' }) {
  return <p className="loading">{label}</p>
}

export function Pagination({ page, pages, total, onPage, noun = 'orders' }) {
  return (
    <div className="pagination">
      <span>{total.toLocaleString('en-US')} {noun}</span>
      <div>
        <button className="btn btn-quiet" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="page-of">Page {page} of {pages.toLocaleString('en-US')}</span>
        <button className="btn btn-quiet" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  )
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={'field ' + className}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}
