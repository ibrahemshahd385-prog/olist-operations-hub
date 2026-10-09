// Module 3: every seller's health at a glance, the alerts an account manager
// should act on, and how concentrated revenue is.
import { useState } from 'react'
import { api } from '../lib/api'
import { money, number, pct, shortId } from '../lib/format'
import { navigate } from '../lib/router'
import { useAsync } from '../lib/useAsync'
import { HBars, ParetoCurve } from '../components/charts'
import { ErrorNotice, Loading, Pagination } from '../components/ui'

export const TIER_TEXT = {
  A: 'Healthy',
  B: 'Good',
  C: 'Needs attention',
  D: 'At risk',
}

const ALERTS = [
  { key: 'key_account_at_risk', label: 'Key accounts at risk', bad: true },
  { key: 'gone_quiet', label: 'Stopped selling' },
  { key: 'revenue_drop', label: 'Revenue down 50%+' },
  { key: 'slow_shipping', label: 'Slow to ship' },
  { key: 'low_rating', label: 'Low rating' },
]

const PART_LABEL = { delivery: 'On-time delivery', rating: 'Customer rating', speed: 'Shipping speed', reliability: 'Reliability' }

export function TierBadge({ tier, health }) {
  return (
    <span className="nowrap">
      <span className={`tier tier-${tier || 'none'}`} title={tier ? TIER_TEXT[tier] : 'Fewer than 10 orders: not scored'}>{tier || '–'}</span>
      {health != null && <span className="score">{health}</span>}
    </span>
  )
}

const EMPTY = { q: '', tier: '', state: '', key_only: '', alert: '', credit_ready: '', sort: 'revenue', page: 1 }
let remembered = EMPTY

