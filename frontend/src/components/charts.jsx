// Small hand-made SVG charts (no chart library to install or learn).
// Every chart has a legend or a title naming what it shows, a hover tooltip,
// and a table version for anyone who cannot read the colours.
import { useRef, useState } from 'react'

export const SERIES = {
  actual: '#1baf7a',   // what really happened
  model: '#1f3bd8',    // our model
  olist: '#eb6834',    // Olist's original promise
}

function useTooltip() {
  const ref = useRef(null)
  const [tip, setTip] = useState(null)
  const show = (e, content) => {
    const box = ref.current.getBoundingClientRect()
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content })
  }
  const node = tip && (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }} role="status">{tip.content}</div>
  )
  return { ref, show, hide: () => setTip(null), node }
}

export function Legend({ items }) {
  return (
    <ul className="legend">
      {items.map((i) => (
        <li key={i.label}><span className="legend-dot" style={{ background: i.color }} />{i.label}</li>
      ))}
    </ul>
  )
}

// One row per state: three dots on a shared day axis.
export function PromiseByState({ rows }) {
  const tip = useTooltip()
  const W = 720, rowH = 30, left = 44, right = 24, top = 8, bottom = 34
  const H = top + rows.length * rowH + bottom
  const maxDays = Math.ceil(Math.max(...rows.map((r) => Math.max(r.olist_promise, r.model_promise))) / 5) * 5
  const x = (d) => left + (d / maxDays) * (W - left - right)
  const ticks = Array.from({ length: maxDays / 5 + 1 }, (_, i) => i * 5)

  return (
    <div className="chart" ref={tip.ref}>
      <Legend items={[
        { label: 'Real delivery (median)', color: SERIES.actual },
        { label: 'Model promise', color: SERIES.model },
        { label: 'Olist promise', color: SERIES.olist },
      ]} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Delivery promise versus real delivery time by state">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={H - bottom} className="grid" />
            <text x={x(t)} y={H - bottom + 16} className="axis" textAnchor="middle">{t}</text>
          </g>
        ))}
        <text x={W - right} y={H - 4} className="axis" textAnchor="end">days after purchase</text>
        {rows.map((r, i) => {
          const cy = top + i * rowH + rowH / 2
          const lo = Math.min(r.actual_median, r.model_promise, r.olist_promise)
          const hi = Math.max(r.actual_median, r.model_promise, r.olist_promise)
          return (
            <g key={r.customer_state}>
              <text x={left - 10} y={cy + 4} className="axis-strong" textAnchor="end">{r.customer_state}</text>
              <line x1={x(lo)} x2={x(hi)} y1={cy} y2={cy} className="track" />
              {[['actual_median', SERIES.actual], ['olist_promise', SERIES.olist], ['model_promise', SERIES.model]].map(([k, c]) => (
                <circle key={k} cx={x(r[k])} cy={cy} r="5.5" fill={c} className="dot" />
              ))}
              <rect x={left} y={cy - rowH / 2} width={W - left - right} height={rowH} fill="transparent"
                onMouseMove={(e) => tip.show(e, (
                  <>
                    <strong>{r.customer_state}</strong>, {r.orders.toLocaleString('en-US')} orders
                    <br />Real delivery: {r.actual_median.toFixed(1)} days (median)
                    <br />Model promise: {r.model_promise.toFixed(1)} days, kept {(r.model_on_time * 100).toFixed(0)}%
                    <br />Olist promise: {r.olist_promise.toFixed(1)} days, kept {(r.olist_on_time * 100).toFixed(0)}%
                  </>
                ))}
                onMouseLeave={tip.hide} />
            </g>
          )
        })}
      </svg>
      {tip.node}
      <details className="chart-table">
        <summary>Show as a table</summary>
        <table className="table">
          <thead><tr><th>State</th><th className="num">Orders</th><th className="num">Real (median)</th>
            <th className="num">Model promise</th><th className="num">Kept</th><th className="num">Olist promise</th><th className="num">Kept</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.customer_state}><td>{r.customer_state}</td><td className="num">{r.orders.toLocaleString('en-US')}</td>
                <td className="num">{r.actual_median.toFixed(1)}</td><td className="num">{r.model_promise.toFixed(1)}</td>
                <td className="num">{(r.model_on_time * 100).toFixed(1)}%</td><td className="num">{r.olist_promise.toFixed(1)}</td>
                <td className="num">{(r.olist_on_time * 100).toFixed(1)}%</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

