// A one-time message carried from one screen to the next
// (e.g. "Order registered" + warnings, shown on the order page after redirect).
let pending = null

export const setFlash = (message) => {
  pending = message
}

export const takeFlash = () => {
  const m = pending
  pending = null
  return m
}
