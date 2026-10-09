// One seller: health score and what drives it, sales over time,
// where deliveries go wrong, and what the account manager should do next.
import { api } from '../lib/api'
import { date, money, number, pct, shortId } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { HBars, MonthlyBars } from '../components/charts'
import { ErrorNotice, Loading, StatusBadge } from '../components/ui'
import { navigate } from '../lib/router'
import { TIER_TEXT, TierBadge } from './SellersPage'

const PART_LABEL = { delivery: 'On-time delivery', rating: 'Customer rating', speed: 'Shipping speed', reliability: 'Reliability' }

export default function SellerDetailPage({ sellerId }) {
  const { data: s, error } = useAsync(() => api.seller(sellerId), [sellerId])
  const orders = useAsync(() => api.orders({ seller_id: sellerId, page_size: 8 }), [sellerId])

  if (error) return <div className="page"><a className="back" href="#/sellers">Sellers</a><ErrorNotice error={error} /></div>
  if (!s) return <div className="page"><Loading /></div>
  const net = s.network

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <a className="back" href="#/sellers">Sellers</a>
          <h1 className="order-title">Seller <span className="id">{shortId(s.seller_id)}</span>
            {s.key_account && <span className="badge tone-info">Key account</span>}</h1>
          <p className="lede">
            <span className="cap">{s.city}</span>, {s.state}. Number {number(s.revenue_rank)} of {number(s.sellers_total)} by
            revenue ({pct(s.revenue_share, 2)} of the platform). Sold from {date(s.first_sale)} to {date(s.last_sale)}.
          </p>
        </div>
      </header>

      <dl className="kpis">
        <div className="kpi"><dt>Revenue</dt><dd>{money(s.revenue)}<small>{number(s.orders)} orders, {money(s.avg_order_value)} each</small></dd></div>
        <div className="kpi"><dt>On time</dt><dd>{s.late_rate == null ? '—' : pct(1 - s.late_rate, 1)}<small>network {pct(1 - net.late_rate, 1)}</small></dd></div>
        <div className="kpi"><dt>Rating</dt><dd>{s.rating == null ? '—' : s.rating.toFixed(2)}<small>{number(s.reviews)} reviews, network {net.rating.toFixed(2)}</small></dd></div>
        <div className="kpi"><dt>Days to ship</dt><dd>{s.handling_days == null ? '—' : s.handling_days.toFixed(1)}<small>network {net.handling_days.toFixed(1)}</small></dd></div>
      </dl>

      <section className="panel">
        <h2 className="panel-title">Health score</h2>
        {s.health == null ? (
          <p className="muted">Fewer than 10 orders, so no score yet: a handful of orders would make it mostly luck.</p>
        ) : (
          <div className="scorecard">
            <div className="score-big">
              <strong>{s.health}</strong>
              <span><TierBadge tier={s.tier} /> {TIER_TEXT[s.tier]}</span>
            </div>
            <ul className="components">
              {s.components.map((c) => (
                <li key={c.key}>
                  <span className="part-label">{PART_LABEL[c.key]}<small className="muted">{Math.round(c.weight * 100)}% of the score</small></span>
                  <span className="hbar-track"><span className="hbar-fill" style={{ width: `${c.score ?? 0}%` }} /></span>
                  <span className="hbar-value">{c.score ?? '—'}</span>
                  <small>{c.rule}</small>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">What to do next</h2>
        {s.alerts.length > 0 && (
          <ul className="recs alerts">{s.alerts.map((a) => <li key={a.type} className="alert-line">{a.message}</li>)}</ul>
        )}
        <ol className="recs">{s.recommendations.map((r) => <li key={r}>{r}</li>)}</ol>
      </section>

      <section className="panel">
        <h2 className="panel-title">Revenue by month</h2>
        <MonthlyBars rows={s.monthly} valueKey="revenue" label="Seller revenue by month"
                     format={(v, axis) => axis ? `R$ ${v >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v)}` : money(v)}
                     extra={(r) => <><br />{r.orders} orders</>} />
      </section>

      <div className="two-col">
        <section className="panel">
          <h2 className="panel-title">Late deliveries by destination</h2>
          <p className="panel-intro">The six states this seller ships to most.</p>
          <HBars label="Late rate by destination state"
                 rows={s.late_by_state.map((r) => ({ key: r.state, label: r.state, value: r.late_rate || 0, orders: r.orders }))}
                 format={(v) => pct(v, 0)} note={(r) => `of ${number(r.orders)}`} max={Math.max(0.2, ...s.late_by_state.map((r) => r.late_rate || 0))} />
        </section>
        <section className="panel">
          <h2 className="panel-title">Top categories</h2>
          <HBars label="Revenue by category"
                 rows={s.categories.map((c) => ({ key: c.category, label: c.category.replaceAll('_', ' '), value: c.revenue, items: c.items }))}
                 format={money} note={(r) => `${number(r.items)} items`} />
        </section>
      </div>

      <section className="panel">
        <h2 className="panel-title">Latest orders</h2>
        {orders.data && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Order</th><th>Placed</th><th>Customer</th><th className="num">Total</th><th>Status</th></tr></thead>
              <tbody>
                {orders.data.items.map((o) => (
                  <tr key={o.order_id} className="row-link" tabIndex={0} onClick={() => navigate(`/orders/${o.order_id}`)}
                      onKeyDown={(e) => e.key === 'Enter' && navigate(`/orders/${o.order_id}`)}>
                    <td className="id">{shortId(o.order_id)}</td>
                    <td>{date(o.order_purchase_timestamp)}</td>
                    <td className="cap">{o.customer_city}, {o.customer_state}</td>
                    <td className="num">{money(o.total)}</td>
                    <td><StatusBadge status={o.order_status} label={o.status_label} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
