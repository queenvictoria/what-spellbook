import { useSelection } from '@/lib/useSelection'
import { MessageSquare } from 'lucide-react'

/**
 * A button that appears when text is selected, allowing the user to ask about it.
 *
 * The button is disabled when no text is selected, and clicking it triggers the
 * ask action with the selected text.
 */
export function RulesContextButton() {
  const { selectedText, clearSelection } = useSelection({ current: null })

  const handleClick = () => {
    if (selectedText) {
      clearSelection()
    }
  }

  if (!selectedText) return null

  return (
    <button
      onClick={handleClick}
      className="flex w-full items-center justify-center gap-2 rounded-md border border-arcane-500/30 bg-arcane-500/10 px-4 py-2 text-sm text-arcane-300 transition-colors hover:bg-arcane-500/20"
      aria-label={`Ask about "${selectedText.substring(0, 50)}${selectedText.length > 50 ? '...' : ''}"`}
    >
      <MessageSquare className="h-4 w-4" />
      <span>Ask about "{selectedText.substring(0, 50)}{selectedText.length > 50 ? '...' : ''}"</span>
    </button>
  )
}