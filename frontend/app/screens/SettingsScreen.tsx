import { useCallback, useEffect, useState } from "react"
import { Check, Eye, EyeOff, RotateCcw, Save } from "lucide-react"

import { api } from "@/api/client"
import type { Settings, SettingField, SettingSource } from "@/api/types"
import { ErrorNotice } from "@/components/ErrorNotice"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  apiBaseError,
  BUILD_API_BASE,
  hasApiBaseOverride,
  readApiBase,
  writeApiBase,
} from "@/lib/browserSettings"
import { cn } from "@/lib/utils"

/**
 * Where the app reads its configuration from, split by who owns each setting.
 *
 * The split is the point of the screen, not a layout choice. The models and the key are read
 * by the *backend* when it builds a model client, so they are saved through the API and a
 * browser copy of them would do nothing. The API address has to be known before a request
 * can be made at all, so only it can live in the browser. Showing them as one list of boxes
 * would imply the browser holds all of them, and a user who inspected `localStorage` and
 * found no model there would reasonably conclude the page was broken.
 */
export function SettingsScreen() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // Which boxes the user has actually edited.
  //
  // Needed for the secret field, and only for it. A non-secret box is comparable against the
  // value the server sent, so an edit is visible in the draft itself. The key arrives
  // *masked*, so there is nothing to compare against - and comparing a typed key to a mask
  // would call every save a change. Worse, a secret cannot be excluded from the patch either:
  // that is what made the box unwritable, with the Save button permanently disabled and no
  // way to store a key at all. Tracking touched-ness answers both: untouched means absent
  // (the stored key survives), touched means write exactly what is in the box, and touching
  // then emptying it is a deliberate clear.
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(() => {
    api
      .settings()
      .then((result) => {
        setSettings(result)
        setDrafts(
          Object.fromEntries(
            result.fields.filter((f) => !f.secret).map((f) => [f.key, f.value ?? ""]),
          ),
        )
        setTouched({})
      })
      .catch(setError)
  }, [])

  useEffect(load, [load])

  /** Only the boxes actually edited, so saving one cannot clear the others. */
  function changedPatch() {
    if (!settings) return {}
    const patch: Record<string, string> = {}
    for (const field of settings.fields) {
      const draft = drafts[field.key] ?? ""
      if (field.secret) {
        // Included only on touch: an untouched box must be absent, or a save made for another
        // field would write an empty string over the stored key.
        if (touched[field.key]) patch[field.key] = draft
        continue
      }
      if (draft.trim() !== (field.value ?? "").trim()) patch[field.key] = draft
    }
    return patch
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
      const result = await api.saveSettings(changedPatch())
      setSettings(result)
      // Re-seed from the response and forget what was touched. Without this the secret box
      // keeps the typed key and stays "touched", so the form still reads as dirty after a
      // successful save - and a second Save would write a value nothing changed. Clearing
      // the box is also the only option: the response carries a mask, and putting that in
      // the field would make the next save write the mask as the key.
      setDrafts(
        Object.fromEntries(
          result.fields.filter((f) => !f.secret).map((f) => [f.key, f.value ?? ""]),
        ),
      )
      setTouched({})
      setSaved(true)
    } catch (e) {
      setSaveError(e)
    } finally {
      setSaving(false)
    }
  }

  function retry() {
    setError(null)
    load()
  }

  if (!settings) {
    // The API-address card renders even here, and that is deliberate: a wrong address is the
    // commonest reason `api.settings()` fails, and it is the one failure whose fix is *on
    // this page*. Returning only an error would make the screen that repairs a bad address
    // unreachable whenever the address is bad.
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        {error != null ? (
          <ErrorNotice error={error} onRetry={retry} />
        ) : (
          <p className="text-sm text-parchment/60">Loading…</p>
        )}
        <ApiBaseCard />
      </div>
    )
  }

  const patch = changedPatch()
  const dirty = Object.keys(patch).length > 0

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Models</CardTitle>
          <CardDescription>
            Used by every surface — the CLI, the API and anything else calling the same service.
            Saved on the server in <code className="text-parchment/70">{settings.settings_file}</code>;
            a value set in the environment when the server started takes precedence over it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {!settings.writable && (
            <p className="rounded-md border border-radiant-500/40 bg-radiant-500/5 p-3 text-xs text-radiant-200">
              The settings file is not writable, so nothing here can be saved. Check the
              permissions on its directory.
            </p>
          )}

          {settings.fields.map((field) => (
            <Field
              key={field.key}
              field={field}
              value={drafts[field.key] ?? ""}
              touched={touched[field.key] === true}
              onChange={(value) => edit(field, value)}
            />
          ))}

          {saveError != null && <ErrorNotice error={saveError} compact />}

          <div className="flex items-center gap-3 pt-1">
            <Button onClick={save} disabled={saving || !dirty || !settings.writable}>
              <Save className="h-4 w-4" />
              {saving ? "Saving…" : "Save"}
            </Button>
            {saved && !dirty && (
              <span className="flex items-center gap-1 text-xs text-verdant-400">
                <Check className="h-3.5 w-3.5" />
                Saved. The next request uses it.
              </span>
            )}
            {dirty && <span className="text-xs text-parchment/50">Unsaved changes</span>}
          </div>
        </CardContent>
      </Card>

      {/* What the next run will actually do, resolved by the backend. It cannot be derived
          from the boxes above: a name containing a slash means OpenRouter only while a key is
          present, and otherwise falls back to a local model. */}
      <Card>
        <CardHeader>
          <CardTitle>In effect</CardTitle>
          <CardDescription>
            What the next recommendation will use, resolved the same way the server resolves it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-void-800 text-sm">
            <Row label="Reasoning">
              <Resolved model={settings.reasoning_model} backend={settings.reasoning_backend} />
            </Row>
            <Row label="Fast">
              <Resolved model={settings.fast_model} backend={settings.fast_backend} />
            </Row>
          </dl>
        </CardContent>
      </Card>

      <ApiBaseCard />
    </div>
  )
}

