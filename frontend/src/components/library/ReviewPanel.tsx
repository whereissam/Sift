import { useCallback, useEffect, useState } from 'react'
import { Check, X, Undo2, Loader2, ExternalLink, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { apiGet, apiPost, apiPut, errorMessage, formatTimestamp, sourceLinkAt } from '@/lib/api'

/**
 * Human review of extracted predictions before they are published on the
 * KOL scorecard (docs/kol-scorecard.md): is the quote right, and who said it?
 * A call can only be verified once its speaker is assigned to a KOL.
 */

type ReviewStatus = 'unreviewed' | 'verified' | 'rejected'

interface QueueItem {
  claim_id: string
  episode_id: string
  episode_title?: string | null
  source_url?: string | null
  text: string
  evidence_excerpt?: string | null
  speaker?: string | null
  timestamp_start?: number | null
  target_horizon?: string | null
  kol_entity_id?: string | null
  kol_name?: string | null
  review_status: ReviewStatus
  review_note?: string | null
}

interface Kol {
  entity_id: string
  name: string
  handles: { platform: string; handle: string }[]
}

const FILTERS: { value: ReviewStatus; label: string }[] = [
  { value: 'unreviewed', label: 'To review' },
  { value: 'verified', label: 'Verified' },
  { value: 'rejected', label: 'Rejected' },
]

function SpeakerPicker({
  item,
  kols,
  onAssigned,
}: {
  item: QueueItem
  kols: Kol[]
  onAssigned: () => void
}) {
  const [newName, setNewName] = useState('')
  const [newHandle, setNewHandle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!item.speaker) {
    return <p className="text-xs text-destructive">No speaker label on this claim — reject it or re-run diarization.</p>
  }

  async function assign(entityId: string) {
    setBusy(true)
    setError(null)
    try {
      await apiPut(
        `/api/episodes/${encodeURIComponent(item.episode_id)}/speakers/${encodeURIComponent(item.speaker!)}`,
        { entity_id: entityId },
      )
      onAssigned()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function createAndAssign(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    setBusy(true)
    setError(null)
    try {
      const handles = newHandle.trim() ? [{ platform: 'x', handle: newHandle.trim() }] : []
      const kol = await apiPost<Kol>('/api/kols', { name: newName.trim(), handles })
      await assign(kol.entity_id)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Who is <span className="font-mono">{item.speaker}</span> in this episode? (applies to all their calls here)
      </p>
      {kols.length > 0 && (
        <select
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
          defaultValue=""
          disabled={busy}
          onChange={e => e.target.value && assign(e.target.value)}
          aria-label="Assign speaker to KOL"
        >
          <option value="" disabled>Pick an existing KOL…</option>
          {kols.map(k => (
            <option key={k.entity_id} value={k.entity_id}>
              {k.name}
              {k.handles[0] ? ` (@${k.handles[0].handle})` : ''}
            </option>
          ))}
        </select>
      )}
      <form onSubmit={createAndAssign} className="flex gap-2">
        <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder="New KOL name"
          className="h-8 text-xs" aria-label="New KOL name" />
        <Input value={newHandle} onChange={e => setNewHandle(e.target.value)} placeholder="@handle (X)"
          className="h-8 text-xs w-32" aria-label="X handle" />
        <Button type="submit" size="sm" variant="outline" disabled={busy || !newName.trim()}>
          <UserPlus /> Add
        </Button>
      </form>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function ReviewCard({
  item,
  kols,
  onChanged,
}: {
  item: QueueItem
  kols: Kol[]
  onChanged: () => void
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const link = sourceLinkAt(item.source_url, item.timestamp_start)

  async function review(status: ReviewStatus) {
    setBusy(true)
    setError(null)
    try {
      await apiPost(`/api/predictions/${encodeURIComponent(item.claim_id)}/review`, {
        status,
        note: note.trim() || undefined,
      })
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="bg-muted rounded-lg p-3 space-y-2.5">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">{item.episode_title || item.episode_id}</span>
        {link && (
          <a href={link} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 shrink-0 hover:text-foreground">
            {formatTimestamp(item.timestamp_start)} <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      <p className="text-sm font-medium leading-snug">“{item.text}”</p>
      {item.evidence_excerpt && item.evidence_excerpt !== item.text && (
        <p className="text-xs text-muted-foreground border-l-2 border-border pl-2">
          Transcript: {item.evidence_excerpt}
        </p>
      )}
      {item.target_horizon && (
        <p className="text-xs text-muted-foreground">Horizon: {item.target_horizon}</p>
      )}

      {item.kol_name ? (
        <p className="text-xs">
          Said by <span className="font-semibold">{item.kol_name}</span>
          {item.speaker && <span className="text-muted-foreground"> ({item.speaker})</span>}
        </p>
      ) : (
        <SpeakerPicker item={item} kols={kols} onAssigned={onChanged} />
      )}

      {item.review_status === 'unreviewed' ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input value={note} onChange={e => setNote(e.target.value)} placeholder="Note (optional)"
            className="h-8 text-xs flex-1 min-w-32" aria-label="Review note" />
          <Button size="sm" onClick={() => review('verified')} disabled={busy || !item.kol_entity_id}
            title={item.kol_entity_id ? undefined : 'Assign the speaker first'}>
            {busy ? <Loader2 className="animate-spin" /> : <Check />} Verify
          </Button>
          <Button size="sm" variant="outline" onClick={() => review('rejected')} disabled={busy}>
            <X /> Reject
          </Button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            {item.review_status === 'verified' ? 'Verified' : 'Rejected'}
            {item.review_note ? ` — ${item.review_note}` : ''}
          </span>
          <Button size="sm" variant="ghost" onClick={() => review('unreviewed')} disabled={busy}>
            <Undo2 /> Back to review
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </article>
  )
}

export function ReviewPanel() {
  const [filter, setFilter] = useState<ReviewStatus>('unreviewed')
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [kols, setKols] = useState<Kol[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [queue, kolList] = await Promise.all([
        apiGet<{ items: QueueItem[] }>(`/api/predictions/review-queue?status=${filter}&limit=100`),
        apiGet<{ kols: Kol[] }>('/api/kols'),
      ])
      setItems(queue.items)
      setKols(kolList.kols)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {FILTERS.map(f => (
          <Button key={f.value} size="sm" variant={filter === f.value ? 'secondary' : 'ghost'}
            onClick={() => setFilter(f.value)}>
            {f.label}
          </Button>
        ))}
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground ml-2" />}
      </div>

      <p className="text-xs text-muted-foreground">
        Check each call against the transcript and the source before it can appear on a scorecard.
        Nothing unverified is ever published.
      </p>

      {error && (
        <div className="bg-destructive/10 text-destructive rounded-lg p-2.5 sm:p-3 text-xs sm:text-sm">
          {error}
        </div>
      )}

      {items && items.length === 0 && !loading && (
        <p className="text-sm text-muted-foreground py-6 text-center">
          {filter === 'unreviewed'
            ? 'Nothing to review. Predictions appear here after knowledge extraction.'
            : 'Nothing here yet.'}
        </p>
      )}

      <div className="space-y-2">
        {items?.map(item => (
          <ReviewCard key={item.claim_id} item={item} kols={kols} onChanged={load} />
        ))}
      </div>
    </div>
  )
}