// Late-delivery rate in each tenth of orders, sorted from riskiest to safest.
export function DecileBars({ values, base }) {
  const tip = useTooltip()
  const W = 460, H = 250, left = 40, right = 12, top = 22, bottom = 40
  const maxV = Math.ceil((Math.max(...values, base) * 100) / 5) * 5 / 100
  const slot = (W - left - right) / values.length
  const barW = Math.min(24, slot * 0.6)
  const y = (v) => top + (1 - v / maxV) * (H - top - bottom)
  const ticks = Array.from({ length: Math.round(maxV * 100 / 5) + 1 }, (_, i) => i * 0.05)

  const bar = (v, i) => {
    const x0 = left + i * slot + (slot - barW) / 2, y0 = y(v), yb = y(0), r = Math.min(4, yb - y0)
    return `M${x0},${yb} V${y0 + r} Q${x0},${y0} ${x0 + r},${y0} H${x0 + barW - r} Q${x0 + barW},${y0} ${x0 + barW},${y0 + r} V${yb} Z`
  }
  return (
    <div className="chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Late delivery rate by risk group, riskiest first">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={left - 8} y={y(t) + 4} className="axis" textAnchor="end">{Math.round(t * 100)}%</text>
          </g>
        ))}
        {values.map((v, i) => (
          <g key={i}>
            <path d={bar(v, i)} fill={SERIES.model} />
            <text x={left + i * slot + slot / 2} y={H - bottom + 16} className="axis" textAnchor="middle">{i + 1}</text>
            <rect x={left + i * slot} y={top} width={slot} height={H - top - bottom} fill="transparent"
              onMouseMove={(e) => tip.show(e, <><strong>Group {i + 1}</strong>{i === 0 ? ' (riskiest 10%)' : i === 9 ? ' (safest 10%)' : ''}<br />{(v * 100).toFixed(1)}% arrived late</>)}
              onMouseLeave={tip.hide} />
          </g>
        ))}
        <text x={left + slot / 2} y={y(values[0]) - 6} className="axis-strong" textAnchor="middle">{(values[0] * 100).toFixed(1)}%</text>
        <line x1={left} x2={W - right} y1={y(base)} y2={y(base)} className="ref-line" />
        <text x={W - right} y={y(base) - 6} className="axis" textAnchor="end">average {(base * 100).toFixed(1)}%</text>
        <text x={left} y={H - 4} className="axis">riskiest tenth</text>
        <text x={W - right} y={H - 4} className="axis" textAnchor="end">safest tenth</text>
      </svg>
      {tip.node}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Module 3 & 4 charts (single series: one colour, the title names it)
// ---------------------------------------------------------------------------

const roundedBar = (x0, y0, w, yb, r = 4) => {
  const rr = Math.max(0, Math.min(r, (yb - y0), w / 2))
  return `M${x0},${yb} V${y0 + rr} Q${x0},${y0} ${x0 + rr},${y0} H${x0 + w - rr} Q${x0 + w},${y0} ${x0 + w},${y0 + rr} V${yb} Z`
}

// Round axis: a step of 1, 2 or 5 x 10^n, at most 5 steps, so ticks read as round numbers.
const niceScale = (v, steps = 5) => {
  if (!(v > 0)) return { max: 1, ticks: [0, 1] }
  const raw = v / steps
  const p = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * p).find((m) => m >= raw)
  const n = Math.ceil(v / step)
  return { max: n * step, ticks: Array.from({ length: n + 1 }, (_, i) => i * step) }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monthLabel = (ym) => { const [y, m] = ym.split('-'); return `${MONTHS[Number(m) - 1]} ${y.slice(2)}` }

// Vertical bars over months. `format` turns a value into text for axis and tooltip.
export function MonthlyBars({ rows, valueKey, format = (v) => v, label, extra }) {
  const tip = useTooltip()
  const W = 720, H = 240, left = 56, right = 8, top = 14, bottom = 30
  const scale = niceScale(Math.max(...rows.map((r) => r[valueKey] || 0)))
  const maxV = scale.max
  const slot = (W - left - right) / Math.max(1, rows.length)
  const barW = Math.max(2, Math.min(22, slot - 2))
  const y = (v) => top + (1 - v / maxV) * (H - top - bottom)
  const ticks = scale.ticks
  const every = Math.ceil(rows.length / 9)
  return (
    <div className="chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={left - 8} y={y(t) + 4} className="axis" textAnchor="end">{format(t, true)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x0 = left + i * slot + (slot - barW) / 2
          const v = r[valueKey] || 0
          return (
            <g key={r.month}>
              {v > 0 && <path d={roundedBar(x0, y(v), barW, y(0))} fill={SERIES.model} />}
              {i % every === 0 && <text x={x0 + barW / 2} y={H - bottom + 16} className="axis" textAnchor="middle">{monthLabel(r.month)}</text>}
              <rect x={left + i * slot} y={top} width={slot} height={H - top - bottom} fill="transparent"
                onMouseMove={(e) => tip.show(e, <><strong>{monthLabel(r.month)}</strong><br />{format(v)}{extra && extra(r)}</>)}
                onMouseLeave={tip.hide} />
            </g>
          )
        })}
      </svg>
      {tip.node}
    </div>
  )
}

