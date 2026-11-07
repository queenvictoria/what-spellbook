import { cn } from "@/lib/utils"
import { matchBand, matchScore, matchTitle } from "@/lib/matchScore"

/**
 * A vector hit's match score as a small doughnut.
 *
 * The same reading Claude's context indicator gives: a ring that is filled to the value and
 * a number in the middle, so a list of hits can be scanned by shape instead of by reading
 * twelve decimal distances.
 *
 * **The number is a similarity reading, not a confidence.** See `lib/matchScore.ts` for what
 * it is derived from and why the scale is fixed rather than relative to the result set. The
 * `title` says so in full, because a percentage on screen will otherwise be read as a
 * probability that the answer is correct.
 *
 * Rendered as an SVG ring rather than a conic-gradient div: the gradient needs a hard stop at
 * an arbitrary angle, which a `background` cannot express without a mask, and the SVG's
 * `stroke-dasharray` states the value directly.
 */
export function MatchDial({
  distance,
  size = 14,
  className,
}: {
  /** The hit's Chroma distance, or null when the store could not score it. */
  distance: number | null
  size?: number
  className?: string
}) {
  const score = matchScore(distance)
  const band = matchBand(score)

  // Unscored is shown as an empty ring rather than hidden: a missing dial beside the others
  // reads as a rendering bug, while an empty one reads as "no reading", which is the truth.
  const percent = score === null ? 0 : Math.round(score * 100)
  const radius = (size - STROKE) / 2
  const circumference = 2 * Math.PI * radius
  const filled = circumference * (score ?? 0)

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center",
        className,
      )}
      style={{ width: size, height: size }}
      title={matchTitle(distance)}
      role="img"
      aria-label={
        score === null
          ? "Match score unavailable"
          : `${percent}% match, ${band ?? "unknown"}`
      }
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        {/* The track. Muted rather than absent, so an empty dial still reads as a dial. */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={STROKE}
          className="stroke-void-700"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference - filled}`}
          className={cn(
            "transition-[stroke-dasharray]",
            BAND_STROKE[band ?? "weak"],
          )}
        />
      </svg>
      <span
        className={cn(
          "sr-only absolute text-[0.55rem] font-medium tabular-nums",
          BAND_TEXT[band ?? "weak"],
        )}
      >
        {score === null ? "–" : percent}
      </span>
    </span>
  )
}

/** Ring thickness. Thin enough that the number in the middle stays legible at 34px. */
const STROKE = 2

/**
 * The band colours, from the theme tokens rather than new ones.
 *
 * `verdant` for a strong match, `radiant` for a good one, `arcane` for a fair one and muted
 * parchment for a weak one. The same three accents the rest of the app uses, so the dial
 * cannot introduce a fourth vocabulary for "this is good".
 */
const BAND_STROKE: Record<string, string> = {
  strong: "stroke-verdant-400",
  good: "stroke-radiant-400",
  fair: "stroke-arcane-400",
  weak: "stroke-parchment/30",
}

const BAND_TEXT: Record<string, string> = {
  strong: "text-verdant-400",
  good: "text-radiant-400",
  fair: "text-arcane-300",
  weak: "text-parchment/45",
}
