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
 * This is a **safety net, not the trigger**. A selection is normally acted on the moment the
 * gesture that made it ends - `useSelection` publishes on `pointerup` - because the mouse
 * coming up is the reader saying they have finished choosing. What this catches is the
 * selections no gesture ends: Ctrl+A, a double-click on a word, a selection made from the
 * keyboard, or one the browser restores.
 *
 * It is therefore longer than a drag rather than shorter. The first version was 350ms and
 * fired *during* a drag: a reader who paused mid-phrase for a third of a second had the
 * drawer open on half a sentence while they were still choosing the other half. A drag that
 * pauses is not a drag that has finished, and no timer can tell the two apart - which is why
 * the gesture, not the clock, is what decides.
 */
export const SELECTION_SETTLE_MS = 900
