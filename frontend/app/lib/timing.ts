/**
 * Timing constants shared across the app.
 *
 * Kept in one module because a duration is a *policy* decision, not a local detail: the same
 * number appearing in two files is two numbers that will eventually disagree, and the
 * disagreement shows up as one input feeling laggy next to another that feels responsive.
 *
 * Every value here is milliseconds and every name says so, because a bare `600` at a call
 * site is unreadable and a unit mistake is invisible.
 */

/**
 * How long typing has to stop before a request is made.
 *
 * Used by the Rules tab's ask box (a vector search plus a model call) and by the contextual
 * drawer's input (an index search that updates the cards below it). Both are text a reader
 * types at speed, so both want the same feel: long enough that a question typed quickly fires
 * once, short enough that the pause after a word does not read as the app ignoring the input.
 *
 * 600ms rather than something shorter because these are not keystroke-cost operations - one
 * embeds the query and the other can reach a model. Firing on every pause mid-word would
 * triple the cost of typing a sentence and leave several responses racing to fill one panel.
 */
export const TYPING_DEBOUNCE_MS = 600

/**
 * How long a text selection has to hold still before it is acted on.
 *
 * Shorter than {@link TYPING_DEBOUNCE_MS} because the gesture is different. A drag fires
 * `selectionchange` on every intermediate character, so *some* wait is required - but the
 * reader has already finished choosing by the time the mouse comes up, so this only has to
 * outlast the drag itself. Reusing the typing delay here would make every selection feel like
 * the app had stalled.
 */
export const SELECTION_SETTLE_MS = 350
