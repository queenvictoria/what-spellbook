import { useState } from "react"
import type { ChangeEvent } from "react"
import { Loader2, Upload } from "lucide-react"

import { api } from "@/api/client"
import type { CharacterEntry } from "@/api/types"
import { ErrorNotice } from "@/components/ErrorNotice"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

const MAX_YAML_BYTES = 1_000_000
const MAX_PDF_BYTES = 20 * 1024 * 1024

export function CharacterImporter({
  onImported,
}: {
  onImported: (entry: CharacterEntry) => void | Promise<void>
}) {
  const [overwrite, setOverwrite] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState("")
  const [draft, setDraft] = useState<{ filename: string; content: string } | null>(null)

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ""
    if (!file) return

    setError(null)
    setMessage("")
    setDraft(null)

    const extension = file.name.split(".").pop()?.toLowerCase()
    const maxBytes = extension === "pdf" ? MAX_PDF_BYTES : MAX_YAML_BYTES
    if (file.size > maxBytes) {
      setError(new Error(`Files must be no larger than ${extension === "pdf" ? "20 MB" : "1 MB"}.`))
      return
    }

    setBusy(true)
    try {
      if (extension === "pdf") {
        const parsed = await api.parseCharacterPdf(file)
        setDraft({
          filename: parsed.suggested_filename,
          content: parsed.content,
        })
      } else if (extension === "yaml") {
        const entry = await api.importCharacter({
          filename: file.name,
          content: await file.text(),
          overwrite,
        })
        await onImported(entry)
        setMessage(`Imported ${entry.name}.`)
      } else {
        setError(new Error("Choose a .yaml character sheet or a D&D Beyond .pdf export."))
      }
    } catch (reason) {
      setError(reason)
    } finally {
      setBusy(false)
    }
  }

  async function saveDraft() {
    if (!draft) return
    setError(null)
    setMessage("")
    setBusy(true)
    try {
      const entry = await api.importCharacter({ ...draft, overwrite })
      await onImported(entry)
      setDraft(null)
      setMessage(`Imported ${entry.name}.`)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-void-700 px-3 text-xs text-parchment/80 hover:bg-void-800">
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
        {busy ? "Importing…" : "Import sheet"}
        <input
          type="file"
          accept=".yaml,.pdf,application/pdf,application/yaml,text/yaml"
          className="sr-only"
          disabled={busy}
          onChange={importFile}
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-parchment/55">
        <input
          type="checkbox"
          checked={overwrite}
          onChange={(event) => setOverwrite(event.target.checked)}
          disabled={busy}
        />
        Replace an existing sheet
      </label>
      {message && <span role="status" className="text-xs text-verdant-300">{message}</span>}
      <p className="w-full text-xs text-parchment/45">
        PDF text is sent to the configured model for extraction. Review the YAML before saving;
        the PDF itself is not stored.
      </p>
      {error != null && <ErrorNotice error={error} compact className="w-full" />}
      {draft && (
        <div className="w-full space-y-2 rounded-md border border-void-700 p-3">
          <p className="text-xs text-parchment/65">Review and correct the extracted values before saving.</p>
          <label className="block space-y-1 text-xs text-parchment/65">
            Filename
            <Input
              value={draft.filename}
              onChange={(event) =>
                setDraft((current) => current && { ...current, filename: event.target.value })
              }
              disabled={busy}
            />
          </label>
          <label className="block space-y-1 text-xs text-parchment/65">
            Extracted YAML
            <Textarea
              rows={12}
              value={draft.content}
              onChange={(event) =>
                setDraft((current) => current && { ...current, content: event.target.value })
              }
              disabled={busy}
              spellCheck={false}
            />
          </label>
          <div className="flex gap-2">
            <Button size="sm" onClick={saveDraft} disabled={busy || !draft.filename.trim()}>
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save character
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDraft(null)} disabled={busy}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
