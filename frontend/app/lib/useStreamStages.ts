import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { StreamHandlers } from '@/api/stream'
import { STREAM_STAGES, type StreamOp } from '@/api/types'

/**
 * The stage state a panel shows while a streamed operation is running.
 *
 * The point of the websocket is that this is *reported* rather than guessed: the backend
 * announces the stage the work is actually in, so the list advances when the work moves
 * instead of when a stopwatch says it should. That is why there is no stage heuristic here -
 * every caller used to have one, and it showed "Scribing" while the server was still
 * embedding.
 *
 * Everything returned except `stages`/`stage`/`elapsed` is stable across renders, so a
 * caller may put `start`, `finish` and `handlers` in a dependency array without recreating
 * the callback that runs the request on every tick of the clock. That matters: `elapsed`
 * changes ten times a second, and a request callback that changed with it would restart
 * whatever it was attached to.
 */
export interface StageState {
  /** The stage keys this operation runs through, in order. */
  stages: readonly string[]
  /** Index into `stages`; equals `stages.length` once the operation has finished. */
  stage: number
  /** Real seconds since the operation started. */
  elapsed: number
  /** Call once before starting a request. */
  start: (op: StreamOp) => void
  /** Mark the work done, so the spinner stops even when the answer came from cache. */
  finish: () => void
  handlers: StreamHandlers
}

export function useStreamStages(): StageState {
  const [stages, setStages] = useState<readonly string[]>([])
  const [stage, setStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const started = useRef(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  // The list the stage keys are resolved against, read from the listener rather than
  // captured - otherwise every `onStages` reply would rebuild `handlers` and, through it,
  // the caller's request callback.
  const order = useRef<readonly string[]>([])

  const stopTimer = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  const start = useCallback(
    (op: StreamOp) => {
      stopTimer()
      // The operation's own list from the mirror, so the panel can draw the whole sequence
      // before the server's `start` frame lands. That frame replaces it a moment later with
      // the server's own copy, which is authoritative.
      const initial = STREAM_STAGES[op] ?? []
      order.current = initial
      setStages(initial)
      setStage(0)
      setElapsed(0)
      started.current = performance.now()
      // The elapsed readout keeps counting while a stage runs: the stage number says where
      // the work is, and the clock says how long it has been there.
      timer.current = setInterval(() => {
        setElapsed((performance.now() - started.current) / 1000)
      }, 100)
    },
    [stopTimer],
  )

  const finish = useCallback(() => {
    stopTimer()
    setStage(order.current.length)
  }, [stopTimer])

  const handlers: StreamHandlers = useMemo(
    () => ({
      onStages: (received) => {
        if (received.length === 0) return
        order.current = received
        setStages(received)
      },
      onStage: (key) => {
        // A key the list does not name is ignored rather than appended: the list is what the
        // operation said it would run through, and a stage outside it would shift every index
        // after it onto the wrong row. The gap is visible in development and is not a silent
        // misreport of where the work is.
        const index = order.current.indexOf(key)
        if (index >= 0) setStage(index)
      },
    }),
    [],
  )

  // A timer that outlived the component would be a leak and, worse, a `setState` on an
  // unmounted panel every 100ms. The operation may still be running - sharing the socket is
  // the point - but this panel has stopped caring.
  useEffect(() => stopTimer, [stopTimer])

  return { stages, stage, elapsed, start, finish, handlers }
}
