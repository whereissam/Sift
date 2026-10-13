import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import {
  Loader2,
  Copy,
  Check,
  ChevronDown,
  Download,
  Scissors,
  Sparkles,
  Hash,
  TrendingUp,
} from 'lucide-react'
import {
  ClipSuggestion,
  ClipsResponse,
  SocialPlatform,
  SOCIAL_PLATFORMS,
  formatDuration,
  getViralScoreLabel,
} from '../downloader/types'
import { apiUrl } from '@/lib/desktop'

interface ClipsSectionProps {
  jobId: string
  hasTranscript: boolean
}

export function ClipsSection({ jobId, hasTranscript }: ClipsSectionProps) {
  const [expanded, setExpanded] = useState(false)
  const [clips, setClips] = useState<ClipSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [available, setAvailable] = useState<boolean | null>(null)
  const [availabilityReason, setAvailabilityReason] = useState<string | null>(null)

  // Check availability on mount
  useEffect(() => {
    if (!hasTranscript) {
      setAvailable(false)
      setAvailabilityReason('No transcript available')
      return
    }

    fetch(`/api/jobs/${jobId}/clips/available`)
      .then(res => res.json())
      .then(data => {
        setAvailable(data.available)
        setAvailabilityReason(data.reason || null)
        if (data.available) {
          // Check if clips already exist
          fetch(`/api/jobs/${jobId}/clips`)
            .then(res => res.json())
            .then(data => {
              if (data.clips && data.clips.length > 0) {
                setClips(data.clips)
                setExpanded(true)
              }
            })
            .catch(() => {})
        }
      })
      .catch(() => {
        setAvailable(false)
        setAvailabilityReason('Failed to check availability')
      })
  }, [jobId, hasTranscript])

  const handleGenerateClips = async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/jobs/${jobId}/clips`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          max_clips: 5,
          min_viral_score: 0.4,
        }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || 'Failed to generate clips')
      }

      const data: ClipsResponse = await response.json()

      if (!data.success) {
        throw new Error(data.error || 'Failed to generate clips')
      }

      setClips(data.clips)
      setExpanded(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate clips')
    } finally {
      setLoading(false)
    }
  }

  if (available === false) {
    return (
      <div className="bg-card rounded-xl shadow-lg p-3 sm:p-4 mb-3 sm:mb-6 opacity-60">
        <div className="flex items-center gap-2">
          <Scissors className="h-4 w-4 sm:h-5 sm:w-5 text-muted-foreground" />
          <span className="font-medium text-sm sm:text-base text-muted-foreground">Viral Clips</span>
          <span className="text-xs text-muted-foreground">({availabilityReason})</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-card rounded-xl shadow-lg p-3 sm:p-4 mb-3 sm:mb-6 text-muted-foreground">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left min-h-[44px]"
      >
        <Scissors className="h-4 w-4 sm:h-5 sm:w-5 text-primary flex-shrink-0" />
        <span className="font-medium text-sm sm:text-base flex-1">Viral Clips</span>
        {clips.length > 0 && (
          <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
            {clips.length} clip{clips.length !== 1 ? 's' : ''}
          </span>
        )}
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {expanded && (
        <div className="mt-3 sm:mt-4 space-y-4">
          {/* Generate Button */}
          <Button
            onClick={handleGenerateClips}
            disabled={loading || available === null}
            className="w-full h-10 sm:h-11"
            variant={clips.length > 0 ? 'outline' : 'default'}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                <span className="text-sm">Analyzing transcript...</span>
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4" />
                <span className="text-sm">
                  {clips.length > 0 ? 'Regenerate Viral Clips' : 'Generate Viral Clips'}
                </span>
              </>
            )}
          </Button>

          {/* Error */}
          {error && (
            <div className="bg-destructive/10 text-destructive rounded-lg p-2.5 sm:p-3 text-xs sm:text-sm">
              {error}
            </div>
          )}

          {/* Clips List */}
          {clips.length > 0 && (
            <div className="space-y-3">
              {clips.map((clip, index) => (
                <ClipCard key={clip.clip_id} clip={clip} index={index} jobId={jobId} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface ClipCardProps {
  clip: ClipSuggestion
  index: number
  jobId: string
}

function ClipCard({ clip, index, jobId }: ClipCardProps) {
  const [expanded, setExpanded] = useState(index === 0)
  const [hookCopied, setHookCopied] = useState(false)
  const [captionCopied, setCaptionCopied] = useState(false)
  const [exporting, setExporting] = useState<SocialPlatform | null>(null)
  const [exportedFiles, setExportedFiles] = useState<Record<string, string>>(
    clip.exported_files || {}
  )

  const viralLabel = getViralScoreLabel(clip.viral_score)

  const handleCopyHook = async () => {
    await navigator.clipboard.writeText(clip.hook)
    setHookCopied(true)
    setTimeout(() => setHookCopied(false), 2000)
  }

  const handleCopyCaption = async () => {
    const fullCaption = `${clip.caption}\n\n${clip.hashtags.map(h => `#${h}`).join(' ')}`
    await navigator.clipboard.writeText(fullCaption)
    setCaptionCopied(true)
    setTimeout(() => setCaptionCopied(false), 2000)
  }

  const handleExport = async (platform: SocialPlatform) => {
    setExporting(platform)

    try {
      const response = await fetch(`/api/jobs/${jobId}/clips/${clip.clip_id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          quality: 'high',
          format: 'mp3',
        }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || 'Export failed')
      }

      const data = await response.json()
      if (data.success && data.file_path) {
        setExportedFiles(prev => ({ ...prev, [platform]: data.file_path }))
      }
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setExporting(null)
    }
  }

  const handleDownload = (platform: SocialPlatform) => {
    window.open(apiUrl(`/api/jobs/${jobId}/clips/${clip.clip_id}/download/${platform}`), '_blank')
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full p-3 text-left bg-muted/50 hover:bg-muted/70 transition-colors"
      >
        <span className="text-xs font-medium text-primary bg-primary/10 px-2 py-0.5 rounded">
          #{index + 1}
        </span>
        <span className="text-xs text-muted-foreground">
          {formatDuration(clip.start_time)} - {formatDuration(clip.end_time)}
        </span>
        <span className="text-xs text-muted-foreground">({formatDuration(clip.duration)})</span>
        <span className={`text-xs font-medium ${viralLabel.color} ml-auto flex items-center gap-1`}>
          <TrendingUp className="h-3 w-3" />
          {(clip.viral_score * 100).toFixed(0)}%
        </span>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Content */}
      {expanded && (
        <div className="p-3 space-y-3">
          {/* Hook */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-muted-foreground">Opening Hook</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopyHook}
                className="h-6 w-6 p-0"
              >
                {hookCopied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
            <p className="text-sm font-medium text-foreground bg-muted rounded px-2 py-1.5">
              "{clip.hook}"
            </p>
          </div>

          {/* Transcript Preview */}
          <div>
            <span className="text-xs font-medium text-muted-foreground block mb-1">
              Transcript Preview
            </span>
            <p className="text-xs text-muted-foreground bg-muted rounded px-2 py-1.5 line-clamp-3">
              {clip.transcript_text}
            </p>
          </div>

          {/* Caption + Hashtags */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                <Hash className="h-3 w-3" />
                Caption & Hashtags
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopyCaption}
                className="h-6 w-6 p-0"
              >
                {captionCopied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
            <div className="bg-muted rounded px-2 py-1.5">
              <p className="text-xs text-foreground mb-1">{clip.caption}</p>
              <p className="text-xs text-primary">
                {clip.hashtags.map(h => `#${h}`).join(' ')}
              </p>
            </div>
          </div>

          {/* Engagement Factors */}
          {Object.keys(clip.engagement_factors).length > 0 && (
            <div>
              <span className="text-xs font-medium text-muted-foreground block mb-1">
                Engagement Factors
              </span>
              <div className="flex flex-wrap gap-1">
                {Object.entries(clip.engagement_factors)
                  .sort(([, a], [, b]) => b - a)
                  .map(([factor, score]) => (
                    <span
                      key={factor}
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        score >= 0.7
                          ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                          : score >= 0.4
                          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                          : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                      }`}
                    >
                      {factor}: {(score * 100).toFixed(0)}%
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* Platform Export Buttons */}
          <div>
            <span className="text-xs font-medium text-muted-foreground block mb-2">
              Export for Platform
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {SOCIAL_PLATFORMS.filter(p =>
                clip.compatible_platforms.includes(p.value)
              ).map(platform => {
                const isExported = !!exportedFiles[platform.value]
                const isExporting = exporting === platform.value

                return (
                  <div key={platform.value} className="flex flex-col gap-1">
                    {!isExported ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleExport(platform.value)}
                        disabled={isExporting || exporting !== null}
                        className="h-9 text-xs w-full"
                      >
                        {isExporting ? (
                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <span className="mr-1">{platform.icon}</span>
                        )}
                        {platform.label}
                      </Button>
                    ) : (
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => handleDownload(platform.value)}
                        className="h-9 text-xs w-full"
                      >
                        <Download className="h-3 w-3 mr-1" />
                        {platform.label}
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
            {clip.compatible_platforms.length === 0 && (
              <p className="text-xs text-muted-foreground italic">
                Clip duration exceeds all platform limits
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default ClipsSection
