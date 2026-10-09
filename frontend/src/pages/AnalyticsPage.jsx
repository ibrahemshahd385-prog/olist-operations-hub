// Module 4: the management view, and what 43k written reviews say.
import { useState } from 'react'
import { api } from '../lib/api'
import { money, number, pct, PAYMENT_LABELS, shortId } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { ColumnBars, HBars, MonthlyBars } from '../components/charts'
import { ErrorNotice, Loading, Notice } from '../components/ui'

const EXAMPLES = [
  'Comprei dois produtos e só chegou um. Já mandei email e ninguém respondeu.',
  'Chegou antes do prazo, muito bem embalado. Recomendo!',
  'Produto bom, mas veio sem a nota fiscal.',
]

function ReviewAnalyzer() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run(value = text) {
    if (!value.trim()) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.analyzeReview(value))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="analyzer">
      <label className="field">
        <span className="field-label">Paste a review in Portuguese</span>
        <textarea className="input" rows={3} lang="pt-BR" value={text} onChange={(e) => setText(e.target.value)}
                  placeholder="Ex.: O produto chegou quebrado e ninguém responde." />
      </label>
      <div className="actions plain">
        <button className="btn btn-primary" disabled={!text.trim() || busy} onClick={() => run()}>
          {busy ? 'Reading…' : 'Analyze review'}
        </button>
        <span className="hint">Or try:</span>
        {EXAMPLES.map((ex, i) => (
          <button key={i} className="btn btn-quiet" onClick={() => { setText(ex); run(ex) }}>Example {i + 1}</button>
        ))}
      </div>
      <ErrorNotice error={error} />
      {result && (
        <div className="analysis">
          {result.sentiment != null && (
            <div className="sentiment">
              <span className="field-label">Reads as negative</span>
              <span className="hbar-track"><span className={'hbar-fill' + (result.sentiment >= 0.5 ? ' is-bad' : '')}
                style={{ width: `${result.sentiment * 100}%` }} /></span>
              <strong>{pct(result.sentiment, 0)}</strong>
            </div>
          )}
          <p><span className="field-label">Topics </span>
            {result.topics.length ? result.topics.map((t) => <span key={t.key} className="topic">{t.label}</span>) : <span className="muted">none of the known topics</span>}
          </p>
          {result.drivers.length > 0 && (
            <p><span className="field-label">Words that weighed most </span>
              {result.drivers.map((d) => (
                <span key={d.term} className={`term term-${d.push}`}>{d.term} <small>{d.push === 'negative' ? 'negative' : 'positive'}</small></span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function AnalyticsPage() {
  const ov = useAsync(() => api.analyticsOverview(), [])
  const rv = useAsync(() => api.reviewInsights(), [])

  if (ov.error) return <div className="page"><ErrorNotice error={ov.error} /></div>
  if (!ov.data) return <div className="page"><Loading /></div>
  const { kpi, monthly, delay_vs_review: delay, categories, states, payments } = ov.data
  const r = rv.data
  const early = delay[0].avg_review
  const worst = Math.min(...delay.map((d) => d.avg_review))

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Analytics & AI</h1>
          <p className="lede">
            The business in one page, from {number(kpi.orders)} orders placed between September 2016 and October 2018,
            and what customers wrote in their reviews, read by a text model.
          </p>
        </div>
      </header>

      <dl className="kpis five">
        <div className="kpi"><dt>Product revenue</dt><dd>{money(kpi.gmv)}<small>{number(kpi.orders)} orders</small></dd></div>
        <div className="kpi"><dt>Average order</dt><dd>{money(kpi.avg_ticket)}<small>products only</small></dd></div>
        <div className="kpi"><dt>Delivered on time</dt><dd>{pct(kpi.on_time_rate, 1)}<small>against Olist’s own promise</small></dd></div>
        <div className="kpi"><dt>Average review</dt><dd>{kpi.avg_review.toFixed(2)}<small>out of 5 stars</small></dd></div>
        <div className="kpi"><dt>Customers who came back</dt><dd>{pct(kpi.repeat_rate, 1)}<small>of {number(kpi.customers)} customers</small></dd></div>
      </dl>

      <section className="panel">
        <h2 className="panel-title">Revenue by month</h2>
        <p className="panel-intro">
          From {money(monthly[0].revenue)} in January 2017 to {money(monthly[12].revenue)} in January 2018, then flat through
          2018. The November 2017 peak is Black Friday.
        </p>
        <MonthlyBars rows={monthly} valueKey="revenue" label="Product revenue by month"
                     format={(v, axis) => axis ? (v >= 1e6 ? `R$ ${(v / 1e6).toFixed(1)}M` : v === 0 ? 'R$ 0' : `R$ ${Math.round(v / 1000)}k`) : money(v)}
                     extra={(row) => <><br />{number(row.orders)} orders</>} />
      </section>

      <section className="panel">
        <h2 className="panel-title">One late delivery costs the review</h2>
        <p className="panel-intro">
          Average review by when the order arrived compared with the promised date. Early or on time, reviews sit near {early.toFixed(1)}.
          From four days late they fall to around {worst.toFixed(1)}, and more than half are one-star. This is why the delivery promise
          (Module 2) and seller shipping speed (Module 3) matter so much.
        </p>
        <ColumnBars rows={delay.map((d) => ({ label: d.bucket, value: d.avg_review, orders: d.orders, one: d.one_star }))}
                    maxValue={5} format={(v, axis) => (axis ? v.toFixed(0) : v.toFixed(2))} refValue={kpi.avg_review}
                    refLabel={`overall ${kpi.avg_review.toFixed(2)}`} label="Average review by delivery delay"
                    detail={(row) => <><br />{number(row.orders)} orders, {pct(row.one, 0)} one-star</>} />
      </section>

      {/* ---------------- review intelligence ---------------- */}
      <h2 className="section-title big">What customers write</h2>
      {rv.error && <ErrorNotice error={rv.error} />}
      {r && !r.available && (
        <Notice tone="warn" title="The review model is not trained yet">
          <p>In the backend folder, run <code>python -m scripts.train_models</code>, then reload this page.</p>
        </Notice>
      )}
      {r && r.available && (
        <>
          <div className="two-col first">
            <section className="panel">
              <h2 className="panel-title">What the {number(r.negative_reviews)} negative reviews are about</h2>
              <p className="panel-intro">
                Share of 1–2 star reviews that mention each topic (a review can mention several).
                {' '}{pct(r.delivery_share_of_negative, 0)} talk about an order that did not arrive or arrived late.
              </p>
              <HBars label="Complaint topics in negative reviews"
                     rows={r.topics.filter((t) => t.complaint).sort((a, b) => b.negative_share - a.negative_share)
                       .map((t) => ({ key: t.key, label: t.label, value: t.negative_share }))}
                     format={(v) => pct(v, 1)} />
              <p className="muted small">{pct(r.negative_no_topic, 0)} of negative reviews match none of the topics; the sentiment model still reads them.</p>
            </section>
            <section className="panel">
              <h2 className="panel-title">The text model</h2>
              {r.model && (
                <>
                  <p>
                    Trained on {number(r.model.train_reviews)} reviews and tested on {number(r.model.test_reviews)} written
                    from {r.model.test_from}. It tells a negative review from a positive one
                    {' '}{pct(r.model.accuracy, 1)} of the time (ROC AUC {r.model.roc_auc}).
                  </p>
                  <p className="field-label">Words that make a review read negative</p>
                  <p>{r.model.negative_words.slice(0, 10).map((w) => <span key={w} className="term term-negative">{w}</span>)}</p>
                  <p className="field-label">Words that make it read positive</p>
                  <p>{r.model.positive_words.slice(0, 10).map((w) => <span key={w} className="term term-positive">{w}</span>)}</p>
                </>
              )}
            </section>
          </div>

          <section className="panel">
            <h2 className="panel-title">Hidden complaints: {number(r.hidden_complaints)} happy ratings with unhappy words</h2>
            <p className="panel-intro">
              Reviews with 4–5 stars whose text the model reads as a complaint. A star average never shows these customers,
              but many of them still have a problem to solve.
            </p>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Stars</th><th>What the customer wrote</th><th>Topics</th><th className="num">Negative</th><th>Order</th></tr></thead>
                <tbody>
                  {r.hidden_examples.map((h) => (
                    <tr key={h.order_id + h.message}>
                      <td className="stars-cell">{'★'.repeat(h.stars)}</td>
                      <td lang="pt-BR">{h.title && <strong>{h.title}. </strong>}{h.message}</td>
                      <td className="muted">{h.topics.join(', ') || '—'}</td>
                      <td className="num">{pct(h.negative, 0)}</td>
                      <td><a className="id" href={`#/orders/${h.order_id}`}>{shortId(h.order_id)}</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Try the model</h2>
            <ReviewAnalyzer />
          </section>
        </>
      )}

      {/* ---------------- where the business comes from ---------------- */}
      <div className="two-col">
        <section className="panel">
          <h2 className="panel-title">Top categories by revenue</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Category</th><th className="num">Revenue</th><th className="num">Orders</th><th className="num">Review</th></tr></thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.category}><td className="cap">{c.category.replaceAll('_', ' ')}</td><td className="num">{money(c.revenue)}</td>
                    <td className="num">{number(c.orders)}</td><td className="num">{c.avg_review?.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel">
          <h2 className="panel-title">Top customer states</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>State</th><th className="num">Orders</th><th className="num">Avg days</th><th className="num">Late</th></tr></thead>
              <tbody>
                {states.map((s) => (
                  <tr key={s.state}><td className="strong">{s.state}</td><td className="num">{number(s.orders)}</td>
                    <td className="num">{s.avg_days}</td><td className="num">{pct(s.late_rate, 1)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel">
        <h2 className="panel-title">How customers pay</h2>
        <p className="panel-intro">Share of the money paid. Card buyers split their payment into {payments[0]?.avg_installments} installments on average.</p>
        <HBars label="Payment mix" rows={payments.map((p) => ({ key: p.payment_type, label: PAYMENT_LABELS[p.payment_type], value: p.share, n: p.payments }))}
               format={(v) => pct(v, 1)} note={(row) => `${number(row.n)} payments`} max={1} />
      </section>
    </div>
  )
}
