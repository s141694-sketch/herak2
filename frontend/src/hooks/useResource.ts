import { useCallback, useEffect, useState } from 'react'

import { errorCode, http } from '../api'

export interface Resource<T> {
  data: T | undefined
  error: string | null
  loading: boolean
  reload: () => void
}

/** GETs `path` (skipped when null) and re-fetches on reload(). */
export function useResource<T>(path: string | null): Resource<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (path === null) return
    let alive = true
    setLoading(true)
    http.get<T>(path).then(
      (body) => {
        if (!alive) return
        setData(body)
        setError(null)
        setLoading(false)
      },
      (caught: unknown) => {
        if (!alive) return
        setError(errorCode(caught))
        setLoading(false)
      },
    )
    return () => {
      alive = false
    }
  }, [path, tick])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return { data, error, loading, reload }
}

/** Runs one action at a time and keeps its error code for display. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (caught) {
      setError(errorCode(caught))
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])

  return { busy, error, run, clearError: () => setError(null) }
}
