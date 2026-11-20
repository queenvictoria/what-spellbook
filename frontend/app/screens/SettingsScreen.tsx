import { useCallback, useEffect, useState } from "react"
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Pin,
  RotateCcw,
  Save,
  X,
} from "lucide-react"

import { api } from "@/api/client"
import type { Settings, SettingField } from "@/api/types"
import { ErrorNotice } from "@/components/ErrorNotice"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import {
  apiBaseError,
  BUILD_API_BASE,
  clearModelSettings,
  hasApiBaseOverride,
  readApiBase,
  readModelSettings,
  writeApiBase,
  writeModelSettings,
  type StoredModelSettings,
} from "@/lib/browserSettings"
import { cn } from "@/lib/utils"

/**
 * Where the app reads its configuration from: this browser.
 *
 * The models, their providers and the provider keys are stored in `localStorage` and pushed to
 * the API. The server keeps nothing — `PUT /api/settings` holds what it is sent **in memory for
 * the life of the process** so the model client can be built from it, and writes no file,
 * because the key is a credential and a server-side copy of it is a liability nobody asked for.
 * Two consequences this screen has to be honest about:
 *
 * * **This browser is the only durable copy.** Clearing site data loses the settings, and the
 *   next run falls back to whatever the server's environment has.
 * * **A restart does not lose them.** The page re-pushes what it has stored on load, so a
 *   server restart does not quietly revert the choice.
 */
