// Module 2: how the logistics models perform, which open orders need attention,
// and how the busiest delivery routes behave.
import { api } from '../lib/api'
import { date, number, pct, shortId } from '../lib/format'
import { navigate } from '../lib/router'
import { useAsync } from '../lib/useAsync'
import { DecileBars, PromiseByState } from '../components/charts'
import { ErrorNotice, Loading, Notice, RiskBadge, StatusBadge } from '../components/ui'

export default function LogisticsPage() {
  const overview = useAsync(() => api.logisticsOverview(), [])
  const queue = useAsync(() => api.atRisk(), [])

  if (overview.error) return <div className="page"><ErrorNotice error={overview.error} /></div>
  if (!overview.data) return <div className="page"><Loading /></div>

  const models = overview.data.models
  if (!models) {
    return (
      <div className="page">
        <h1>Smart logistics</h1>
        <Notice tone="warn" title="The models are not trained yet">
          <p>In the backend folder, run <code>python -m scripts.train_models</code> (about 15 seconds), then reload this page.
            Until then, orders use Olist’s historical promise.</p>
        </Notice>
      </div>
    )
  }
  const { eta, risk, freight } = models.metrics
  const states = eta.by_state.slice(0, 12)
  const daysSaved = eta.olist_promise_mean_days - eta.model_promise_mean_days

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Smart logistics</h1>
          <p className="lede">
            Three models trained on orders up to March 2018 and tested on {number(eta.test_orders)} orders from
            June to August 2018 that they never saw. Every number on this page comes from that test.
          </p>
        </div>
      </header>

      <section className="results" aria-label="Model results">
        <div className="result">
          <h2>Delivery promise</h2>
          <p className="result-figure">{eta.model_promise_mean_days} days <span>instead of {eta.olist_promise_mean_days}</span></p>
          <p>
            The model promises {daysSaved.toFixed(1)} days less on average and still keeps {pct(eta.model_on_time, 1)} of
            its promises (Olist kept {pct(eta.olist_on_time, 1)}). A shorter, honest date helps the customer decide to buy.
          </p>
        </div>
        <div className="result">
          <h2>Late-delivery risk</h2>
          <p className="result-figure">{pct(risk.top10_capture)} <span>of late orders caught</span></p>
          <p>
            by looking only at the riskiest 10% of orders. In that group {pct(risk.top10_late_rate, 1)} arrive late,
            against {pct(risk.late_rate, 1)} overall (ROC AUC {risk.roc_auc}). That is where a nudge to the seller pays off.
          </p>
        </div>
        <div className="result">
          <h2>Freight check</h2>
          <p className="result-figure">R$ {freight.mae.toFixed(2)} <span>average error</span></p>
          <p>
            per item, against R$ {freight.baseline_mae.toFixed(2)} when using the average price of the route. Used in the
            order form to flag freight that looks too high for the weight, size and distance.
          </p>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Promise against reality, by state</h2>
        <p className="panel-intro">The 12 busiest destination states in the test months. The gap between the green dot and the orange one is how much longer than needed Olist made customers wait.</p>
        <PromiseByState rows={states} />
      </section>

      <div className="two-col">
        <section className="panel">
          <h2 className="panel-title">Late deliveries by risk group</h2>
          <p className="panel-intro">Test orders sorted by the model’s risk score and cut into ten equal groups.</p>
          <DecileBars values={risk.late_rate_by_decile} base={risk.late_rate} />
        </section>

        <section className="panel">
          <h2 className="panel-title">Busiest delivery routes</h2>
          <p className="panel-intro">Seller state to customer state, all delivered orders in the dataset.</p>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Route</th><th className="num">Orders</th><th className="num">Avg days</th><th>Late</th></tr></thead>
              <tbody>
                {overview.data.lanes.map((l) => (
                  <tr key={l.seller_state + l.customer_state}>
                    <td className="strong">{l.seller_state} to {l.customer_state}</td>
                    <td className="num">{number(l.orders)}</td>
                    <td className="num">{l.avg_days}</td>
                    <td>
                      <span className="meter" aria-hidden="true"><span style={{ width: `${Math.min(100, l.late_rate * 500)}%` }} /></span>
                      {pct(l.late_rate, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel">
        <h2 className="panel-title">Open orders by late risk</h2>
        <p className="panel-intro">Orders registered in this system that are not delivered yet, riskiest first.</p>
        {queue.data && queue.data.length === 0 && (
          <p className="muted">No open orders. Register one and its risk score appears here.</p>
        )}
        {queue.data && queue.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Order</th><th>Status</th><th>Ship to</th><th>Promised</th><th>Risk</th><th>Why</th></tr></thead>
              <tbody>
                {queue.data.map((o) => (
                  <tr key={o.order_id} className="row-link" tabIndex={0} onClick={() => navigate(`/orders/${o.order_id}`)}
                      onKeyDown={(e) => e.key === 'Enter' && navigate(`/orders/${o.order_id}`)}>
                    <td className="id">{shortId(o.order_id)}</td>
                    <td><StatusBadge status={o.order_status} label={o.status_label} /></td>
                    <td className="cap">{o.customer_city}, {o.customer_state}</td>
                    <td>{date(o.order_estimated_delivery_date)}
                      <small className="block muted">{o.days_left >= 0 ? `${o.days_left} days left` : `${-o.days_left} days overdue`}</small></td>
                    <td><RiskBadge level={o.risk_level} probability={o.late_risk} /></td>
                    <td className="muted">{o.risk_reasons[0] || 'No specific warning'}
                      {o.risk_reasons.length > 1 && <small className="block">and {o.risk_reasons.length - 1} more</small>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel how">
        <h2 className="panel-title">How the models avoid fooling themselves</h2>
        <ul>
          <li><strong>Split by time, never at random.</strong> Train up to March 2018, tune in April and May, test on June to August. A random split would let the model learn from orders placed after the ones it is tested on.</li>
          <li><strong>Only what is known at checkout.</strong> Route distance, weight and size, payment method, the seller’s track record up to that day. Nothing that happens after the order is placed.</li>
          <li><strong>Anchored on how the network is doing lately.</strong> Deliveries got about 25% faster during 2018. The model predicts how much faster or slower an order is than the last 30 days of deliveries, so it follows the network instead of remembering old speeds.</li>
          <li><strong>A safety margin chosen on purpose.</strong> The promise adds a margin tuned so that 95% of orders arrive on time in the tuning months.</li>
        </ul>
        <p className="muted">Trained {models.trained_at} with scikit-learn {models.sklearn_version}. Live orders use the network figures up to {date(models.network_as_of)}.</p>
      </section>
    </div>
  )
}
