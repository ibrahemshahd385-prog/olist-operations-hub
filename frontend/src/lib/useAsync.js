// Load data for a screen: gives back { data, error, loading, reload }.
// "deps" works like useEffect: when a filter changes, the data reloads.
import { useCallback, useEffect, useRef, useState } from 'react'

export function useAsync(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const callId = useRef(0)

  const run = useCallback(() => {
    const id = ++callId.current
    setState((s) => ({ ...s, loading: true, error: null }))
    loader()
      .then((data) => id === callId.current && setState({ data, error: null, loading: false }))
      .catch((error) => id === callId.current && setState({ data: null, error, loading: false }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(run, [run])
  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) }
}
