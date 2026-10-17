import { useEffect, useState } from 'react'
import { Copy, Check, Loader2, Newspaper, Trophy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { apiGet, errorMessage } from '@/lib/api'

/**
 * KOL leaderboard + weekly digest (docs/kol-scorecard.md, step 3). Only
 * verified calls with an assigned speaker are ever counted or published.
 */

interface KolScore {
  entity_id: string
  label: string
  resolved: number
  hits: number
  hit_rate?: number | null
  score: number
  bold_hits: number
  too_vague_rate?: number | null
  open_calls: number
}

interface DigestResponse {
  markdown: string
  stats: { new_calls: number; came_due: number; kols: number }
}

const pct = (v?: number | null) => (v === null || v === undefined ? '–' : `${Math.round(v * 100)}%`)

function isoDay(d: Date) {
  return d.toISOString().slice(0, 10)
}

export function ScorecardPanel() {
  const today = new Date()
  const [minResolved, setMinResolved] = useState(5)
  const [board, setBoard] = useState<KolScore[] | null>(null)
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 6 * 86400000)))
  const [end, setEnd] = useState(isoDay(today))
  const [digest, setDigest] = useState<DigestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<{ kols: KolScore[] }>(`/api/scorecard/leaderboard?min_resolved=${minResolved}`)
      .then(r => setBoard(r.kols))
      .catch(err => setError(errorMessage(err)))
  }, [minResolved])

  async function generate() {
    setLoading(true)
    setError(null)
    setCopied(false)
    try {
      setDigest(await apiGet<DigestResponse>(`/api/scorecard/digest?start=${start}&end=${end}`))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function copy() {
    if (!digest) return
    try {
      await navigator.clipboard.writeText(digest.markdown)
      setCopied(true)
    } catch {
      setError('Copy failed. Select the text and copy it manually.')
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Trophy className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">Leaderboard</h2>
          <label className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
            min. resolved
            <Input type="number" min={1} max={100} value={minResolved}
              onChange={e => setMinResolved(Math.max(1, Number(e.target.value) || 1))}
              className="h-7 w-16 text-xs" aria-label="Minimum resolved calls" />
          </label>
        </div>
        {board && board.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No KOL has {minResolved} resolved calls yet. Verify calls in “Review calls”; price calls
            resolve automatically when they hit or come due.
          </p>
        )}
        {board && board.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="text-left">
                  <th className="py-1.5 pr-2">#</th>
                  <th className="py-1.5 pr-2">KOL</th>
                  <th className="py-1.5 pr-2 text-right">Resolved</th>
                  <th className="py-1.5 pr-2 text-right">Hit rate</th>
                  <th className="py-1.5 pr-2 text-right" title="Wilson lower bound: rewards a long track record">Score</th>
                  <th className="py-1.5 pr-2 text-right" title="Correct calls ≥25% away from the price when made">Bold hits</th>
                  <th className="py-1.5 pr-2 text-right">Too vague</th>
                  <th className="py-1.5 text-right">Open</th>
                </tr>
              </thead>
              <tbody>
                {board.map((k, i) => (
                  <tr key={k.entity_id} className="border-t border-border">
                    <td className="py-1.5 pr-2">{i + 1}</td>
                    <td className="py-1.5 pr-2 font-medium">{k.label}</td>
                    <td className="py-1.5 pr-2 text-right">{k.resolved}</td>
                    <td className="py-1.5 pr-2 text-right">{pct(k.hit_rate)}</td>
                    <td className="py-1.5 pr-2 text-right">{k.score.toFixed(2)}</td>
                    <td className="py-1.5 pr-2 text-right">{k.bold_hits}</td>
                    <td className="py-1.5 pr-2 text-right">{pct(k.too_vague_rate)}</td>
                    <td className="py-1.5 text-right">{k.open_calls}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">Weekly digest</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input type="date" value={start} onChange={e => setStart(e.target.value)}
            className="h-8 w-36 text-xs" aria-label="From" />
          <span className="text-xs text-muted-foreground">to</span>
          <Input type="date" value={end} onChange={e => setEnd(e.target.value)}
            className="h-8 w-36 text-xs" aria-label="To" />
          <Button size="sm" onClick={generate} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <Newspaper />} Generate
          </Button>
          {digest && (
            <Button size="sm" variant="outline" onClick={copy}>
              {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy markdown'}
            </Button>
          )}
        </div>
        {digest && (
          <>
            <p className="text-xs text-muted-foreground">
              {digest.stats.new_calls} new calls · {digest.stats.came_due} came due · {digest.stats.kols} KOLs
            </p>
            <pre className="bg-muted rounded-lg p-3 text-xs whitespace-pre-wrap max-h-[28rem] overflow-y-auto">
              {digest.markdown}
            </pre>
          </>
        )}
      </section>

      {error && (
        <div className="bg-destructive/10 text-destructive rounded-lg p-2.5 sm:p-3 text-xs sm:text-sm">
          {error}
        </div>
      )}
    </div>
  )
}
