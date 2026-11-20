import { useCallback, useEffect, useState } from "react"
import { Check, Eye, EyeOff, Pin, RotateCcw, Save } from "lucide-react"

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
 * The models and the OpenRouter key are stored in `localStorage` and pushed to the API. The
 * server keeps nothing — `PUT /api/settings` holds what it is sent **in memory for the life of
 * the process** so the model client can be built from it, and writes no file, because the key
 * is a credential and a server-side copy of it is a liability nobody asked for. Two
 * consequences this screen has to be honest about:
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
   */
  const load = useCallback(() => {
    api
      .settings()
      .then(async (definitions) => {
        const stored = readModelSettings()
        const applied = await api.saveSettings(stored)
        setSettings(applied)
        // Seeded from what is stored, falling back to the server's own value so a fresh
        // browser opens showing what it will actually use rather than four empty boxes. A
        // secret is never seeded: the server only ever sends a mask, and putting that in the
        // field would make the next save write the mask as the key.
        setDrafts(
          Object.fromEntries(
            definitions.fields
              .filter((field) => !field.secret)
              .map((field) => [
                field.key,
                stored[field.key as keyof StoredModelSettings] ??
                  field.value ??
                  "",
              ]),
          ),
        )
        setTouched({})
      })
      .catch(setError)
  }, [])

  useEffect(load, [load])

  /** The whole picture, because the browser is the store of record rather than a diff. */
  function current(): StoredModelSettings {
    if (!settings) return {}
    const values: StoredModelSettings = {}
    for (const field of settings.fields) {
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
      const kept = writeModelSettings(values)
      // Pushed even when storage refused, so the session still behaves as the form says - the
      // alternative is a Save button that appears to do nothing at all.
      const applied = await api.saveSettings(values)
      setSettings(applied)
      // Re-seed from what was just saved, and forget what was touched. Without this the secret
      // box keeps the typed key and stays "touched", so the form reads as dirty after a
      // successful save.
      //
      // Seeded from `values` rather than from `applied.fields`, which is the trap: a field's
      // `value` in the response is the *server's environment* value, and that is usually null
      // because the whole point of this page is that the server has nothing. Seeding from it
      // blanked every box the moment Save succeeded, and only a reload - which re-seeds from
      // storage - brought them back. The response is still what the "In effect on the server"
      // card reads, because that is the one thing only the server can resolve.
      setDrafts(
        Object.fromEntries(
          applied.fields
            .filter((f) => !f.secret)
            .map((f) => [
              f.key,
              values[f.key as keyof StoredModelSettings] ?? "",
            ]),
        ),
      )
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
      setSettings(await api.saveSettings({}))
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

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Models</CardTitle>
          <CardDescription>
            Stored in this browser and pushed to the API on change. The server
            keeps nothing, so these survive without a settings file on it. The
            CLI reads the same names from its own environment.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {settings.any_pinned && (
            <p className="rounded-md border border-radiant-500/40 bg-radiant-500/5 p-3 text-xs text-radiant-200">
              This server was started with some of these already set in its
              environment, and those win — a launched variable outranks a
              browser, so an edit to a pinned field will be accepted and have no
              effect. They are marked below.
            </p>
          )}

          {settings.fields.map((field) => (
            <Field
              key={field.key}
              field={field}
              value={drafts[field.key] ?? ""}
              touched={touched[field.key] === true}
              pinned={pinned.has(field.key)}
              onChange={(value) => edit(field, value)}
            />
          ))}

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
              <span className="text-xs text-parchment/50">Unsaved changes</span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* What the next run will actually do, resolved by the backend through the same merge the
          service uses. It cannot be derived from the boxes above: a name containing a slash
          means OpenRouter only while a key is present, and a pinned field overrides its box
          whatever the box says. */}
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
                backend={settings.reasoning_backend}
              />
            </Row>
            <Row label="Fast">
              <Resolved
                model={settings.fast_model}
                backend={settings.fast_backend}
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

/** One model box, with its label, help and whether the server pins it. */
function Field({
  field,
  value,
  touched,
  pinned,
  onChange,
}: {
  field: SettingField
  value: string
  touched: boolean
  pinned: boolean
  onChange: (value: string) => void
}) {
  const [revealed, setRevealed] = useState(false)

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
      </div>

      <div className="flex gap-2">
        <Input
          id={field.key}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          // A secret is a password box, but one that can be revealed while typing: the value is
          // never echoed anywhere else, so hiding it only makes a typo invisible.
          type={field.secret && !revealed ? "password" : "text"}
          autoComplete="off"
          spellCheck={false}
          placeholder={
            field.secret && field.value
              ? `Server has ${field.value}`
              : "Not set"
          }
          className="font-mono"
        />
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
      </div>

      <p className="text-xs text-parchment/50">
        {field.help}
        {/* A secret box is never pre-filled — there is nothing to pre-fill it with, since the
            server only ever sends a mask — so this line is the only thing on screen that says
            whether a key is held anywhere. It says "in use" rather than "in the environment"
            because the value may be the one this browser pushed, not the server's own. */}
        {field.secret && field.value && !touched && (
          <>
            {" "}
            A key is in use:{" "}
            <code className="text-parchment/70">{field.value}</code>.
          </>
        )}
      </p>
    </div>
  )
}

function Resolved({
  model,
  backend,
}: {
  model: string | null
  backend: string | null
}) {
  if (!model) return <span className="text-parchment/50">Not resolved</span>
  return (
    <span className="flex flex-wrap items-center gap-2">
      <code className="text-parchment/90">{model}</code>
      {backend && <Badge tone="arcane">{backend}</Badge>}
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
