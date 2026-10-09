// One order: where it is in its journey, what can be done next,
// and everything attached to it (items, NF-e per seller, payments, review, history).
import { useState } from 'react'
import { api } from '../lib/api'
import { takeFlash } from '../lib/flash'
import { accessKeyBlocks, dateTime, money, PAYMENT_LABELS, shortId } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import LifecycleRoute from '../components/LifecycleRoute'
import { ErrorNotice, Loading, Notice, RiskBadge, StatusBadge } from '../components/ui'

// The main forward action gets the primary button; the rest are secondary.
const PRIMARY = ['approve_payment', 'start_processing', 'ship', 'deliver']

const EVENT_LABELS = {
  created: 'Order registered',
  approved: 'Payment approved',
  processing: 'Processing started',
  invoice_issued: 'NF-e issued',
  invoice_canceled: 'NF-e canceled',
  invoiced: 'Order invoiced',
  shipped: 'Handed to carrier',
  delivered: 'Delivered',
  canceled: 'Order canceled',
  unavailable: 'Marked unavailable',
}

export default function OrderDetailPage({ orderId }) {
  const [flash] = useState(takeFlash)
  const { data: o, error, loading, setData, reload } = useAsync(() => api.order(orderId), [orderId])
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')

  async function run(action, note) {
    setBusy(action)
    setActionError(null)
    try {
      setData(await api.runAction(orderId, action, note))
      setCancelling(false)
      setReason('')
    } catch (e) {
      setActionError(e)
    } finally {
      setBusy(null)
    }
  }

  async function issue(sellerId) {
    setBusy('invoice:' + sellerId)
    setActionError(null)
    try {
      await api.issueInvoice(orderId, sellerId)
      reload()
    } catch (e) {
      setActionError(e)
    } finally {
      setBusy(null)
    }
  }

  if (error) return <div className="page"><a className="back" href="#/orders">Orders</a><ErrorNotice error={error} /></div>
  if (!o) return <div className="page">{loading && <Loading />}</div>

  const forward = o.actions.filter((a) => PRIMARY.includes(a.action))
  const other = o.actions.filter((a) => !PRIMARY.includes(a.action) && a.action !== 'cancel')
  const canCancel = o.actions.some((a) => a.action === 'cancel')
  const review = o.reviews[0]

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <a className="back" href="#/orders">Orders</a>
          <h1 className="order-title">
            Order <span className="id">{shortId(o.order_id)}</span>
            <StatusBadge status={o.order_status} label={o.status_label} />
          </h1>
          <p className="lede">
            Placed {dateTime(o.order_purchase_timestamp)} by a customer in{' '}
            <span className="cap">{o.customer.customer_city}</span>, {o.customer.customer_state}.{' '}
            {o.source === 'historical'
              ? 'This order comes from the dataset and is read-only.'
              : 'Registered in this system.'}
          </p>
        </div>
      </header>

      {flash && <Notice tone="ok" title={flash.title} items={flash.items} />}

      <section className="panel route-panel">
        <LifecycleRoute timeline={o.timeline} promisedDate={o.delivery.promised_date} />
        {(forward.length > 0 || other.length > 0 || canCancel) && (
          <div className="actions">
            {forward.map((a) => (
              <button key={a.action} className="btn btn-primary" disabled={!!busy} onClick={() => run(a.action)}>
                {busy === a.action ? 'Saving…' : a.label}
              </button>
            ))}
            {o.order_status === 'processing' && (
              <span className="hint">Issue an NF-e for each seller below to move the order to “invoiced”.</span>
            )}
            {other.map((a) => (
              <button key={a.action} className="btn btn-secondary" disabled={!!busy} onClick={() => run(a.action, 'Product out of stock')}>
                {a.label}
              </button>
            ))}
            {canCancel && !cancelling && (
              <button className="btn btn-danger-quiet" onClick={() => setCancelling(true)}>Cancel order</button>
            )}
          </div>
        )}
        {cancelling && (
          <div className="cancel-form">
            <label className="field">
              <span className="field-label">Why is this order being canceled?</span>
              <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus
                     placeholder="e.g. customer asked to cancel" />
            </label>
            {o.order_status === 'invoiced' && (
              <p className="field-hint">Its NF-e will be canceled too. That is only allowed within 24 hours of issue.</p>
            )}
            <div className="actions">
              <button className="btn btn-danger" disabled={!reason.trim() || !!busy} onClick={() => run('cancel', reason.trim())}>
                {busy === 'cancel' ? 'Canceling…' : 'Cancel order'}
              </button>
              <button className="btn btn-quiet" onClick={() => setCancelling(false)}>Keep order</button>
            </div>
          </div>
        )}
        <ErrorNotice error={actionError} />
      </section>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel">
            <h2 className="panel-title">Items</h2>
            {o.items.length === 0 ? (
              <p className="muted">The dataset has no items for this order. That is common for canceled and unavailable orders.</p>
            ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Product</th><th>Seller</th><th className="num">Qty</th>
                    <th className="num">Unit price</th><th className="num">Freight</th><th className="num">Total</th></tr>
                </thead>
                <tbody>
                  {o.items.map((it) => (
                    <tr key={it.product_id + it.seller_id + it.unit_price}
                        className={it.unit_freight > it.unit_price ? 'is-flagged' : ''}>
                      <td><span className="cap strong">{it.category.replaceAll('_', ' ')}</span>
                        <small className="block muted">{shortId(it.product_id)}{it.weight_g != null && `, ${it.weight_g} g`}</small></td>
                      <td><span className="id">{shortId(it.seller_id)}</span>
                        <small className="block muted cap">{it.seller_city}, {it.seller_state}</small></td>
                      <td className="num">{it.quantity}</td>
                      <td className="num">{money(it.unit_price)}</td>
                      <td className="num">{money(it.line_freight)}</td>
                      <td className="num">{money(it.line_total + it.line_freight)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr><td colSpan={4}>Freight is {o.totals.freight_share}% of the product value</td>
                    <td className="num">{money(o.totals.freight)}</td><td className="num strong">{money(o.totals.total)}</td></tr>
                </tfoot>
              </table>
            </div>
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">Invoices (NF-e)</h2>
            <p className="panel-intro">Each seller is a separate issuer, so each one issues its own NF-e for its part of the order.</p>
            <div className="invoice-list">
              {o.sellers.length === 0 && <p className="muted">No items, so there is nothing to invoice.</p>}
              {o.sellers.map((s) => (
                <article key={s.seller_id} className="invoice-card">
                  <header>
                    <div>
                      <span className="muted">Seller </span><span className="id">{shortId(s.seller_id)}</span>
                      <small className="block muted"><span className="cap">{s.city}</span>, {s.state}. {s.items} item{s.items > 1 ? 's' : ''}, {money(s.subtotal)}</small>
                    </div>
                    {s.invoice && <span className={`badge tone-${s.invoice.status === 'authorized' ? 'ok' : 'bad'}`}>
                      {s.invoice.status === 'authorized' ? 'Authorized' : 'Canceled'}</span>}
                  </header>
                  {s.invoice ? (
                    <div className="invoice-body">
                      <p>NF-e nº {s.invoice.number}, series {s.invoice.series}, issued {dateTime(s.invoice.issued_at)}</p>
                      <p className="access-key">{accessKeyBlocks(s.invoice.access_key)}</p>
                      <a className="btn btn-secondary" href={`#/invoices/${s.invoice.invoice_id}`}>Open DANFE</a>
                      {s.can_issue_invoice && (
                        <button className="btn btn-primary" disabled={!!busy} onClick={() => issue(s.seller_id)}>Issue new NF-e</button>
                      )}
                    </div>
                  ) : s.can_issue_invoice ? (
                    <button className="btn btn-primary" disabled={!!busy} onClick={() => issue(s.seller_id)}>
                      {busy === 'invoice:' + s.seller_id ? 'Issuing…' : 'Issue NF-e'}
                    </button>
                  ) : (
                    <p className="muted">
                      {o.source === 'historical'
                        ? 'The dataset has no invoice records.'
                        : ['created', 'approved'].includes(o.order_status)
                          ? 'Available once the order is being processed.'
                          : 'No NF-e was issued.'}
                    </p>
                  )}
                </article>
              ))}
            </div>
          </section>

          {o.events.length > 0 && (
            <section className="panel">
              <h2 className="panel-title">Activity</h2>
              <ol className="activity">
                {o.events.map((e) => (
                  <li key={e.event_id}>
                    <time>{dateTime(e.occurred_at)}</time>
                    <span>{EVENT_LABELS[e.status] || e.status}{e.note && <small className="block muted">{e.note}</small>}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>

        <aside className="detail-side">
          <section className="panel">
            <h2 className="panel-title">Delivery</h2>
            <dl className="facts">
              <div><dt>Promised</dt><dd>{dateTime(o.delivery.promised_date)}{o.delivery.promised_days != null && <small> ({o.delivery.promised_days} days)</small>}</dd></div>
              {o.delivery.delivered_days != null && (
                <>
                  <div><dt>Delivered in</dt><dd>{o.delivery.delivered_days} days</dd></div>
                  <div><dt>Against promise</dt>
                    <dd className={o.delivery.on_time ? 'good' : 'bad'}>
                      {o.delivery.days_vs_promise === 0 ? 'On the day'
                        : o.delivery.on_time ? `${-o.delivery.days_vs_promise} days early` : `${o.delivery.days_vs_promise} days late`}
                    </dd></div>
                </>
              )}
            </dl>
            {o.prediction && (
              <div className="prediction">
                <div className="quote-row">
                  <span className="muted">Late risk when registered</span>
                  <RiskBadge level={o.prediction.risk_level} probability={o.prediction.late_risk} />
                </div>
                <p className="field-hint">
                  {o.prediction.promise_source === 'model'
                    ? `Promise set by the model (expected ${Math.round(o.prediction.eta_days)} days). Olist would have promised ${o.prediction.legacy_promise_days}.`
                    : 'Promise copied from Olist’s history for this state.'}
                </p>
                {o.prediction.risk_reasons.length > 0 && (
                  <ul className="reasons">{o.prediction.risk_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">Customer</h2>
            <dl className="facts">
              <div><dt>Customer id</dt><dd className="id">{shortId(o.customer.customer_unique_id)}</dd></div>
              <div><dt>Ship to</dt><dd><span className="cap">{o.customer.customer_city}</span>, {o.customer.customer_state} {o.customer.customer_zip_code_prefix}</dd></div>
              <div><dt>Other orders</dt><dd>{o.customer_previous_orders === 0 ? 'First order' : o.customer_previous_orders}</dd></div>
            </dl>
          </section>

          <section className="panel">
            <h2 className="panel-title">Payments</h2>
            <dl className="facts">
              {o.payments.map((p) => (
                <div key={p.payment_sequential}>
                  <dt>{PAYMENT_LABELS[p.payment_type] || p.payment_type}{p.payment_installments > 1 && ` in ${p.payment_installments}×`}</dt>
                  <dd>{money(p.payment_value)}</dd>
                </div>
              ))}
              <div className="sum-total"><dt>Paid</dt><dd>{money(o.paid_total)}</dd></div>
            </dl>
          </section>

          {review && (
            <section className="panel">
              <h2 className="panel-title">Customer review</h2>
              <p className={`stars score-${review.review_score}`} aria-label={`${review.review_score} out of 5`}>
                {'★'.repeat(review.review_score)}<span>{'★'.repeat(5 - review.review_score)}</span>
              </p>
              {review.review_comment_title && <p className="strong">{review.review_comment_title}</p>}
              {review.review_comment_message
                ? <blockquote lang="pt-BR">{review.review_comment_message}</blockquote>
                : <p className="muted">No written comment.</p>}
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}