/** One model box, with its label, help and the layer its current value came from. */
function Field({
  field,
  value,
  touched,
  onChange,
}: {
  field: SettingField
  value: string
  touched: boolean
  onChange: (value: string) => void
}) {
  const [revealed, setRevealed] = useState(false)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <label htmlFor={field.key} className="text-sm font-medium text-parchment/90">
          {field.label}
        </label>
        <SourceBadge source={field.source} />
      </div>

      <div className="flex gap-2">
        <Input
          id={field.key}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          // A secret is a password box, but one that can be revealed while typing: the value
          // is never echoed anywhere, so hiding it only makes a typo invisible.
          type={field.secret && !revealed ? "password" : "text"}
          autoComplete="off"
          spellCheck={false}
          placeholder={field.secret && field.value ? `Saved (${field.value})` : "Not set"}
        />
        {field.secret && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={revealed ? "Hide the key" : "Show the key"}
            onClick={() => setRevealed((shown) => !shown)}
          >
            {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </Button>
        )}
      </div>

      <p className="text-xs text-parchment/50">
        {field.help}
        {/* A secret box is never pre-filled with the saved value, so the only thing that says
            whether a key is stored is this line. Saving replaces it; emptying the box and
            saving clears it - and the help text says so, because a password box that shows
            nothing looks like a key that is not there. */}
        {field.secret && field.value && !touched && (
          <> Currently saved: <code className="text-parchment/70">{field.value}</code>. Leave
          empty to keep it; clear it to remove the key.</>
        )}
        {field.secret && touched && (
          <> {value.trim()
            ? "Saving replaces the stored key with this one."
            : "Saving with this box empty removes the stored key."}</>
        )}
      </p>
    </div>
  )
}

const SOURCE_LABELS: Record<SettingSource, { text: string; tone: "muted" | "verdant" | "radiant" }> = {
  launch: { text: "from the shell", tone: "radiant" },
  saved: { text: "saved here", tone: "verdant" },
  env: { text: "from .env", tone: "muted" },
  default: { text: "default", tone: "muted" },
}

/**
 * Which layer supplied the value that is actually in use.
 *
 * Not decoration: with `.env`, the saved file and the launch environment all able to set the
 * same name, a save can succeed and still not change anything — and nothing else on screen
 * would explain why. Naming the winner is the difference between "the page is broken" and
 * "this server was started with the variable set".
 */
function SourceBadge({ source }: { source: SettingSource }) {
  const { text, tone } = SOURCE_LABELS[source] ?? SOURCE_LABELS.default
  return (
    <Badge tone={tone} title="Which layer supplied the value in use">
      {text}
    </Badge>
  )
}

function Resolved({ model, backend }: { model: string | null; backend: string | null }) {
  if (!model) return <span className="text-parchment/50">Not resolved</span>
  return (
    <span className="flex flex-wrap items-center gap-2">
      <code className="text-parchment/90">{model}</code>
      {backend && <Badge tone="arcane">{backend}</Badge>}
    </span>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] items-center gap-4 py-2">
      <dt className="text-parchment/60">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/**
 * The API address, the one setting that has to live in the browser.
 *
 * Kept apart from the server settings above, and labelled as working differently, because it
 * does: it is a `localStorage` value read by `fetch` before any request exists, so it cannot
 * be served by the API it points at. A saved value is applied to the next request with no
 * reload, and the connection check is a real request - which is the only way to know an
 * address works, since a wrong one fails at the transport layer rather than in validation.
 */
function ApiBaseCard() {
  const [value, setValue] = useState(() => readApiBase() ?? "")
  const [override, setOverride] = useState(() => hasApiBaseOverride())
  const [note, setNote] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)

  const formatError = apiBaseError(value)

  function apply() {
    if (formatError) return
    const stored = writeApiBase(value)
    setOverride(hasApiBaseOverride())
    setNote(stored ? null : "This browser refused to store the value; it will apply for this session only.")
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
      setResult({ ok: true, message: `Reached the API. Model: ${health.model ?? "unknown"}.` })
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : String(e) })
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
          Stored in this browser, not on the server — it has to be known before a request can be
          made, so it cannot be fetched from the API it points at. Leave it empty to use the
          build's default.
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
          <Button variant="outline" size="icon" aria-label="Use the default" onClick={reset}>
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>

        {formatError && <p className="text-xs text-red-300">{formatError}</p>}

        <p className="text-xs text-parchment/50">
          {override ? "Currently overridden." : "Currently using the build's default."}{" "}
          Default: <code className="text-parchment/70">{BUILD_API_BASE}</code>
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={apply} disabled={!!formatError || !dirty}>
            <Save className="h-4 w-4" />
            Apply
          </Button>
          {/* A real request, because a syntactically valid address can still be nothing —
              which is how a typo in this field presents: every screen fails, and the message
              points at the API rather than at the box that caused it. */}
          <Button variant="outline" onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Test connection"}
          </Button>
          {note && <span className="text-xs text-radiant-300">{note}</span>}
        </div>

        {result && (
          <p className={cn("text-xs", result.ok ? "text-verdant-400" : "text-red-300")}>
            {result.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
