// Orders list: the work queue for orders registered in the system,
// then every order (dataset + new) with filters.
import { useState } from 'react'
import { api } from '../lib/api'
import { date, money, number, shortId } from '../lib/format'
import { navigate } from '../lib/router'
import { useAsync } from '../lib/useAsync'
import { ErrorNotice, Loading, Pagination, StatusBadge } from '../components/ui'

const QUEUE = [
  { status: 'created', label: 'Awaiting payment' },
  { status: 'approved', label: 'To process' },
  { status: 'processing', label: 'To invoice' },
  { status: 'invoiced', label: 'To ship' },
  { status: 'shipped', label: 'In transit' },
]

const EMPTY = { q: '', status: '', state: '', source: '', date_from: '', date_to: '', page: 1 }
let remembered = EMPTY // keeps the filters when you open an order and come back

export default function OrdersPage() {
  const [filters, setFiltersState] = useState(remembered)
  const setFilters = (next) => {
    remembered = next
    setFiltersState(next)
  }
  const update = (key) => (e) => setFilters({ ...filters, [key]: e.target.value, page: 1 })

  const meta = useAsync(() => api.meta(), [])
  const summary = useAsync(() => api.summary(), [])
  const list = useAsync(() => api.orders({ ...filters, page_size: 25 }), [JSON.stringify(filters)])

  const s = summary.data
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Orders & invoices</h1>
          {s && (
            <p className="lede">
              {number(s.orders)} orders worth {money(s.gmv)} in products. The dataset covers{' '}
              {date(s.dataset_from)} to {date(s.dataset_to)}. {s.system_orders > 0
                ? `${number(s.system_orders)} of them ${s.system_orders === 1 ? 'was' : 'were'} registered in this system.`
                : 'None registered in this system yet.'}
            </p>
          )}
        </div>
        <a className="btn btn-primary" href="#/orders/new">Register order</a>
      </header>

      <section className="queue" aria-label="Work queue for orders registered here">
        <h2 className="section-title">Work queue</h2>
        <ol className="queue-steps">
          {QUEUE.map((q) => {
            const n = s?.work_queue?.[q.status] ?? 0
            const active = filters.status === q.status && filters.source === 'system'
            return (
              <li key={q.status}>
                <button
                  className={'queue-step' + (n ? ' has-work' : '') + (active ? ' is-active' : '')}
                  onClick={() => setFilters({ ...EMPTY, status: active ? '' : q.status, source: active ? '' : 'system' })}
                >
                  <span className="queue-count">{n}</span>
                  <span className="queue-label">{q.label}</span>
                </button>
              </li>
            )
          })}
        </ol>
      </section>

      <section className="filters" aria-label="Filters">
        <input className="input grow" type="search" placeholder="Order or customer id" value={filters.q}
               onChange={update('q')} aria-label="Search by order or customer id" />
        <select className="input" value={filters.status} onChange={update('status')} aria-label="Status">
          <option value="">All statuses</option>
          {meta.data?.statuses.map((st) => <option key={st.value} value={st.value}>{st.label}</option>)}
        </select>
        <select className="input" value={filters.state} onChange={update('state')} aria-label="Customer state">
          <option value="">All states</option>
          {meta.data?.states.map((st) => <option key={st} value={st}>{st}</option>)}
        </select>
        <select className="input" value={filters.source} onChange={update('source')} aria-label="Source">
          <option value="">Dataset and new</option>
          <option value="system">Registered here</option>
          <option value="historical">Dataset only</option>
        </select>
        <input className="input" type="date" value={filters.date_from} onChange={update('date_from')} aria-label="From date" />
        <input className="input" type="date" value={filters.date_to} onChange={update('date_to')} aria-label="To date" />
        {JSON.stringify(filters) !== JSON.stringify(EMPTY) && (
          <button className="btn btn-quiet" onClick={() => setFilters(EMPTY)}>Clear</button>
        )}
      </section>

      <ErrorNotice error={list.error} />
      {list.data && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Placed</th>
                  <th>Customer</th>
                  <th className="num">Items</th>
                  <th className="num">Total</th>
                  <th>Status</th>
                  <th>Delivery</th>
                </tr>
              </thead>
              <tbody className={list.loading ? 'is-stale' : ''}>
                {list.data.items.map((o) => (
                  <tr key={o.order_id} className="row-link" tabIndex={0}
                      onClick={() => navigate(`/orders/${o.order_id}`)}
                      onKeyDown={(e) => e.key === 'Enter' && navigate(`/orders/${o.order_id}`)}>
                    <td>
                      <span className="id">{shortId(o.order_id)}</span>
                      {o.source === 'system' && <span className="tag">new</span>}
                    </td>
                    <td>{date(o.order_purchase_timestamp)}</td>
                    <td className="cap">{o.customer_city}, {o.customer_state}</td>
                    <td className="num">{o.items}{o.sellers > 1 && <small className="block muted">{o.sellers} sellers</small>}</td>
                    <td className="num">{money(o.total)}</td>
                    <td><StatusBadge status={o.order_status} label={o.status_label} /></td>
                    <td className="muted">
                      {o.order_delivered_customer_date
                        ? `Delivered ${date(o.order_delivered_customer_date)}`
                        : o.order_estimated_delivery_date ? `Promised ${date(o.order_estimated_delivery_date)}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.data.items.length === 0 && (
              <p className="empty">No orders match these filters. Clear them, or register a new order.</p>
            )}
          </div>
          <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total}
                      onPage={(page) => setFilters({ ...filters, page })} />
        </>
      )}
      {!list.data && list.loading && <Loading />}
    </div>
  )
}
