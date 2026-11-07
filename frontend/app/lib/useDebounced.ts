/**
 * Settling a value, or a call, until the typing stops.
 *
 * The Rules tab's ask box drives three things at once, two of which are requests - a vector
 * search and a model call. Firing either on every keystroke would triple the cost of typing a
 * question and leave several responses racing to fill one panel, so both wait for a pause.
 *
 * The third lane - the keyword filter - is deliberately not debounced, because it is
 * synchronous and its whole value is that it answers while the other two are still waiting.
 * That is why this debounces the *call* rather than the query: there is no settled value
 * anyone wants.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A debounced wrapper around a callback.
 *
 * `pending` is true from the keystroke that scheduled the call until the call runs, which is
 * what lets the UI show a spinner for the *whole* wait rather than only the request - a
 * pause that looks like nothing happening is the thing a debounce gets wrong.
 *
 * `cancel()` drops a scheduled call without running it. The ask button uses it so an
 * explicit request does not race its own debounce and issue the same work twice.
 */
export function useDebouncedCallback<A extends unknown[]>(
  fn: (...args: A) => void,
  delay: number,
) {
  // The callback is read through a ref updated in an effect, so `call` keeps a stable
  // identity without capturing a stale closure - and nothing is written to a ref during
  // render.
  const latest = useRef(fn)
  useEffect(() => {
    latest.current = fn
  })

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [pending, setPending] = useState(false)

  const cancel = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setPending(false)
  }, [])

  useEffect(() => cancel, [cancel])

  const call = useCallback(
    (...args: A) => {
      if (timer.current) clearTimeout(timer.current)
      setPending(true)
      timer.current = setTimeout(() => {
        timer.current = null
        // Cleared before the work starts, because the caller's own loading flag takes over
        // from here and two spinners for one wait would flicker.
        setPending(false)
        latest.current(...args)
      }, delay)
    },
    [delay],
  )

  return { call, cancel, pending }
}
