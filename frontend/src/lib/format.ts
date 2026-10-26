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
