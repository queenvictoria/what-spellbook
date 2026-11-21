import { apiBase, readCharacter } from '@/lib/browserSettings'

import { api, ApiError } from './client'
import type { Answer, Generation, StreamOp, StreamRequest } from './types'

/**
 * One websocket, shared by every panel, carrying the operations that take seconds.
 *
 * The HTTP routes are still the contract: each of these ops has a route that returns the
 * same payload, and a failure to open a socket here falls back to it. What the socket adds
 * is the work in progress - the service announces its stages, and the stage a panel shows
 * is therefore the one the work is actually in rather than a guess from a stopwatch.
 *
 * Three things are deliberate:
 *
 * - **One connection for the whole app.** A socket per panel would pay a handshake for
 *   every book opened, and switching tabs would tear one down mid-run. Requests are
 *   multiplexed by `id` instead, so a recommendation and a rules question can be in flight
 *   at once and each panel only sees its own frames.
 * - **A request outlives its caller only if nothing cancels it.** `open()` returns a
 *   session whose `run()` resolves with the payload; a panel that unmounts simply stops
 *   listening, and the backend cancels when the *socket* closes. That is the intended
 *   bargain: leaving a tab is saying "I no longer need this".
 * - **The frames are typed by `type`, not by shape.** `start` is the first date, `stage`
 *   arrives zero or more times, and exactly one of `result`/`error` ends the request.
 */

/** How the wire speaks: the event as the backend sends it. */
interface Frame {
  type: 'start' | 'stage' | 'result' | 'error'
  /** Echoed back so one socket can carry several operations. */
  id?: string
  op?: StreamOp
  /** The stable stage identifier, e.g. `retrieval`. */
  key?: string
  /** The service's own wording for the stage, for display. */
  label?: string
  /** The full stage list for the operation, on `start` only. */
  stages?: string[]
  data?: unknown
  status?: number
  detail?: string
}

export interface StreamHandlers {
  /** The stages this operation will run through, in order. */
  onStages?: (stages: string[]) => void
  /** One stage is now running. */
  onStage?: (key: string, label: string) => void
}

type Listener = (frame: Frame) => void

/**
 * The shared connection, with the reconnect logic no caller should have to think about.
 *
 * A socket is a live thing: a server restart (`--reload` does this on every edit) closes
 * it, and the next request has to work anyway. So the connection is *lazy* - opened on the
 * first request and re-opened on the next after a close - rather than a singleton that a
 * caller has to notice is dead.
 */
class StreamConnection {
  private socket: WebSocket | null = null
  private opening: Promise<WebSocket> | null = null
  private readonly listeners = new Map<string, Listener>()
  private sequence = 0

  private url(): string {
    // `http://` -> `ws://`; `https://` -> `wss://`. A hand-built string would break behind
    // TLS, which is the one case that is hard to notice locally.
    return `${apiBase().replace(/^http/, 'ws')}/api/stream`
  }

  private open(): Promise<WebSocket> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return Promise.resolve(this.socket)
    }
    if (this.opening) return this.opening

    this.opening = new Promise<WebSocket>((resolve, reject) => {
      let socket: WebSocket
      try {
        socket = new WebSocket(this.url())
      } catch {
        reject(new ApiError(0, `Could not reach the API at ${apiBase()}. Is it running?`))
        return
      }
      socket.onopen = () => resolve(socket)
      socket.onmessage = (event) => {
        let frame: Frame
        try {
          frame = JSON.parse(event.data as string) as Frame
        } catch {
          // A frame this build cannot read is dropped rather than thrown: the socket is
          // shared, and one malformed message must not break the panel next to it.
          return
        }
        if (frame.id) this.listeners.get(frame.id)?.(frame)
      }
      socket.onerror = () => {
        // `onclose` always follows, so the failure is reported there, once, for every
        // pending request rather than once per request that noticed the error event.
      }
      socket.onclose = () => {
        this.socket = null
        this.opening = null
        // Everything in flight died with the connection. Resolving them as *errors* rather
        // than leaving their promises pending is what keeps a panel from spinning forever
        // when the server restarts - the alternative is a spinner with no way out.
        for (const listener of this.listeners.values()) {
          listener({ type: 'error', status: 0, detail: 'The API connection closed.' })
        }
        this.listeners.clear()
      }

      socket.onopen = () => {
        this.socket = socket
        resolve(socket)
      }
    })

    return this.opening
  }

  /**
   * Run one operation, reporting its stages until the result arrives.
   *
   * The returned promise resolves with the payload or rejects with an `ApiError` carrying
   * the backend's own status - so `describeFailure` and `ErrorNotice` treat a socket failure
   * exactly like an HTTP one, which is the point of sharing the mapping.
   */
  async run<T>(
    request: StreamRequest,
    handlers: StreamHandlers = {},
  ): Promise<T> {
    const socket = await this.open()
    const id = `op-${++this.sequence}`

    return new Promise<T>((resolve, reject) => {
      this.listeners.set(id, (frame) => {
        if (frame.type === 'start') {
          handlers.onStages?.(frame.stages ?? [])
          return
        }
        if (frame.type === 'stage') {
          if (frame.key) handlers.onStage?.(frame.key, frame.label ?? frame.key)
          return
        }
        // Terminal: the request is done either way, so the listener goes before the caller
        // runs - a handler that immediately asks something else must not be fed this reply.
        this.listeners.delete(id)
        if (frame.type === 'error') {
          reject(new ApiError(frame.status ?? 500, frame.detail ?? 'The request failed.'))
        } else {
          resolve(frame.data as T)
        }
      })

      try {
        socket.send(JSON.stringify({ id, ...request }))
      } catch (e) {
        this.listeners.delete(id)
        reject(
          new ApiError(
            0,
            e instanceof Error ? e.message : 'Could not send the request.',
          ),
        )
      }
    })
  }
}

