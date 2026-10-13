import { useState, useEffect, useRef, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { MessageSquare, X, Loader2, Send, RefreshCw } from 'lucide-react'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { AnnotationThread } from './AnnotationThread'
import { AnnotationForm } from './AnnotationForm'
import { wsUrl } from '@/lib/desktop'

export interface Annotation {
  id: string
  job_id: string
  content: string
  user_id: string
  user_name?: string
  segment_start?: number
  segment_end?: number
  parent_id?: string
  replies: Annotation[]
  created_at: string
  updated_at: string
}

interface AnnotationPanelProps {
  jobId: string
  isOpen: boolean
  onClose: () => void
  currentUserId?: string
  currentUserName?: string
  selectedSegment?: { start: number; end: number } | null
  onSegmentClick?: (start: number, end: number) => void
}

export function AnnotationPanel({
  jobId,
  isOpen,
  onClose,
  currentUserId = 'anonymous',
  currentUserName,
  selectedSegment,
  onSegmentClick,
}: AnnotationPanelProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)

  const fetchAnnotations = useCallback(async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}/annotations`)
      if (!response.ok) throw new Error('Failed to load annotations')
      const data = await response.json()
      setAnnotations(data.annotations)
      setError(null)
    } catch {
      setError('Failed to load annotations')
    } finally {
      setLoading(false)
    }
  }, [jobId])

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!isOpen) return

    fetchAnnotations()

    // Connect to WebSocket
    const ws = new WebSocket(wsUrl(`/api/jobs/${jobId}/annotations/ws`))

    ws.onopen = () => {
      setConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'annotation_created') {
          setAnnotations((prev) => {
            const annotation = data.annotation
            if (annotation.parent_id) {
              // It's a reply, add to parent's replies
              return prev.map((a) =>
                a.id === annotation.parent_id
                  ? { ...a, replies: [...a.replies, annotation] }
                  : a
              )
            }
            // New top-level annotation
            return [...prev, { ...annotation, replies: [] }]
          })
        } else if (data.type === 'annotation_updated') {
          setAnnotations((prev) =>
            prev.map((a) =>
              a.id === data.annotation.id
                ? { ...a, ...data.annotation }
                : {
                    ...a,
                    replies: a.replies.map((r) =>
                      r.id === data.annotation.id ? { ...r, ...data.annotation } : r
                    ),
                  }
            )
          )
        } else if (data.type === 'annotation_deleted') {
          setAnnotations((prev) =>
            prev
              .filter((a) => a.id !== data.annotation_id)
              .map((a) => ({
                ...a,
                replies: a.replies.filter((r) => r.id !== data.annotation_id),
              }))
          )
        }
      } catch {
        // Ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setConnected(false)
    }

    // Ping to keep connection alive
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 30000)

    wsRef.current = ws

    return () => {
      clearInterval(pingInterval)
      ws.close()
    }
  }, [isOpen, jobId, fetchAnnotations])

  const handleCreateAnnotation = async (content: string, segmentStart?: number, segmentEnd?: number) => {
    try {
      const response = await fetch(`/api/jobs/${jobId}/annotations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          user_id: currentUserId,
          user_name: currentUserName,
          segment_start: segmentStart,
          segment_end: segmentEnd,
        }),
      })

      if (!response.ok) throw new Error('Failed to create annotation')

      setShowForm(false)
    } catch {
      setError('Failed to create annotation')
    }
  }

  const handleReply = async (parentId: string, content: string) => {
    try {
      const response = await fetch(`/api/annotations/${parentId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          user_id: currentUserId,
          user_name: currentUserName,
        }),
      })

      if (!response.ok) throw new Error('Failed to create reply')

      setReplyTo(null)
    } catch {
      setError('Failed to create reply')
    }
  }

  const handleDelete = async (annotationId: string) => {
    if (!confirm('Delete this annotation?')) return

    try {
      const response = await fetch(`/api/annotations/${annotationId}`, {
        method: 'DELETE',
      })

      if (!response.ok) throw new Error('Failed to delete annotation')
    } catch {
      setError('Failed to delete annotation')
    }
  }

  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 639px)')
    setIsMobile(mq.matches)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  if (!isOpen) return null

  const panelContent = (
    <>
      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : error ? (
          <div className="text-center py-8 text-destructive text-sm">{error}</div>
        ) : annotations.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            No annotations yet. Be the first to comment!
          </div>
        ) : (
          <div className="space-y-4">
            {annotations.map((annotation) => (
              <AnnotationThread
                key={annotation.id}
                annotation={annotation}
                currentUserId={currentUserId}
                onReply={(id) => setReplyTo(id)}
                onDelete={handleDelete}
                onSegmentClick={onSegmentClick}
                replyingTo={replyTo}
                onSubmitReply={(content) => handleReply(annotation.id, content)}
                onCancelReply={() => setReplyTo(null)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Add Annotation Form */}
      <div className="border-t p-4">
        {showForm ? (
          <AnnotationForm
            onSubmit={handleCreateAnnotation}
            onCancel={() => setShowForm(false)}
            selectedSegment={selectedSegment}
          />
        ) : (
          <Button onClick={() => setShowForm(true)} className="w-full">
            <Send className="h-4 w-4 mr-2" />
            Add Annotation
          </Button>
        )}
      </div>
    </>
  )

  if (isMobile) {
    return (
      <BottomSheet open={isOpen} onClose={onClose} title="Annotations" snapPoints={[0.6, 0.9]}>
        {panelContent}
      </BottomSheet>
    )
  }

  return (
    <div className="fixed right-0 top-0 h-full w-96 max-w-full bg-card border-l shadow-xl z-50 hidden sm:flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-primary" />
          <span className="font-semibold">Annotations</span>
          <span className="text-xs text-muted-foreground">({annotations.length})</span>
          {connected && (
            <span className="w-2 h-2 bg-green-500 rounded-full" title="Real-time updates enabled" />
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={fetchAnnotations} className="h-8 w-8 p-0">
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
      {panelContent}
    </div>
  )
}
