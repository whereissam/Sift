import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import {
  Loader2,
  Copy,
  Check,
  Download,
  Scissors,
  Sparkles,
  Hash,
  TrendingUp,
  RefreshCw,
  Clock,
  ChevronRight,
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

interface TranscriptionJobSummary {
  job_id: string
  status: string
  text?: string
  language?: string
  duration_seconds?: number
  created_at: string
  has_segments: boolean
}

export function ClipsPage() {
  const [jobs, setJobs] = useState<TranscriptionJobSummary[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [clips, setClips] = useState<ClipSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aiAvailable, setAiAvailable] = useState(false)

  // Fetch completed transcription jobs
  useEffect(() => {
    fetchJobs()
    checkAiAvailability()
  }, [])

  const fetchJobs = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/clips/transcriptions?limit=50')
      if (response.ok) {
        const data = await response.json()
        // Filter to only completed jobs
        const completedJobs = (data.jobs || [])
          .filter((j: any) => j.status === 'completed')
          .map((j: any) => ({
            job_id: j.job_id,
            status: j.status,
            text: j.text,
            language: j.language,
            duration_seconds: j.duration_seconds,
            created_at: j.created_at,
            has_segments: j.has_segments,
          }))
        setJobs(completedJobs)
      }
    } catch (err) {
      console.error('Failed to fetch jobs:', err)
    } finally {
      setLoading(false)
    }
  }

  const checkAiAvailability = async () => {
    try {
      const response = await fetch('/api/ai/settings')
      if (response.ok) {
        setAiAvailable(true)
      }
    } catch {
      setAiAvailable(false)
    }
  }

  const handleSelectJob = async (jobId: string) => {
    setSelectedJobId(jobId)
    setError(null)
    setClips([])

    // Fetch existing clips for this job
    try {
      const response = await fetch(`/api/jobs/${jobId}/clips`)
      if (response.ok) {
        const data: ClipsResponse = await response.json()
        if (data.clips && data.clips.length > 0) {
          setClips(data.clips)
        }
      }
    } catch (err) {
      console.error('Failed to fetch clips:', err)
    }
  }

  const handleGenerateClips = async () => {
    if (!selectedJobId) return

    setGenerating(true)
    setError(null)

    try {
      const response = await fetch(`/api/jobs/${selectedJobId}/clips`, {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate clips')
    } finally {
      setGenerating(false)
    }
  }

  // Job selection view
  if (!selectedJobId) {
    return (
      <div className="w-full max-w-2xl mx-auto text-muted-foreground">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Scissors className="h-5 w-5 text-primary" />
            Select a Transcription
          </h2>
          <Button variant="ghost" size="sm" onClick={fetchJobs} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>

        {!aiAvailable && (
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3 mb-4 text-sm text-yellow-800 dark:text-yellow-200">
            Configure an AI provider in Settings to generate viral clips.
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <Scissors className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p>No completed transcriptions found.</p>
            <p className="text-sm mt-1">Transcribe some audio first to generate viral clips.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map((job) => (
              <button
                key={job.job_id}
                onClick={() => job.has_segments && handleSelectJob(job.job_id)}
                disabled={!job.has_segments}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  job.has_segments
                    ? 'border-border hover:border-primary hover:bg-muted/50 cursor-pointer'
                    : 'border-border/50 opacity-50 cursor-not-allowed'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {job.text || 'Untitled transcription'}
                    </p>
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      {job.language && <span>{job.language.toUpperCase()}</span>}
                      {job.duration_seconds && (
                        <>
                          <span>•</span>
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {formatDuration(job.duration_seconds)}
                          </span>
                        </>
                      )}
                      {!job.has_segments && (
                        <>
                          <span>•</span>
                          <span className="text-yellow-600">No segments</span>
                        </>
                      )}
                    </div>
                  </div>
                  {job.has_segments && (
                    <ChevronRight className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  // Clip generation view
  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="flex items-center gap-2 mb-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setSelectedJobId(null)
            setClips([])
            setError(null)
          }}
        >
          <ChevronRight className="h-4 w-4 rotate-180" />
          Back
        </Button>
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Scissors className="h-5 w-5 text-primary" />
          Viral Clips
        </h2>
      </div>

      {/* Generate Button */}
      <Button
        onClick={handleGenerateClips}
        disabled={generating || !aiAvailable}
        className="w-full h-12 mb-4"
        variant={clips.length > 0 ? 'outline' : 'default'}
      >
        {generating ? (
          <>
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Analyzing for viral moments...
          </>
        ) : (
          <>
            <Sparkles className="mr-2 h-5 w-5" />
            {clips.length > 0 ? 'Regenerate Viral Clips' : 'Generate Viral Clips'}
          </>
        )}
      </Button>

      {/* Error */}
      {error && (
        <div className="bg-destructive/10 text-destructive rounded-lg p-3 mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Clips List */}
      {clips.length > 0 ? (
        <div className="space-y-4">
          {clips.map((clip, index) => (
            <ClipCard key={clip.clip_id} clip={clip} index={index} jobId={selectedJobId} />
          ))}
        </div>
      ) : !generating && (
        <div className="text-center py-8 text-muted-foreground">
          <Sparkles className="h-10 w-10 mx-auto mb-3 opacity-50" />
          <p>Click "Generate Viral Clips" to find the best moments</p>
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
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-border bg-muted/30">
        <span className="text-sm font-bold text-primary bg-primary/10 px-2.5 py-1 rounded-full">
          #{index + 1}
        </span>
        <div className="flex-1">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            {formatDuration(clip.start_time)} - {formatDuration(clip.end_time)}
            <span className="text-muted-foreground/50">({formatDuration(clip.duration)})</span>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-sm font-medium ${viralLabel.color}`}>
          <TrendingUp className="h-4 w-4" />
          {(clip.viral_score * 100).toFixed(0)}% viral
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Hook */}
        <div className="bg-gradient-to-r from-primary/5 to-primary/10 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-primary uppercase tracking-wide">Opening Hook</span>
            <Button variant="ghost" size="sm" onClick={handleCopyHook} className="h-7 px-2">
              {hookCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              <span className="ml-1 text-xs">{hookCopied ? 'Copied' : 'Copy'}</span>
            </Button>
          </div>
          <p className="text-base font-medium text-foreground">"{clip.hook}"</p>
        </div>

        {/* Caption + Hashtags */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Hash className="h-3.5 w-3.5" />
              Caption & Hashtags
            </span>
            <Button variant="ghost" size="sm" onClick={handleCopyCaption} className="h-7 px-2">
              {captionCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              <span className="ml-1 text-xs">{captionCopied ? 'Copied' : 'Copy'}</span>
            </Button>
          </div>
          <div className="bg-muted rounded-lg p-3">
            <p className="text-sm text-foreground mb-2">{clip.caption}</p>
            <p className="text-sm text-primary font-medium">
              {clip.hashtags.map(h => `#${h}`).join(' ')}
            </p>
          </div>
        </div>

        {/* Engagement Factors */}
        {Object.keys(clip.engagement_factors).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(clip.engagement_factors)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 4)
              .map(([factor, score]) => (
                <span
                  key={factor}
                  className={`text-xs px-2 py-1 rounded-full font-medium ${
                    score >= 0.7
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : score >= 0.4
                      ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                  }`}
                >
                  {factor} {(score * 100).toFixed(0)}%
                </span>
              ))}
          </div>
        )}

        {/* Platform Export Buttons */}
        <div className="pt-2 border-t border-border">
          <span className="text-xs font-medium text-muted-foreground block mb-2">
            Export for Platform
          </span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {SOCIAL_PLATFORMS.filter(p => clip.compatible_platforms.includes(p.value)).map(
              platform => {
                const isExported = !!exportedFiles[platform.value]
                const isExporting = exporting === platform.value

                return (
                  <div key={platform.value}>
                    {!isExported ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleExport(platform.value)}
                        disabled={isExporting || exporting !== null}
                        className="h-10 text-xs w-full"
                      >
                        {isExporting ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <>
                            <span className="mr-1.5 text-base">{platform.icon}</span>
                            {platform.label.split(' ')[0]}
                          </>
                        )}
                      </Button>
                    ) : (
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => handleDownload(platform.value)}
                        className="h-10 text-xs w-full"
                      >
                        <Download className="h-4 w-4 mr-1" />
                        {platform.label.split(' ')[0]}
                      </Button>
                    )}
                  </div>
                )
              }
            )}
          </div>
          {clip.compatible_platforms.length === 0 && (
            <p className="text-xs text-muted-foreground italic mt-2">
              Clip duration exceeds all platform limits
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default ClipsPage