export function SettingsScreen() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)

  /**
   * Read the server's definitions, apply what this browser has stored, and push it back.
   *
   * The push is what makes the browser the source of truth rather than just a form: without
   * it, stored settings would only take effect after the user pressed Save again following
   * every reload or server restart.
   *
   * **A browser with nothing stored must not push.** An empty push means "forget everything"
   * — that is what Reset sends — so opening this page from an origin with an empty
   * `localStorage` silently reverted the server to its environment defaults. That is not a
   * corner case: `localStorage` is per-origin, so a second dev server on another port (or the
   * production build served from a different one) is a *different* store, and simply opening
   * Settings there switched the model back to Ollama no matter what the first tab had saved.
   * The symptom is a setting that reverts by itself, and a local model doing the work after
   * every provider had been set to a remote one.
   *
   * So the push happens only when this browser actually has an opinion. Nothing stored means
   * nothing to say, and the page shows the server's resolved values instead.
   */
  const load = useCallback(() => {
    api
      .settings()
      .then(async (definitions) => {
        const stored = readModelSettings()
        const hasStored = Object.keys(stored).length > 0
        const applied = hasStored
          ? await api.saveSettings(stored)
          : definitions
        setSettings(applied)
        setDrafts(seed(definitions, stored))
        setTouched({})
      })
      .catch(setError)
  }, [])

  useEffect(load, [load])

  /**
   * What to push: only the boxes the user has actually changed.
   *
   * This is the fix for a second save wiping the key. A secret box is never pre-filled — the
   * server only ever sends a mask, so filling it in would write the mask back as the key — so
   * the page cannot resend a key it already holds. Sending every box regardless therefore sent
   * an empty string for the key on every save after the first, and "blank" means "remove it".
   * An absent field means "no change", so only touched boxes are sent, plus a secret that has
   * been explicitly cleared (which sends `""` and is the Clear button's whole job).
   */
  function current(): StoredModelSettings {
    if (!settings) return {}
    const values: StoredModelSettings = {}
    for (const field of settings.fields) {
      if (!touched[field.key]) continue
      values[field.key as keyof StoredModelSettings] = drafts[field.key] ?? ""
    }
    return values
  }

  function edit(field: SettingField, value: string) {
    setSaved(false)
    setTouched((current) => ({ ...current, [field.key]: true }))
    setDrafts((current) => ({ ...current, [field.key]: value }))
  }

  async function save() {
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const values = current()
      // Merged into what is already stored rather than replacing it, because `values` is a
      // diff: replacing would drop every untouched box, and the stored copy has to stay whole
      // because it is the one that survives a server restart.
      const stored: StoredModelSettings = { ...readModelSettings(), ...values }
      for (const key of Object.keys(values) as (keyof StoredModelSettings)[]) {
        if (!stored[key]) delete stored[key]
      }
      const kept = writeModelSettings(stored)
      // Pushed even when storage refused, so the session still behaves as the form says - the
      // alternative is a Save button that appears to do nothing at all.
      const applied = await api.saveSettings(values)
      setSettings(applied)
      // Re-seed from what is now stored, and forget what was touched: the boxes have to agree
      // with the picture the page just made durable, and a field left "touched" reads as dirty
      // after a successful save. Seeding from the stored copy rather than from
      // `applied.fields` is deliberate — a field's `value` in the response is the *server's*
      // environment value, which is usually null here, so seeding from it blanked every box.
      setDrafts(seed(applied, stored))
      setTouched({})
      if (!kept) setSaveError(new Error(NOT_STORED))
      setSaved(true)
    } catch (e) {
      setSaveError(e)
    } finally {
      setSaving(false)
    }
  }

  /** Forget the stored settings and fall back to the server's environment. */
  async function reset() {
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      clearModelSettings()
      setSettings(await api.saveSettings({ reset: true }))
      load()
    } catch (e) {
      setSaveError(e)
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    // The API-address card renders even here, and that is deliberate: a wrong address is the
    // commonest reason the settings request fails, and it is the one failure whose fix is *on
    // this page*. Returning only an error would make the screen that repairs a bad address
    // unreachable whenever the address is bad.
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        {error != null ? (
          <ErrorNotice
            error={error}
            onRetry={() => {
              setError(null)
              load()
            }}
          />
        ) : (
          <p className="text-sm text-parchment/60">Loading…</p>
        )}
        <ApiBaseCard />
      </div>
    )
  }

  const dirty = settings.fields.some((field) => touched[field.key])
  const pinned = new Set(settings.pinned)
  const groups = groupFields(settings.fields)

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {groups.map(([title, fields], index) => (
        <Card key={title}>
          <CardHeader>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{GROUP_HELP[title] ?? ""}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {index === 0 && settings.any_pinned && (
              <p className="rounded-md border border-radiant-500/40 bg-radiant-500/5 p-3 text-xs text-radiant-200">
                This server was started with some of these already set in its
                environment, and those win — a launched variable outranks a
                browser, so an edit to a pinned field will be accepted and have no
                effect. They are marked below.
              </p>
            )}

            {fields.map((field) => (
              <Field
                key={field.key}
                field={field}
                value={drafts[field.key] ?? ""}
                touched={touched[field.key] === true}
                pinned={pinned.has(field.key)}
                onChange={(value) => edit(field, value)}
                onClear={() => edit(field, "")}
              />
            ))}

            {index === groups.length - 1 && (
              <>
                {saveError != null && <ErrorNotice error={saveError} compact />}

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <Button onClick={save} disabled={saving || !dirty}>
                    <Save className="h-4 w-4" />
                    {saving ? "Saving…" : "Save"}
                  </Button>
                  <Button variant="outline" onClick={reset} disabled={saving}>
                    <RotateCcw className="h-4 w-4" />
                    Use the server's defaults
                  </Button>
                  {saved && !dirty && (
                    <span className="flex items-center gap-1 text-xs text-verdant-400">
                      <Check className="h-3.5 w-3.5" />
                      Saved. The next request uses it.
                    </span>
                  )}
                  {dirty && (
                    <span className="text-xs text-parchment/50">
                      Unsaved changes
                    </span>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      ))}

      {/* What the next run will actually do, resolved by the backend through the same merge the
          service uses. It cannot be derived from the boxes above: a provider chosen without a
          key falls back to Ollama, and a pinned field overrides its box whatever the box says. */}
      <Card>
        <CardHeader>
          <CardTitle>In effect on the server</CardTitle>
          <CardDescription>
            What the next recommendation will use, resolved the way the server
            resolves it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-void-800 text-sm">
            <Row label="Reasoning">
              <Resolved
                model={settings.reasoning_model}
                provider={settings.reasoning_provider}
              />
            </Row>
            <Row label="Fast">
              <Resolved
                model={settings.fast_model}
                provider={settings.fast_provider}
              />
            </Row>
          </dl>
        </CardContent>
      </Card>

      <ApiBaseCard />
    </div>
  )
}

const NOT_STORED =
  "This browser refused to store the settings, so they apply only until the page is reloaded."

/** What each card is for, keyed by the group the backend put its fields in. */
const GROUP_HELP: Record<string, string> = {
  Models:
    "Stored in this browser and pushed to the API on change. The provider says which service " +
    "serves the name, which the name alone cannot — an Ollama model may be a Hugging Face repo " +
    "id and so contains slashes. The CLI reads the same names from its own environment.",
  "API keys":
    "Held in this browser and sent to the server only in memory, for the life of the process. " +
    "A key is never pre-filled here and is never written to disk, so Save leaves it alone " +
    "unless you type a new one.",
  Fallback:
    "Where the server lands when a chosen provider cannot run — a remote model with no key, " +
    "or a client that failed to construct. A local model, so it needs no key.",
}

/**
 * The box values to show, given the server's definitions and what this browser stored.
 *
 * A stored value wins over the server's, because the browser is the store of record. Falling
 * back to `resolved` rather than `value` is what makes a fresh browser show what will *actually*
 * run: the environment usually names no provider at all, while the server still resolves one
 * (Ollama, or OpenRouter when it has a key), and a blank dropdown beside a card naming a model
 * reads as two answers to one question.
 *
 * A secret is never seeded: the server only ever sends a mask, and putting that in the field
 * would make the next save write the mask as the key.
 */
function seed(
  definitions: Settings,
  stored: StoredModelSettings,
): Record<string, string> {
  return Object.fromEntries(
    definitions.fields.map((field) => {
      if (field.secret) return [field.key, ""]
      const own = stored[field.key as keyof StoredModelSettings]
      return [field.key, own ?? field.resolved ?? field.value ?? ""]
    }),
  )
}

/** The fields in the order the backend listed them, split by the card they belong in. */
function groupFields(fields: SettingField[]): [string, SettingField[]][] {
  const groups: [string, SettingField[]][] = []
  for (const field of fields) {
    const last = groups.at(-1)
    if (last && last[0] === field.group) last[1].push(field)
    else groups.push([field.group, [field]])
  }
  return groups
}

/** One setting row: label, control, and whether the server pins it. */
function Field({
  field,
  value,
  touched,
  pinned,
  onChange,
  onClear,
}: {
  field: SettingField
  value: string
  touched: boolean
  pinned: boolean
  onChange: (value: string) => void
  onClear: () => void
}) {
  const [revealed, setRevealed] = useState(false)
  // Whether the *server* holds a key, which is the only thing on screen that says one is set:
  // the box is never pre-filled, so an empty box means "no new key", not "no key".
  const held = field.secret ? field.value : null

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={field.key}
          className="text-sm font-medium text-parchment/90"
        >
          {field.label}
        </label>
        {pinned && (
          <Badge
            tone="radiant"
            title="Set when this server started, so it outranks this page"
          >
            <Pin className="h-3 w-3" />
            set on the server
          </Badge>
        )}
        {/* A key that is present but cannot work is worse than none: the box looks satisfied
            and the failure only appears on the next run, as a 401 from the provider. The
            backend decides which is which, because only it sees the value in full. */}
        {field.problem ? (
          <Badge
            tone="radiant"
            title={field.problem}
            className="border-red-400/50 bg-red-500/10 text-red-300"
          >
            <AlertTriangle className="h-3 w-3" />
            key unusable
          </Badge>
        ) : (
          held && (
            <Badge tone="verdant" title="A key is loaded on the server">
              <Check className="h-3 w-3" />
              key set
            </Badge>
          )
        )}
      </div>

      <div className="flex gap-2">
        {field.choices ? (
          <Select
            id={field.key}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            aria-label={field.label}
          >
            {/* An empty value is "no opinion", which is not the same as any provider: it lets
                the server decide from the key it has, and is what an untouched form holds. */}
            <option value="">Let the server decide</option>
            {field.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </Select>
        ) : (
          <Input
            id={field.key}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            // A secret is a password box, but one that can be revealed while typing: the value
            // is never echoed anywhere else, so hiding it only makes a typo invisible.
            type={field.secret && !revealed ? "password" : "text"}
            autoComplete="off"
            spellCheck={false}
            placeholder={
              field.problem
                ? "No usable key - paste the whole one"
                : held
                  ? `Saved: ${held}. Leave empty to keep it.`
                  : "Not set"
            }
            aria-invalid={field.problem !== null}
            className={cn("font-mono", field.problem && "border-red-400/60")}
          />
        )}
        {field.secret && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={revealed ? "Hide the key" : "Show the key"}
            onClick={() => setRevealed((shown) => !shown)}
          >
            {revealed ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </Button>
        )}
        {/* A set key cannot be removed by emptying the box, because an empty box already means
            "keep it" - that is what stops a save wiping it. Removing one is an explicit act
            with its own control, which sends a blank value and nothing else. */}
        {(held || (field.secret && touched && value !== "")) && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={`Clear the ${field.label}`}
            title="Remove the saved key"
            onClick={onClear}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <p className="text-xs text-parchment/50">
        {field.help}
        {field.problem ? (
          <>
            {" "}
            <span className="text-red-300">{field.problem}</span>
          </>
        ) : (
          held && (
            <>
              {" "}
              A key is in use: <code className="text-parchment/70">{held}</code>.
            </>
          )
        )}
      </p>
    </div>
  )
}

function Resolved({
  model,
  provider,
}: {
  model: string | null
  provider: string | null
}) {
  if (!model) return <span className="text-parchment/50">Not resolved</span>
  return (
    <span className="flex flex-wrap items-center gap-2">
      <code className="text-parchment/90">{model}</code>
      {provider && <Badge tone="arcane">{provider}</Badge>}
    </span>
  )
}

function Row({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[8rem_1fr] items-center gap-4 py-2">
      <dt className="text-parchment/60">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/**
 * The API address, stored in the browser for the same reason as everything else here.
 *
 * It cannot be pushed anywhere, because it has to be known before a request can be made — which
 * makes it the one setting that only ever exists on this side. A saved value is applied to the
 * next request with no reload, and the connection check is a real request, since that is the
 * only way to know an address works.
 */
function ApiBaseCard() {
  const [value, setValue] = useState(() => readApiBase() ?? "")
  const [override, setOverride] = useState(() => hasApiBaseOverride())
  const [note, setNote] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(
    null,
  )

  const formatError = apiBaseError(value)

  function apply() {
    if (formatError) return
    const stored = writeApiBase(value)
    setOverride(hasApiBaseOverride())
    setNote(
      stored
        ? null
        : "This browser refused to store the value; it will apply for this session only.",
    )
    setResult(null)
  }

  function reset() {
    writeApiBase(null)
    setValue("")
    setOverride(false)
    setNote(null)
    setResult(null)
  }

  async function check() {
    setChecking(true)
    setResult(null)
    try {
      const health = await api.health()
      setResult({
        ok: true,
        message: `Reached the API. Model: ${health.model ?? "unknown"}.`,
      })
    } catch (e) {
      setResult({
        ok: false,
        message: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setChecking(false)
    }
  }

  const dirty = value.trim() !== (readApiBase() ?? "")

  return (
    <Card>
      <CardHeader>
        <CardTitle>API address</CardTitle>
        <CardDescription>
          Stored in this browser, not on the server — it has to be known before
          a request can be made, so it cannot be fetched from the API it points
          at. Leave it empty to use the build's default.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Input
            value={value}
            onChange={(event) => {
              setNote(null)
              setValue(event.target.value)
            }}
            placeholder={BUILD_API_BASE}
            spellCheck={false}
            aria-invalid={formatError !== null}
            aria-label="API base address"
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="Use the default"
            onClick={reset}
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>

        {formatError && <p className="text-xs text-red-300">{formatError}</p>}

        <p className="text-xs text-parchment/50">
          {override
            ? "Currently overridden."
            : "Currently using the build's default."}{" "}
          Default: <code className="text-parchment/70">{BUILD_API_BASE}</code>
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={apply} disabled={!!formatError || !dirty}>
            <Save className="h-4 w-4" />
            Apply
          </Button>
          {/* A real request, because a syntactically valid address can still be nothing — which
              is how a typo in this field presents: every screen fails, and the message points
              at the API rather than at the box that caused it. */}
          <Button variant="outline" onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Test connection"}
          </Button>
          {note && <span className="text-xs text-radiant-300">{note}</span>}
        </div>

        {result && (
          <p
            className={cn(
              "text-xs",
              result.ok ? "text-verdant-400" : "text-red-300",
            )}
          >
            {result.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}