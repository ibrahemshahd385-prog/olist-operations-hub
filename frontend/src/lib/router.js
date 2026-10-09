// A tiny hash router (#/orders/123). Enough for this app, and easy to read:
// the URL after "#" is matched against patterns like "/orders/:id".
import { useEffect, useState } from 'react'

export function useHashPath() {
  const read = () => window.location.hash.replace(/^#/, '') || '/orders'
  const [path, setPath] = useState(read)
  useEffect(() => {
    const onChange = () => {
      setPath(read())
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return path
}

// match('/orders/:id', '/orders/abc') -> { id: 'abc' }   (null when it does not match)
export function match(pattern, path) {
  const p = pattern.split('/')
  const a = path.split('?')[0].split('/')
  if (p.length !== a.length) return null
  const params = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(a[i])
    else if (p[i] !== a[i]) return null
  }
  return params
}

export const navigate = (path) => {
  window.location.hash = path
}
