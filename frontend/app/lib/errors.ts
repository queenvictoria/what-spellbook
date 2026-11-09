import { ApiError } from '@/api/client'

/** What a failure should look like on screen: a headline, the detail, and whether to retry. */
export type Failure = {
  title: string
  message: string
  retryable: boolean
}

/**
 * Turn whatever a `catch` produced into something worth showing.
 *
 * The backend already writes its 5xx messages for a person - `llm.explain_failure` names
 * the address, the command and the model - so this does not rewrite them. What it adds is
 * the part the message cannot know: which *kind* of failure it is, and therefore whether
 * offering a Retry button is honest. A 503 from a stopped Ollama is worth retrying once it
 * has been started; a 404 never is.
 *
 * Status 0 is `fetch` rejecting, which in development almost always means the API is not
 * running. It is separated from the other 5xx cases because the fix is different: nothing
 * about the model matters until the server is up.
 */
export function describeFailure(error: unknown): Failure {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return { title: 'The API is not running', message: error.message, retryable: true }
    }
    if (error.status === 503) {
      return { title: 'The model is unavailable', message: error.message, retryable: true }
    }
    if (error.status === 502) {
      return { title: 'The model returned nothing', message: error.message, retryable: true }
    }
    if (error.isPermanent) {
      return { title: 'That request cannot work', message: error.message, retryable: false }
    }
    return { title: 'The server failed', message: error.message, retryable: true }
  }
  // Not an ApiError, so this is a bug on this side rather than a reported failure. Retrying
  // would replay the same bug, so no button is offered.
  return {
    title: 'Something went wrong',
    message: error instanceof Error ? error.message : String(error),
    retryable: false,
  }
}
