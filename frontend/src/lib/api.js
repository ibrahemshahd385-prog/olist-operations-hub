// One small wrapper around fetch, so every screen talks to the API the same way
// and every error reaches the screen as a readable list of messages.

export class ApiError extends Error {
  constructor(status, messages) {
    super(messages.join('\n'))
    this.status = status
    this.messages = messages
  }
}

// FastAPI returns errors in two shapes:
//   our business errors:   { detail: "text" }  or  { detail: ["text", ...] }
//   Pydantic validation:   { detail: [{ loc: ["body", "items", 0], msg: "..." }] }
function readErrors(body) {
  const detail = body?.detail
  if (!detail) return ['Unexpected error']
  if (typeof detail === 'string') return [detail]
  return detail.map((d) =>
    typeof d === 'string' ? d : `${(d.loc || []).filter((p) => p !== 'body').join(' › ')}: ${d.msg}`,
  )
}

async function request(method, path, body) {
  let res
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, ['Cannot reach the API. Is the backend running on port 8000?'])
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, readErrors(data))
  return data
}

const qs = (params) => {
  const clean = Object.entries(params).filter(([, v]) => v !== '' && v != null)
  return clean.length ? '?' + new URLSearchParams(clean).toString() : ''
}

export const api = {
  meta: () => request('GET', '/api/meta'),
  orders: (filters) => request('GET', '/api/orders' + qs(filters)),
  summary: () => request('GET', '/api/orders/summary'),
  order: (id) => request('GET', `/api/orders/${id}`),
  createOrder: (payload) => request('POST', '/api/orders', payload),
  runAction: (id, action, note) => request('POST', `/api/orders/${id}/actions/${action}`, { note: note || null }),
  issueInvoice: (id, sellerId) => request('POST', `/api/orders/${id}/invoices`, { seller_id: sellerId }),
  invoice: (id) => request('GET', `/api/invoices/${id}`),
  searchCustomers: (q) => request('GET', '/api/customers/search' + qs({ q })),
  searchSellers: (q) => request('GET', '/api/sellers/search' + qs({ q })),
  sellerProducts: (sellerId, q) => request('GET', `/api/sellers/${sellerId}/products` + qs({ q })),
  deliveryReference: (state) => request('GET', `/api/delivery-reference/${state}`),
  // Module 2: smart logistics
  logisticsOverview: () => request('GET', '/api/logistics/overview'),
  quote: (payload) => request('POST', '/api/logistics/quote', payload),
  atRisk: () => request('GET', '/api/logistics/at-risk'),
  // Module 3: seller performance
  sellersSummary: () => request('GET', '/api/sellers/summary'),
  sellers: (filters) => request('GET', '/api/sellers' + qs(filters)),
  seller: (id) => request('GET', `/api/sellers/${id}`),
  // Module 4: analytics & AI
  analyticsOverview: () => request('GET', '/api/analytics/overview'),
  reviewInsights: () => request('GET', '/api/analytics/reviews'),
  analyzeReview: (text) => request('POST', '/api/analytics/reviews/analyze', { text }),
}
