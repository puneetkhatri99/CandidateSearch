import { useEffect, useState } from 'react'

/** Whole seconds since the component mounted, ticking once a second. */
export function useElapsedSeconds() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])
  return seconds
}
