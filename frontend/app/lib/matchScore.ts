/**
 * A vector hit's Chroma distance, expressed as a 0-1 reading for the match dial.
 *
 * **This is a presentational transform, not a probability.** The index is built with
 * `hnsw:space: l2` over `nomic-embed-text`, so a hit's `distance` is a squared euclidean
 * distance between embeddings - unbounded above, with no threshold that means "relevant".
 * A vector search has no relevance floor at all, which is why the API reports
 * `total_matching` as "documents the *filters* admit" rather than a count of matches.
 *
 * So the number here answers "how near is this to the query, on a fixed scale" and nothing
 * more. It is deliberately **not** called a confidence: a confidence would be a claim about
 * the answer being right, and this cannot make that claim. The dial's tooltip says the same
 * thing, because a percentage on screen will be read as a probability otherwise.
 *
 * ## The scale
 *
 * Measured over the live index, so the dial's range is the range the data actually occupies:
 *
 * | Query | nearest | furthest |
 * | --- | --- | --- |
 * | `fireball` (a name) | 0.30 | 0.80 |
 * | `how does cover work` (a question) | 0.52 | 0.96 |
 * | `protect an ally from being grappled` (a description) | 0.61 | 0.82 |
 * | nonsense words | 0.97 | 1.02 |
 *
 * `MAX_DISTANCE` is therefore 1.4: it puts a nonsense query at the empty end (0.97 -> 3%)
 * and an exact name match near the full end (0.30 -> 79%), without either end clipping.
 * Clipping is what would make the dial lie, so the constant is set past the worst observed
 * distance rather than at a round number.
 *
 * The cost of the fixed scale is that a *good* question and a *mediocre* one can differ by
 * only a few points (0.52 and 0.61 are 66% and 59%). That is the honest picture: on this
 * embedder the absolute distance separates "found it" from "found nothing" far better than
 * it separates "good" from "better". Ordering within one result set is the reliable signal,
 * and it is what the list already shows.
 */

/**
 * The distance at which the dial reads empty.
 *
 * Past the largest distance a nonsense query produces, so the dial never pins at zero and
 * stops distinguishing one bad result from another.
 */
export const MAX_DISTANCE = 1.4

/** A hit's distance as 0-1, or null when the store could not score it. */
export function matchScore(distance: number | null | undefined): number | null {
  if (distance === null || distance === undefined) return null
  if (!Number.isFinite(distance)) return null
  return Math.min(1, Math.max(0, 1 - distance / MAX_DISTANCE))
}

/** How close a hit reads, for the dial's colour. */
export type MatchBand = "strong" | "good" | "fair" | "weak"

/**
 * The band a score falls in.
 *
 * Bands rather than a gradient because a continuous colour would imply the scale is
 * calibrated finely enough to tell 0.61 from 0.66, and it is not. Four steps is as much
 * resolution as the measurement supports.
 */
export function matchBand(score: number | null): MatchBand | null {
  if (score === null) return null
  if (score >= 0.75) return "strong"
  if (score >= 0.55) return "good"
  if (score >= 0.35) return "fair"
  return "weak"
}

/** What the dial's tooltip says, given the raw distance it was derived from. */
export function matchTitle(distance: number | null): string {
  if (distance === null) {
    return "This store could not score the match, so there is no reading to show."
  }
  const score = matchScore(distance)
  const percent = Math.round((score ?? 0) * 100)
  return (
    `${percent}% match — Chroma distance ${distance.toFixed(3)} on a fixed 0–${MAX_DISTANCE} ` +
    "scale. Lower distance is closer. This is a similarity reading, not a probability " +
    "that the answer is right."
  )
}