export default function SellersPage() {
  const [filters, setFiltersState] = useState(remembered)
  const setFilters = (next) => { remembered = next; setFiltersState(next) }
  const update = (key) => (e) => setFilters({ ...filters, [key]: e.target.value, page: 1 })
  const toggle = (key, value) => setFilters({ ...EMPTY, sort: filters.sort, [key]: filters[key] === value ? '' : value })

  const summary = useAsync(() => api.sellersSummary(), [])
  const list = useAsync(() => api.sellers({ ...filters, page_size: 25 }), [JSON.stringify(filters)])
  const meta = useAsync(() => api.meta(), [])

  if (summary.error) return <div className="page"><ErrorNotice error={summary.error} /></div>
  const s = summary.data

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Seller performance</h1>
          {s && (
            <p className="lede">
              Olist’s real customer is the seller. Of {number(s.sellers)} sellers, the top {number(s.key_accounts)} (10%)
              bring {pct(s.key_revenue_share, 1)} of revenue, so the health of those key accounts is the business.
              Scores use the dataset up to {s.as_of}.
            </p>
          )}
        </div>
      </header>

      {!s && <Loading />}
      {s && (
        <>
          <div className="two-col first">
            <section className="panel">
              <h2 className="panel-title">Revenue concentration</h2>
              <ParetoCurve points={s.pareto} />
            </section>
            <section className="panel">
              <h2 className="panel-title">Health tiers by share of revenue</h2>
              <p className="panel-intro">Sellers with at least {s.min_orders} orders get a 0–100 score and a tier.</p>
              <HBars
                label="Revenue share by health tier"
                rows={s.by_tier.map((t) => ({
                  key: t.tier || 'none',
                  label: t.tier ? `${t.tier}: ${TIER_TEXT[t.tier]}` : 'Not scored yet',
                  value: t.revenue_share, sellers: t.sellers,
                }))}
                format={(v) => pct(v, 1)}
                note={(r) => `${number(r.sellers)} sellers`}
              />
              <details className="chart-table how-score">
                <summary>How the score is built</summary>
                <ul>
                  {Object.entries(s.weights).map(([k, w]) => (
                    <li key={k}><strong>{PART_LABEL[k]} ({Math.round(w * 100)}%).</strong> {s.components[k]}.</li>
                  ))}
                  <li>Delivery weighs most because late orders drop the average review from 4.3 to 2.3 stars (Task 1 finding).</li>
                  <li>Tiers: A from 85, B from 70, C from 55, D below 55.</li>
                </ul>
              </details>
            </section>
          </div>

          <h2 className="section-title">Act on</h2>
          <div className="chips" role="group" aria-label="Alerts">
            {ALERTS.map((a) => (
              <button key={a.key} className={'chip' + (a.bad ? ' is-bad' : '') + (filters.alert === a.key ? ' is-active' : '')}
                      onClick={() => toggle('alert', a.key)} aria-pressed={filters.alert === a.key}>
                <strong>{number(s.alert_counts[a.key] || 0)}</strong>{a.label}
              </button>
            ))}
            <button className={'chip' + (filters.credit_ready ? ' is-active' : '')} onClick={() => toggle('credit_ready', 'true')}
                    aria-pressed={!!filters.credit_ready} title="Healthy, steady sellers: a first screen for Olist's credit offer">
              <strong>{number(s.credit_ready)}</strong>Ready for a credit offer
            </button>
          </div>
        </>
      )}

      <section className="filters" aria-label="Filters">
        <input className="input grow" type="search" placeholder="Seller id or city" value={filters.q} onChange={update('q')} aria-label="Search sellers" />
        <select className="input" value={filters.tier} onChange={update('tier')} aria-label="Tier">
          <option value="">All tiers</option>
          {['A', 'B', 'C', 'D'].map((t) => <option key={t} value={t}>{t}: {TIER_TEXT[t]}</option>)}
        </select>
        <select className="input" value={filters.state} onChange={update('state')} aria-label="Seller state">
          <option value="">All states</option>
          {meta.data?.states.map((st) => <option key={st}>{st}</option>)}
        </select>
        <select className="input" value={filters.key_only} onChange={update('key_only')} aria-label="Key accounts">
          <option value="">All sellers</option>
          <option value="true">Key accounts only</option>
        </select>
        <select className="input" value={filters.sort} onChange={update('sort')} aria-label="Sort by">
          <option value="revenue">Biggest first</option>
          <option value="health">Lowest health first</option>
          <option value="late">Most late first</option>
        </select>
        {JSON.stringify(filters) !== JSON.stringify(EMPTY) && <button className="btn btn-quiet" onClick={() => setFilters(EMPTY)}>Clear</button>}
      </section>

      <ErrorNotice error={list.error} />
      {list.data && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Seller</th><th className="num">Revenue</th><th className="num">Orders</th><th>Health</th>
                  <th className="num">On time</th><th className="num">Rating</th><th className="num">Days to ship</th><th>Alert</th></tr>
              </thead>
              <tbody className={list.loading ? 'is-stale' : ''}>
                {list.data.items.map((r) => (
                  <tr key={r.seller_id} className="row-link" tabIndex={0} onClick={() => navigate(`/sellers/${r.seller_id}`)}
                      onKeyDown={(e) => e.key === 'Enter' && navigate(`/sellers/${r.seller_id}`)}>
                    <td>
                      <span className="id">{shortId(r.seller_id)}</span>{r.key_account && <span className="tag">key</span>}
                      <small className="block muted cap">{r.city}, {r.state}</small>
                    </td>
                    <td className="num">{money(r.revenue)}<small className="block muted">#{number(r.revenue_rank)}</small></td>
                    <td className="num">{number(r.orders)}</td>
                    <td><TierBadge tier={r.tier} health={r.health} /></td>
                    <td className="num">{r.late_rate == null ? '—' : pct(1 - r.late_rate, 0)}</td>
                    <td className="num">{r.rating == null ? '—' : r.rating.toFixed(2)}</td>
                    <td className="num">{r.handling_days == null ? '—' : r.handling_days.toFixed(1)}</td>
                    <td className="alert-line">{r.alerts[0]?.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.data.items.length === 0 && <p className="empty">No sellers match these filters.</p>}
          </div>
          <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} noun="sellers"
                      onPage={(page) => setFilters({ ...filters, page })} />
        </>
      )}
    </div>
  )
}
