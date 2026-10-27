import { useEffect, useState } from 'react'

/**
 * Hook to detect text selection in a ref.
 *
 * Returns the selected text and a callback to clear the selection.
 */
export function useSelection(ref: React.RefObject<HTMLElement | null>) {
  const [selectedText, setSelectedText] = useState('')

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const handleSelectionChange = () => {
      const selection = window.getSelection()
      if (!selection || selection.rangeCount === 0) {
        setSelectedText('')
        return
      }

      const range = selection.getRangeAt(0)
      const text = range.toString().trim()

      // Only consider selections that are not empty and are within the element
      if (text.length > 0 && element.contains(range.commonAncestorContainer)) {
        setSelectedText(text)
      } else {
        setSelectedText('')
      }
    }

    document.addEventListener('selectionchange', handleSelectionChange)
    return () => {
      document.removeEventListener('selectionchange', handleSelectionChange)
    }
  }, [ref])

  const clearSelection = () => {
    window.getSelection()?.removeAllRanges()
    setSelectedText('')
  }

  return { selectedText, clearSelection }
}