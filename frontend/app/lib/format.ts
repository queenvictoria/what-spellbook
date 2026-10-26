/** A duration a person reads at the table: seconds under a minute, else "1m 05s". */
export function formatSeconds(value: number) {
  if (value < 60) return `${value.toFixed(1)}s`
  const minutes = Math.floor(value / 60)
  return `${minutes}m ${String(Math.round(value % 60)).padStart(2, '0')}s`
}

/** The median, used to turn this machine's recorded run times into an estimate. */
export function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2
}

/**
 * How far through the estimate a run is, as an uncapped percentage - or null with no
 * estimate to measure against.
 *
 * Deliberately *not* clamped. A run that has taken longer than expected is the one case
 * where the number matters most: a model call that has stalled past its median looks
 * identical to one about to finish if both read "99%", and the percentage is the only
 * signal saying otherwise. The bar clamps for the same reason the readout does not - it
 * cannot draw more than full - so the two are separate values from one measurement.
 */
export function progressPercent(elapsed: number, estimate: number | null) {
  if (estimate === null || estimate <= 0) return null
  return (elapsed / estimate) * 100
}