const connection = new StreamConnection()

/**
 * Run a streaming operation, with the character this browser is looking at filled in.
 *
 * The character is resolved here rather than by each caller for the same reason the HTTP
 * client does it: it is a browser preference, and a panel that forgot to send it would be
 * answered about the server's default sheet.
 */
export function stream<T>(
  request: StreamRequest,
  handlers: StreamHandlers = {},
): Promise<T> {
  const character = request.character ?? readCharacter() ?? undefined
  return connection.run<T>({ ...request, character }, handlers)
}

/** Convenience wrappers, so a caller does not spell out the discriminator. */
export const streamed = {
  /**
   * Generate book loadouts, reporting the stages as they run.
   *
   * Falls back to `POST /api/scenario` when the socket cannot be opened, which is the case a
   * proxy that drops the upgrade produces. The answer is identical either way; only the
   * progress is lost, and losing progress is not worth failing a request over.
   */
  scenario: (
    scenario: string,
    character: string | undefined,
    handlers: StreamHandlers,
  ) =>
    withFallback(
      () => stream<Generation>({ op: 'scenario', scenario, character }, handlers),
      () => api.scenario(scenario, character),
    ),

  refine: (
    scenario: string,
    question: string,
    threadId: string | undefined,
    handlers: StreamHandlers,
  ) =>
    withFallback(
      () =>
        stream<Generation>(
          { op: 'refine', scenario, question, thread_id: threadId },
          handlers,
        ),
      () => api.ask(scenario, question, undefined, threadId),
    ),

  character: (
    question: string,
    character: string | undefined,
    threadId: string | undefined,
    handlers: StreamHandlers,
  ) =>
    withFallback(
      () =>
        stream<Answer>(
          { op: 'character', question, character, thread_id: threadId },
          handlers,
        ),
      () =>
        api.askCharacter(question, character, threadId),
    ),

  rules: (
    question: string,
    threadId: string | undefined,
    handlers: StreamHandlers,
  ) =>
    withFallback(
      () => stream<Answer>({ op: 'rules', question, thread_id: threadId }, handlers),
      () => api.rules(question, threadId),
    ),

  selection: (
    selectedText: string,
    context: string | undefined,
    documents: string[],
    threadId: string | undefined,
    handlers: StreamHandlers,
  ) =>
    withFallback(
      () =>
        stream<Answer>(
          {
            op: 'selection',
            selected_text: selectedText,
            context,
            document: documents,
            thread_id: threadId,
          },
          handlers,
        ),
      () => api.rulesContextual(selectedText, context, documents, threadId),
    ),
}

/**
 * A streaming call that still answers when the socket cannot be opened.
 *
 * The HTTP route is the contract and the socket is the improvement, so a proxy that does
 * not forward an upgrade (which is common), an older deployment, or a browser with
 * websockets blocked must degrade to the answer rather than to an error. Only the
 * *connection* falling back is retried: a 502 from a model that returned nothing is a real
 * answer about the model, and replaying it over HTTP would spend a second model call to
 * learn the same thing.
 */
async function withFallback<T>(
  streamed: () => Promise<T>,
  http: () => Promise<T>,
): Promise<T> {
  try {
    return await streamed()
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) return http()
    throw e
  }
}
