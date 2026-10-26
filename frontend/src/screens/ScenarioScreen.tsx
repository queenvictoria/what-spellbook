import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import type { Book, Generation } from '@/api/types'
import { BookPanel } from '@/components/BookPanel'
import { Markdown } from '@/components/Markdown'
import { StageProgress } from '@/components/StageProgress'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { median } from '@/lib/format'

type Phase = 'idle' | 'running' | 'done' | 'error'

/**
 * Generate a recommendation, or replay the stored one for the same scenario.
 *
 * The cache is the point: the same scenario with the same character and book count
 * costs nothing to re-open, and the backend reports which happened via `from_cache`.
 * The elapsed timer runs locally while the request is in flight because the backend
 * only reports timings once it has finished - and a run takes about 45 seconds, so a
 * silent screen reads as a hang.
 */
export function ScenarioScreen() {
  // Seeded from ?scenario= so the history screen can link straight into a stored run.
  const [params] = useSearchParams()
  const [scenario, setScenario] = useState(() => params.get('scenario') ?? '')
  const [generation, setGeneration] = useState<Generation | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [estimate, setEstimate] = useState<number | null>(null)
  const [stage, setStage] = useState(0)
  const started = useRef(0)

  // A rough three-stage split, matching what the CLI records. The real per-stage
  // timings only exist after the run, so this is a display heuristic: retrieval is
  // quick and local, the model call dominates.
  useEffect(() => {
    if (phase !== 'running') return
    const timer = setInterval(() => {
      const seconds = (performance.now() - started.current) / 1000
      setElapsed(seconds)
      setStage(seconds < 3 ? 0 : seconds < 5 ? 1 : 2)
    }, 100)
    return () => clearInterval(timer)
  }, [phase])

  // Learn the estimate from the scenarios already run, so the first run is honest
  // about taking ~45s rather than showing a spinner with no scale.
  useEffect(() => {
    let cancelled = false
    api
      .history()
      .then((runs) => {
        const totals = runs
          .map((run) => run.timings.total_seconds)
          .filter((value): value is number => typeof value === 'number' && value > 0)
        if (!cancelled && totals.length) {
          setEstimate(median(totals))
        }
      })
      .catch(() => {
        // History is only used for the estimate; failing to read it must not block a run.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const generate = useCallback(async () => {
    if (!scenario.trim()) return
    setPhase('running')
    setError(null)
    setGeneration(null)
    setElapsed(0)
    started.current = performance.now()

    try {
      const result = await api.scenario(scenario)
      setGeneration(result)
      setPhase('done')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setPhase('error')
    }
  }, [scenario])

  return (
    <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Scenario</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              rows={6}
              value={scenario}
              placeholder="A rust monster eats the fighter's plate armour mid-fight."
              onChange={(e) => setScenario(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate()
              }}
            />
            <Button
              className="w-full"
              onClick={generate}
              disabled={phase === 'running' || !scenario.trim()}
            >
              {phase === 'running' ? 'Scribing…' : 'Recommend spells'}
            </Button>
            <p className="text-xs text-parchment/45">
              ⌘/Ctrl + Enter to run. Repeating the same scenario re-opens the stored
              result instead of asking the model again.
            </p>
          </CardContent>
        </Card>

        {phase === 'running' && (
          <Card>
            <CardContent className="pt-4">
              <StageProgress stage={stage} elapsed={elapsed} estimate={estimate} />
            </CardContent>
          </Card>
        )}

        {error && (
          <Card className="border-red-500/40">
            <CardHeader>
              <CardTitle className="text-red-300">The run failed</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-parchment/70">{error}</p>
            </CardContent>
          </Card>
        )}

        {generation && (
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Run</CardTitle>
              {generation.from_cache ? (
                <Badge tone="verdant">Served from cache</Badge>
              ) : (
                <Badge tone="arcane">Freshly generated</Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-parchment/55">
              <Timings generation={generation} />
              {generation.model && <p className="font-mono">{generation.model}</p>}
              {generation.warnings.length > 0 && (
                <div className="space-y-1 pt-2">
                  {generation.warnings.map((warning, i) => (
                    <p key={i} className="text-radiant-400">
                      ⚠ {warning}
                    </p>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <div className="space-y-4">
        {!generation && phase !== 'running' && (
          <Card>
            <CardContent className="pt-4 text-sm text-parchment/50">
              Describe the encounter to get books of spells built for it.
            </CardContent>
          </Card>
        )}

        {generation?.books.map((book) => (
          <BookPanel key={book.index} book={book} scenario={generation.scenario} />
        ))}

        {generation && generation.answer && (
          <Card>
            <CardHeader>
              <CardTitle>Overall reasoning</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown text={generation.answer} className="prose-spell" />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function Timings({ generation }: { generation: Generation }) {
  const phases = Object.entries(generation.timings.phases ?? {})
  if (!phases.length) return null
  return (
    <div className="space-y-1">
      {phases.map(([name, seconds]) => (
        <div key={name} className="flex justify-between font-mono">
          <span>{name}</span>
          <span>{seconds.toFixed(1)}s</span>
        </div>
      ))}
      {generation.timings.total_seconds !== null && (
        <div className="flex justify-between border-t border-void-700 pt-1 font-mono text-parchment/70">
          <span>total</span>
          <span>{generation.timings.total_seconds.toFixed(1)}s</span>
        </div>
      )}
    </div>
  )
}


export type { Book }
