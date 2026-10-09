// The order's journey drawn as a route with stops, from purchase to delivery.
// Each stop comes from the API's "timeline": done, current, pending, skipped or stopped.
import { dateTime } from '../lib/format'

export default function LifecycleRoute({ timeline, promisedDate }) {
  return (
    <ol className="route" aria-label="Order lifecycle">
      {timeline.map((step) => (
        <li key={step.key} className={`stop is-${step.state}`}>
          <span className="stop-dot" aria-hidden="true" />
          <span className="stop-label">{step.label}</span>
          <span className="stop-time">
            {step.at ? dateTime(step.at) : step.note || (step.state === 'current' ? 'Next step' : '')}
          </span>
          {step.at && step.note && step.state === 'stopped' && <span className="stop-note">{step.note}</span>}
          {step.key === 'delivered' && promisedDate && step.state !== 'skipped' && (
            <span className="stop-promise">Promised by {dateTime(promisedDate)}</span>
          )}
        </li>
      ))}
    </ol>
  )
}
