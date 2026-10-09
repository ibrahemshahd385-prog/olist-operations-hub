// Formatting helpers. Money is shown the Brazilian way (R$ 1.234,56)
// because every value in the dataset is in reais.

const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
const int = new Intl.NumberFormat('en-US')

export const money = (v) => (v == null ? '—' : brl.format(v))
export const number = (v) => (v == null ? '—' : int.format(v))
export const shortId = (id) => (id ? id.slice(0, 8) : '—')
export const pct = (v, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2017-10-02 10:56:33" -> "2 Oct 2017, 10:56" (timestamps are stored as plain text)
export function dateTime(ts, { time = true } = {}) {
  if (!ts) return '—'
  const [d, t = ''] = ts.split(' ')
  const [y, m, day] = d.split('-')
  const base = `${Number(day)} ${MONTHS[Number(m) - 1]} ${y}`
  return time && t && t !== '00:00:00' ? `${base}, ${t.slice(0, 5)}` : base
}

export const date = (ts) => dateTime(ts, { time: false })

// The NF-e access key is always printed in blocks of 4 digits
export const accessKeyBlocks = (key) => (key ? key.match(/.{1,4}/g).join(' ') : '')

export const STATUS_TONE = {
  created: 'wait',
  approved: 'info',
  processing: 'info',
  invoiced: 'info',
  shipped: 'transit',
  delivered: 'ok',
  canceled: 'bad',
  unavailable: 'bad',
}

export const PAYMENT_LABELS = {
  credit_card: 'Credit card',
  boleto: 'Boleto',
  voucher: 'Voucher',
  debit_card: 'Debit card',
  not_defined: 'Not defined',
}
