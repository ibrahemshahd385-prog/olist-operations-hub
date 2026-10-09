// Register a sale: customer -> items -> payment, with a live summary.
// The browser checks the obvious things as you type; the API re-checks
// everything (it is the source of truth) and may return extra warnings.
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { setFlash } from '../lib/flash'
import { date, money, number, PAYMENT_LABELS, shortId } from '../lib/format'
import { navigate } from '../lib/router'
import { Field, Notice, RiskBadge } from '../components/ui'

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

// Runs a search whenever the (debounced) text changes
function useSearch(fn, query, enabled = true, key = '') {
  const q = useDebounced(query)
  const [results, setResults] = useState([])
  useEffect(() => {
    if (!enabled) return
    let alive = true
    fn(q).then((r) => alive && setResults(r)).catch(() => alive && setResults([]))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, enabled, key])
  return results
}

const round2 = (n) => Math.round(n * 100) / 100

export default function NewOrderPage() {
  const [meta, setMeta] = useState(null)
  useEffect(() => { api.meta().then(setMeta) }, [])

  // ---- 1. customer
  const [mode, setMode] = useState('existing')
  const [customerQuery, setCustomerQuery] = useState('')
  const [customer, setCustomer] = useState(null)
  const [newCustomer, setNewCustomer] = useState({ zip_code_prefix: '', city: '', state: '' })
  const customers = useSearch(api.searchCustomers, customerQuery, mode === 'existing' && !customer)

  // ---- 2. items
  const [sellerQuery, setSellerQuery] = useState('')
  const [seller, setSeller] = useState(null)
  const [productQuery, setProductQuery] = useState('')
  const sellers = useSearch(api.searchSellers, sellerQuery, !seller)
  const products = useSearch((q) => api.sellerProducts(seller.seller_id, q), productQuery, !!seller, seller?.seller_id)
  const [lines, setLines] = useState([])

  // ---- 3. payment
  const [payments, setPayments] = useState([{ payment_type: 'credit_card', installments: 1, value: '' }])

  const [submitting, setSubmitting] = useState(false)
  const [apiErrors, setApiErrors] = useState([])

  // ---- totals, derived from the lines (never stored twice)
  const productsTotal = round2(lines.reduce((s, l) => s + Number(l.unit_price || 0) * Number(l.quantity || 0), 0))
  const freightTotal = round2(lines.reduce((s, l) => s + Number(l.freight_value || 0) * Number(l.quantity || 0), 0))
  const total = round2(productsTotal + freightTotal)
  const paid = round2(payments.reduce((s, p) => s + Number(p.value || 0), 0))
  const remaining = round2(total - paid)

  const destination = mode === 'existing' ? customer?.state : newCustomer.state
  const [delivery, setDelivery] = useState(null)
  useEffect(() => {
    if (!destination) return setDelivery(null)
    api.deliveryReference(destination).then(setDelivery).catch(() => setDelivery(null))
  }, [destination])

  // ---- Module 2: ask the logistics models about this order while it is being typed
  const [quote, setQuote] = useState(null)
  const quoteCustomer = mode === 'existing'
    ? (customer ? { customer_unique_id: customer.customer_unique_id } : null)
    : (/^\d{5}$/.test(newCustomer.zip_code_prefix) && newCustomer.state ? newCustomer : null)
  const quoteKey = useDebounced(JSON.stringify({
    c: quoteCustomer,
    l: lines.map((l) => [l.product_id, l.seller_id, Number(l.unit_price), Number(l.quantity), Number(l.freight_value || 0)]),
    p: payments.map((p) => p.payment_type),
  }), 400)
  useEffect(() => {
    const k = JSON.parse(quoteKey)
    if (!k.c || k.l.length === 0 || k.l.some((l) => !(l[2] > 0) || !(l[3] >= 1))) return setQuote(null)
    let alive = true
    api.quote({
      customer: k.c,
      items: k.l.map(([product_id, seller_id, unit_price, quantity, freight_value]) => ({ product_id, seller_id, unit_price, quantity, freight_value })),
      payment_types: k.p,
    }).then((q) => alive && setQuote(q.available ? q : null)).catch(() => alive && setQuote(null))
    return () => { alive = false }
  }, [quoteKey])
  const freightEstimate = (i) => quote?.freight_estimates?.find((f) => f.line === i)?.per_unit
  const freightTooHigh = (l, i) => {
    const est = freightEstimate(i)
    return est != null && Number(l.freight_value) > est * 1.5 && Number(l.freight_value) - est > 5
  }

  const warnings = useMemo(() => {
    const w = []
    lines.forEach((l, i) => {
      if (Number(l.freight_value) > Number(l.unit_price))
        w.push(`Line ${i + 1}: freight is higher than the product price. 4,124 items in the dataset had this problem.`)
    })
    const sellerCount = new Set(lines.map((l) => l.seller_id)).size
    if (sellerCount > 1) w.push(`${sellerCount} sellers: each one will issue its own NF-e.`)
    if (payments.some((p) => p.payment_type === 'boleto'))
      w.push('Boleto: the order waits for payment confirmation (median 29 hours in the dataset).')
    lines.forEach((l, i) => {
      if (freightTooHigh(l, i))
        w.push(`Line ${i + 1}: freight is ${(Number(l.freight_value) / freightEstimate(i)).toFixed(1)}x what this route usually costs.`)
    })
    return w
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, payments, quote])

  const problems = []
  if (mode === 'existing' && !customer) problems.push('Choose a customer')
  if (mode === 'new' && !(/^\d{5}$/.test(newCustomer.zip_code_prefix) && newCustomer.city && newCustomer.state))
    problems.push('Fill in the new customer’s address (5-digit zip prefix, city, state)')
  if (lines.length === 0) problems.push('Add at least one item')
  if (lines.some((l) => !(Number(l.unit_price) > 0) || !(Number(l.quantity) >= 1)))
    problems.push('Every item needs a price above zero and a quantity')
  if (lines.length && Math.abs(remaining) > 0.009)
    problems.push(remaining > 0 ? `${money(remaining)} still to be paid` : `Payments exceed the total by ${money(-remaining)}`)

  // ---- line helpers
  const addProduct = (p) => {
    const existing = lines.findIndex((l) => l.product_id === p.product_id && l.seller_id === seller.seller_id)
    if (existing >= 0) {
      setLines(lines.map((l, i) => (i === existing ? { ...l, quantity: Number(l.quantity) + 1 } : l)))
      return
    }
    setLines([...lines, {
      product_id: p.product_id, seller_id: seller.seller_id,
      seller_label: `${seller.city}, ${seller.state}`, category: p.category, weight_g: p.weight_g,
      unit_price: p.avg_price, quantity: 1, freight_value: p.avg_freight,
    }])
  }
  const editLine = (i, key, value) => setLines(lines.map((l, j) => (j === i ? { ...l, [key]: value } : l)))
  const removeLine = (i) => setLines(lines.filter((_, j) => j !== i))

  const editPayment = (i, key, value) =>
    setPayments(payments.map((p, j) => {
      if (j !== i) return p
      const next = { ...p, [key]: value }
      if (key === 'payment_type' && value !== 'credit_card') next.installments = 1
      return next
    }))
  const fillRemaining = (i) => {
    const others = round2(payments.reduce((s, p, j) => (j === i ? s : s + Number(p.value || 0)), 0))
    editPayment(i, 'value', Math.max(0, round2(total - others)))
  }

  async function submit() {
    setSubmitting(true)
    setApiErrors([])
    const payload = {
      customer: mode === 'existing' ? { customer_unique_id: customer.customer_unique_id } : newCustomer,
      items: lines.map((l) => ({
        product_id: l.product_id, seller_id: l.seller_id, unit_price: Number(l.unit_price),
        quantity: Number(l.quantity), freight_value: Number(l.freight_value || 0),
      })),
      payments: payments.map((p) => ({ payment_type: p.payment_type, installments: Number(p.installments), value: Number(p.value) })),
    }
    try {
      const res = await api.createOrder(payload)
      setFlash({ title: `Order registered: ${money(res.total)}`, items: res.warnings })
      navigate(`/orders/${res.order_id}`)
    } catch (e) {
      setApiErrors(e.messages || [String(e)])
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <a className="back" href="#/orders">Orders</a>
          <h1>Register order</h1>
          <p className="lede">Record a sale. Once saved, it moves through payment, NF-e and shipping from the order page.</p>
        </div>
      </header>

      <div className="compose">
        <div className="compose-form">
          {/* ---------------- 1. Customer ---------------- */}
          <section className="panel">
            <h2 className="panel-title"><span className="step-no">1</span>Customer</h2>
            <div className="segmented" role="tablist">
              <button role="tab" aria-selected={mode === 'existing'} onClick={() => setMode('existing')}>Returning customer</button>
              <button role="tab" aria-selected={mode === 'new'} onClick={() => setMode('new')}>New customer</button>
            </div>

            {mode === 'existing' && (customer ? (
              <div className="picked">
                <div>
                  <strong className="id">{shortId(customer.customer_unique_id)}</strong>
                  <span className="cap"> {customer.city}, {customer.state}</span>
                  <small>{customer.orders} previous order{customer.orders > 1 ? 's' : ''}, last on {date(customer.last_order_at)}</small>
                </div>
                <button className="btn btn-quiet" onClick={() => setCustomer(null)}>Change</button>
              </div>
            ) : (
              <>
                <input className="input" type="search" placeholder="Search by customer id or city" value={customerQuery}
                       onChange={(e) => setCustomerQuery(e.target.value)} aria-label="Search customers" />
                <ul className="pick-list">
                  {customers.map((c) => (
                    <li key={c.customer_unique_id}>
                      <button onClick={() => setCustomer(c)}>
                        <span className="id">{shortId(c.customer_unique_id)}</span>
                        <span className="cap">{c.city}, {c.state}</span>
                        <span className="muted">{c.orders} order{c.orders > 1 ? 's' : ''}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ))}

            {mode === 'new' && (
              <div className="grid-3">
                <Field label="Zip code prefix" hint="First 5 digits of the CEP">
                  <input className="input" inputMode="numeric" maxLength={5} value={newCustomer.zip_code_prefix}
                         onChange={(e) => setNewCustomer({ ...newCustomer, zip_code_prefix: e.target.value.replace(/\D/g, '') })} />
                </Field>
                <Field label="City">
                  <input className="input" value={newCustomer.city}
                         onChange={(e) => setNewCustomer({ ...newCustomer, city: e.target.value })} />
                </Field>
                <Field label="State">
                  <select className="input" value={newCustomer.state}
                          onChange={(e) => setNewCustomer({ ...newCustomer, state: e.target.value })}>
                    <option value="">Choose</option>
                    {meta?.states.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </Field>
              </div>
            )}
          </section>

          {/* ---------------- 2. Items ---------------- */}
          <section className="panel">
            <h2 className="panel-title"><span className="step-no">2</span>Items</h2>
            {seller ? (
              <div className="picked">
                <div>
                  <span className="muted">Seller </span>
                  <strong className="id">{shortId(seller.seller_id)}</strong>
                  <span className="cap"> {seller.city}, {seller.state}</span>
                  <small>{number(seller.orders)} orders, {money(seller.revenue)} sold</small>
                </div>
                <button className="btn btn-quiet" onClick={() => { setSeller(null); setProductQuery('') }}>Change seller</button>
              </div>
            ) : (
              <>
                <input className="input" type="search" placeholder="Search sellers by id or city" value={sellerQuery}
                       onChange={(e) => setSellerQuery(e.target.value)} aria-label="Search sellers" />
                <ul className="pick-list">
                  {sellers.map((s) => (
                    <li key={s.seller_id}>
                      <button onClick={() => setSeller(s)}>
                        <span className="id">{shortId(s.seller_id)}</span>
                        <span className="cap">{s.city}, {s.state}</span>
                        <span className="muted">{number(s.orders)} orders</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {seller && (
              <>
                <input className="input" type="search" placeholder="Filter this seller’s products by category or id"
                       value={productQuery} onChange={(e) => setProductQuery(e.target.value)} aria-label="Search products" />
                <p className="field-hint">Products in the dataset have no names, so they are listed by category and weight. Price and freight are pre-filled with this seller’s averages.</p>
                <ul className="pick-list products">
                  {products.map((p) => (
                    <li key={p.product_id}>
                      <button onClick={() => addProduct(p)}>
                        <span className="cap strong">{p.category.replaceAll('_', ' ')}</span>
                        <span className="muted">{p.weight_g != null ? `${number(p.weight_g)} g` : 'no weight'}</span>
                        <span className="muted">{number(p.units_sold)} sold</span>
                        <span className="num">{money(p.avg_price)}</span>
                        <span className="add">Add</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {lines.length > 0 && (
              <div className="table-wrap">
                <table className="table lines">
                  <thead>
                    <tr><th>Product</th><th className="num">Unit price</th><th className="num">Qty</th>
                      <th className="num">Freight / unit</th><th className="num">Line total</th><th /></tr>
                  </thead>
                  <tbody>
                    {lines.map((l, i) => (
                      <tr key={l.product_id + l.seller_id}
                          className={Number(l.freight_value) > Number(l.unit_price) ? 'is-flagged' : ''}>
                        <td>
                          <span className="cap strong">{l.category.replaceAll('_', ' ')}</span>
                          <small className="block muted">{shortId(l.product_id)}, seller in <span className="cap">{l.seller_label}</span></small>
                        </td>
                        <td className="num"><input className="input input-num" type="number" min="0.01" step="0.01"
                          value={l.unit_price} onChange={(e) => editLine(i, 'unit_price', e.target.value)} aria-label="Unit price" /></td>
                        <td className="num"><input className="input input-num qty" type="number" min="1" max="20"
                          value={l.quantity} onChange={(e) => editLine(i, 'quantity', e.target.value)} aria-label="Quantity" /></td>
                        <td className="num"><input className="input input-num" type="number" min="0" step="0.01"
                          value={l.freight_value} onChange={(e) => editLine(i, 'freight_value', e.target.value)} aria-label="Freight per unit" />
                          {freightEstimate(i) != null && (
                            <span className={'freight-hint' + (freightTooHigh(l, i) ? ' is-high' : '')}>
                              Expected {money(freightEstimate(i))}
                              <button type="button" onClick={() => editLine(i, 'freight_value', freightEstimate(i))}>Use</button>
                            </span>
                          )}</td>
                        <td className="num">{money(round2((Number(l.unit_price) + Number(l.freight_value || 0)) * Number(l.quantity)))}</td>
                        <td><button className="btn btn-quiet" onClick={() => removeLine(i)} aria-label="Remove line">Remove</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ---------------- 3. Payment ---------------- */}
          <section className="panel">
            <h2 className="panel-title"><span className="step-no">3</span>Payment</h2>
            {payments.map((p, i) => (
              <div className="pay-row" key={i}>
                <Field label="Method">
                  <select className="input" value={p.payment_type} onChange={(e) => editPayment(i, 'payment_type', e.target.value)}>
                    {(meta?.payment_types || ['credit_card']).map((t) => <option key={t} value={t}>{PAYMENT_LABELS[t]}</option>)}
                  </select>
                </Field>
                <Field label="Installments" hint={p.payment_type === 'credit_card' && Number(p.value) > 0 && p.installments > 1
                  ? `${p.installments} × ${money(Number(p.value) / p.installments)}` : p.payment_type === 'credit_card' ? '' : 'Cards only'}>
                  <select className="input" value={p.installments} disabled={p.payment_type !== 'credit_card'}
                          onChange={(e) => editPayment(i, 'installments', Number(e.target.value))}>
                    {Array.from({ length: 24 }, (_, k) => k + 1).map((n) => <option key={n} value={n}>{n}×</option>)}
                  </select>
                </Field>
                <Field label="Amount (R$)">
                  <input className="input input-num" type="number" min="0" step="0.01" value={p.value}
                         onChange={(e) => editPayment(i, 'value', e.target.value)} />
                </Field>
                <div className="pay-actions">
                  {Math.abs(remaining) > 0.009 && total > 0 && (
                    <button className="btn btn-quiet" onClick={() => fillRemaining(i)}>Fill remaining</button>
                  )}
                  {payments.length > 1 && (
                    <button className="btn btn-quiet" onClick={() => setPayments(payments.filter((_, j) => j !== i))}>Remove</button>
                  )}
                </div>
              </div>
            ))}
            <button className="btn btn-secondary"
                    onClick={() => setPayments([...payments, { payment_type: 'voucher', installments: 1, value: remaining > 0 ? remaining : '' }])}>
              Split with another method
            </button>
          </section>
        </div>

        {/* ---------------- live summary ---------------- */}
        <aside className="compose-summary panel">
          <h2 className="panel-title">Summary</h2>
          <dl className="sums">
            <div><dt>Products</dt><dd>{money(productsTotal)}</dd></div>
            <div><dt>Freight{productsTotal > 0 && <small> ({Math.round((freightTotal / productsTotal) * 100)}% of products)</small>}</dt><dd>{money(freightTotal)}</dd></div>
            <div className="sum-total"><dt>Total</dt><dd>{money(total)}</dd></div>
            <div><dt>Paid</dt><dd>{money(paid)}</dd></div>
            <div className={Math.abs(remaining) > 0.009 ? 'sum-bad' : 'sum-ok'}>
              <dt>{remaining < 0 ? 'Overpaid' : 'Remaining'}</dt><dd>{money(Math.abs(remaining))}</dd>
            </div>
          </dl>

          {quote && (
            <div className="quote-box">
              <div className="quote-row">
                <strong>Promise: {quote.promise_days} days</strong>
                <RiskBadge level={quote.risk.level} probability={quote.risk.probability} />
              </div>
              <p>
                Expected delivery in about {Math.round(quote.eta_days)} days, {number(quote.distance_km)} km from the seller.
                Olist would have promised {quote.legacy_promise_days} days.
              </p>
              {quote.risk.reasons.length > 0 && <ul>{quote.risk.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
            </div>
          )}

          {!quote && delivery && (
            <div className="promise">
              <strong>Promised delivery: {Math.ceil(delivery.median_promised_days)} days</strong>
              <p>
                This copies what Olist historically promised to {destination}. Real deliveries there took a median
                of {delivery.median_actual_days} days, so the promise is about{' '}
                {Math.round(delivery.median_promised_days - delivery.median_actual_days)} days longer than needed.
                Once the logistics models are trained, a data-driven promise replaces it.
              </p>
            </div>
          )}

          <Notice tone="warn" items={warnings} />
          <Notice tone="error" items={apiErrors} title={apiErrors.length ? 'The API rejected the order' : null} />
          {problems.length > 0 && <ul className="todo">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}

          <button className="btn btn-primary btn-block" disabled={problems.length > 0 || submitting} onClick={submit}>
            {submitting ? 'Registering…' : 'Register order'}
          </button>
        </aside>
      </div>
    </div>
  )
}
