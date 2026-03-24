import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Clock, Loader2, Send, X } from 'lucide-react'
import { formatDuration } from '@/components/downloader/types'

interface AnnotationFormProps {
  onSubmit: (content: string, segmentStart?: number, segmentEnd?: number) => Promise<void>
  onCancel: () => void
  selectedSegment?: { start: number; end: number } | null
}

export function AnnotationForm({ onSubmit, onCancel, selectedSegment }: AnnotationFormProps) {
  const [content, setContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [useSegment, setUseSegment] = useState(!!selectedSegment)

  const handleSubmit = async () => {
    if (!content.trim()) return

    setSubmitting(true)
    try {
      await onSubmit(
        content,
        useSegment && selectedSegment ? selectedSegment.start : undefined,
        useSegment && selectedSegment ? selectedSegment.end : undefined
      )
      setContent('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* Segment Selection */}
      {selectedSegment && (
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={useSegment}
              onChange={(e) => setUseSegment(e.target.checked)}
              className="rounded"
            />
            <Clock className="h-4 w-4 text-primary" />
            <span>
              Attach to segment: {formatDuration(selectedSegment.start)} -{' '}
              {formatDuration(selectedSegment.end)}
            </span>
          </label>
        </div>
      )}

      {/* Content Input */}
      <textarea
        placeholder="Write your annotation..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
        disabled={submitting}
        className="w-full min-h-[80px] p-3 border rounded-lg resize-none text-sm bg-background"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && e.metaKey) {
            handleSubmit()
          }
        }}
      />

      {/* Actions */}
      <div className="flex justify-between items-center">
        <span className="text-xs text-muted-foreground">
          Press {navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+Enter to submit
        </span>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={submitting}>
            <X className="h-4 w-4 mr-1" />
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={!content.trim() || submitting}>
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Send className="h-4 w-4 mr-1" />
                Add
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