// Share of revenue held by the top X% of sellers, with the 10% point marked.
export function ParetoCurve({ points, mark = 10 }) {
  const tip = useTooltip()
  const W = 460, H = 260, left = 44, right = 16, top = 16, bottom = 40
  const x = (p) => left + (p / 100) * (W - left - right)
  const y = (v) => top + (1 - v) * (H - top - bottom)
  const path = 'M' + [{ sellers_pct: 0, revenue_share: 0 }, ...points].map((p) => `${x(p.sellers_pct)},${y(p.revenue_share)}`).join(' L')
  const m = points.find((p) => p.sellers_pct === mark)
  const [hover, setHover] = useState(null)
  return (
    <div className="chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Revenue share by share of sellers: the top ${mark}% hold ${Math.round(m.revenue_share * 100)}%`}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect()
          const pct = Math.round(((e.clientX - box.left) / box.width * W - left) / (W - left - right) * 100)
          const p = points.find((q) => q.sellers_pct === Math.min(100, Math.max(1, pct)))
          setHover(p)
          tip.show(e, <><strong>Top {p.sellers_pct}% of sellers</strong><br />{Math.round(p.revenue_share * 100)}% of revenue</>)
        }}
        onMouseLeave={() => { setHover(null); tip.hide() }}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={left - 8} y={y(t) + 4} className="axis" textAnchor="end">{t * 100}%</text>
          </g>
        ))}
        {[0, 25, 50, 75, 100].map((t) => (
          <text key={t} x={x(t)} y={H - bottom + 16} className="axis" textAnchor="middle">{t}%</text>
        ))}
        <text x={W - right} y={H - 4} className="axis" textAnchor="end">share of sellers, biggest first</text>
        <path d={path} fill="none" stroke={SERIES.model} strokeWidth="2" strokeLinejoin="round" />
        <line x1={x(mark)} x2={x(mark)} y1={y(m.revenue_share)} y2={y(0)} className="ref-line" strokeDasharray="3 3" />
        <circle cx={x(mark)} cy={y(m.revenue_share)} r="5" fill={SERIES.model} className="dot" />
        <text x={x(mark) + 10} y={y(m.revenue_share) + 16} className="axis-strong">
          Top {mark}% of sellers: {Math.round(m.revenue_share * 100)}% of revenue
        </text>
        {hover && <circle cx={x(hover.sellers_pct)} cy={y(hover.revenue_share)} r="4" fill={SERIES.model} className="dot" />}
      </svg>
      {tip.node}
    </div>
  )
}

// Horizontal bars with the label on the left and the value on the right.
export function HBars({ rows, format = (v) => v, max, label, note }) {
  const top = max ?? Math.max(...rows.map((r) => r.value), 0)
  return (
    <ul className="hbars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.key ?? r.label} title={r.title}>
          <span className="hbar-label">{r.label}</span>
          <span className="hbar-track"><span className="hbar-fill" style={{ width: `${top ? (r.value / top) * 100 : 0}%` }} /></span>
          <span className="hbar-value">{format(r.value)}{note && <small> {note(r)}</small>}</span>
        </li>
      ))}
    </ul>
  )
}

// Vertical bars for ordered categories (e.g. delivery delay buckets), with an
// optional reference line (e.g. the overall average).
export function ColumnBars({ rows, format = (v) => v, label, refValue, refLabel, maxValue, detail }) {
  const tip = useTooltip()
  const W = 720, H = 250, left = 40, right = 8, top = 24, bottom = 34
  const scale = niceScale(maxValue ?? Math.max(...rows.map((r) => r.value)))
  const maxV = scale.max
  const slot = (W - left - right) / rows.length
  const barW = Math.min(46, slot * 0.62)
  const y = (v) => top + (1 - v / maxV) * (H - top - bottom)
  const ticks = scale.ticks
  return (
    <div className="chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={left - 8} y={y(t) + 4} className="axis" textAnchor="end">{format(t, true)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x0 = left + i * slot + (slot - barW) / 2
          return (
            <g key={r.label}>
              <path d={roundedBar(x0, y(r.value), barW, y(0))} fill={SERIES.model} />
              <text x={x0 + barW / 2} y={y(r.value) - 6} className="axis-strong" textAnchor="middle">{format(r.value)}</text>
              <text x={x0 + barW / 2} y={H - bottom + 16} className="axis" textAnchor="middle">{r.label}</text>
              <rect x={left + i * slot} y={top} width={slot} height={H - top - bottom} fill="transparent"
                onMouseMove={(e) => tip.show(e, <><strong>{r.label}</strong><br />{format(r.value)}{detail && detail(r)}</>)}
                onMouseLeave={tip.hide} />
            </g>
          )
        })}
        {refValue != null && (
          <g>
            <line x1={left} x2={W - right} y1={y(refValue)} y2={y(refValue)} className="ref-line" strokeDasharray="4 3" />
            <text x={W - right} y={y(refValue) - 6} className="axis" textAnchor="end">{refLabel}</text>
          </g>
        )}
      </svg>
      {tip.node}
    </div>
  )
}
