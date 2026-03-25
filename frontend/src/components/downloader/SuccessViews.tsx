import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { Download, ArrowLeft, Mic, Video, FileText, Copy, Check, Users, Sparkles, Loader2, ChevronDown, Languages, Scissors, BookOpen, Settings, ExternalLink } from 'lucide-react'
import { ContentInfo, TranscriptionResult, formatDuration } from './types'
import { useState, useMemo, useEffect } from 'react'
import { SentimentSection } from '@/components/sentiment'
import { ExtractSection } from '@/components/extract'

const SUMMARY_TYPES = [
  { value: 'bullet_points', label: 'Bullet Points', desc: 'Key ideas as bullets' },
  { value: 'chapters', label: 'Chapters', desc: 'With timestamps' },
  { value: 'key_topics', label: 'Key Topics', desc: 'Major themes' },
  { value: 'action_items', label: 'Action Items', desc: 'Tasks & follow-ups' },
  { value: 'full', label: 'Full Summary', desc: 'Comprehensive' },
] as const

type SummaryType = typeof SUMMARY_TYPES[number]['value']

interface DownloadSuccessProps {
  contentInfo: ContentInfo
  downloadUrl: string
  format: string
  mediaType: 'audio' | 'video'
  onReset: () => void
}

export function DownloadSuccess({
  contentInfo,
  downloadUrl,
  format,
  mediaType,
  onReset,
}: DownloadSuccessProps) {
  return (
    <div className="max-w-3xl stagger">
      {/* Title area */}
      <div className="mb-8 animate-fade-up">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 bg-green-500" />
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            Ready
          </span>
        </div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
          {contentInfo.title}
        </h1>
      </div>

      {/* Metadata row */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground mb-6 pb-6 border-b border-border animate-fade-up">
        {contentInfo.show_name && (
          <span>{contentInfo.show_name}</span>
        )}
        {contentInfo.creator_name && (
          <span>
            {contentInfo.creator_username ? `@${contentInfo.creator_username}` : contentInfo.creator_name}
          </span>
        )}
        {contentInfo.duration_seconds && (
          <span>{formatDuration(contentInfo.duration_seconds)}</span>
        )}
        <span className="uppercase font-mono text-xs">{format}</span>
        {contentInfo.file_size_mb && (
          <span className="font-mono text-xs">{contentInfo.file_size_mb.toFixed(1)} MB</span>
        )}
        <span className="inline-flex items-center gap-1">
          {mediaType === 'audio' ? <Mic className="w-3 h-3" /> : <Video className="w-3 h-3" />}
          {mediaType}
        </span>
      </div>

      {/* Actions */}
      <div className="flex gap-2 animate-fade-up">
        <button
          onClick={onReset}
          className="px-4 py-2.5 text-sm font-medium text-muted-foreground border border-border hover:text-foreground hover:border-foreground/30 transition-colors"
        >
          <ArrowLeft className="inline mr-1.5 h-3.5 w-3.5" />
          Back
        </button>
        <a
          href={downloadUrl}
          download
          className="inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
        >
          <Download className="mr-1.5 h-3.5 w-3.5" />
          Download file
        </a>
      </div>
    </div>
  )
}

interface TranscriptionSuccessProps {
  result: TranscriptionResult
  jobId?: string | null
  onReset: () => void
  onDownload: (renamedOutput?: string) => void
}

export function TranscriptionSuccess({
  result,
  jobId,
  onReset,
  onDownload,
}: TranscriptionSuccessProps) {
  const [copied, setCopied] = useState(false)
  const [showRenaming, setShowRenaming] = useState(false)
  const [speakerNames, setSpeakerNames] = useState<Record<string, string>>({})

  // Summarization state
  const [summaryType, setSummaryType] = useState<SummaryType>('bullet_points')
  const [summary, setSummary] = useState<string | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [summaryCopied, setSummaryCopied] = useState(false)

  // Translation state
  const [languages, setLanguages] = useState<{ code: string; name: string }[]>([])
  const [targetLang, setTargetLang] = useState<string>('')
  const [translation, setTranslation] = useState<string | null>(null)
  const [translationLoading, setTranslationLoading] = useState(false)
  const [translationError, setTranslationError] = useState<string | null>(null)
  const [translationCopied, setTranslationCopied] = useState(false)
  const [translateAvailable, setTranslateAvailable] = useState(false)
  const [translatorType, setTranslatorType] = useState<'translategemma' | 'ai_provider'>('translategemma')
  const [aiProviderInfo, setAiProviderInfo] = useState<{ available: boolean; provider?: string; model?: string }>({ available: false })
  const [translateGemmaAvailable, setTranslateGemmaAvailable] = useState(false)

  // Obsidian export state
  const [obsidianConfigured, setObsidianConfigured] = useState(false)
  const [obsidianExporting, setObsidianExporting] = useState(false)
  const [obsidianResult, setObsidianResult] = useState<{
    success: boolean
    file_path?: string
    note_name?: string
    error?: string
  } | null>(null)

  // Fetch supported languages and Obsidian settings on mount
  useEffect(() => {
    fetch('/api/translate/languages')
      .then(res => res.json())
      .then(data => {
        setLanguages(data.languages || [])
      })
      .catch(() => {})

    fetch('/api/translate/available')
      .then(res => res.json())
      .then(data => {
        const gemmaAvailable = data.translategemma?.available || false
        const aiAvailable = data.ai_provider?.available || false
        setTranslateGemmaAvailable(gemmaAvailable)
        setAiProviderInfo({
          available: aiAvailable,
          provider: data.ai_provider?.provider,
          model: data.ai_provider?.model,
        })
        setTranslateAvailable(gemmaAvailable || aiAvailable)
        // Default to AI provider if available, otherwise TranslateGemma
        if (aiAvailable) {
          setTranslatorType('ai_provider')
        } else if (gemmaAvailable) {
          setTranslatorType('translategemma')
        }
      })
      .catch(() => {})

    // Check Obsidian settings
    fetch('/api/obsidian/settings')
      .then(res => res.json())
      .then(data => {
        setObsidianConfigured(data.is_configured || false)
      })
      .catch(() => {})
  }, [])

  // Extract unique speakers from segments
  const uniqueSpeakers = useMemo(() => {
    if (!result.segments) return []
    const speakers = new Set<string>()
    result.segments.forEach(seg => {
      if (seg.speaker) speakers.add(seg.speaker)
    })
    return Array.from(speakers).sort()
  }, [result.segments])

  // Apply speaker renaming to formatted output
  const displayOutput = useMemo(() => {
    if (!result.diarized || Object.keys(speakerNames).length === 0) {
      return result.formatted_output
    }
    let output = result.formatted_output
    for (const [original, renamed] of Object.entries(speakerNames)) {
      if (renamed && renamed !== original) {
        const pattern = new RegExp(`\\b${original}:`, 'gi')
        output = output.replace(pattern, `${renamed}:`)
      }
    }
    return output
  }, [result.formatted_output, result.diarized, speakerNames])

  const handleCopy = async () => {
    await navigator.clipboard.writeText(displayOutput)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    onDownload(displayOutput !== result.formatted_output ? displayOutput : undefined)
  }

  const handleSpeakerRename = (speaker: string, newName: string) => {
    setSpeakerNames(prev => ({
      ...prev,
      [speaker]: newName
    }))
  }

  const handleSummarize = async () => {
    setSummaryLoading(true)
    setSummaryError(null)
    setSummary(null)

    try {
      const response = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: result.text,
          summary_type: summaryType,
        }),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || 'Summarization failed')
      }

      const data = await response.json()
      setSummary(data.content)
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'Summarization failed')
    } finally {
      setSummaryLoading(false)
    }
  }

  const handleCopySummary = async () => {
    if (!summary) return
    await navigator.clipboard.writeText(summary)
    setSummaryCopied(true)
    setTimeout(() => setSummaryCopied(false), 2000)
  }

  const handleTranslate = async () => {
    if (!targetLang) return

    setTranslationLoading(true)
    setTranslationError(null)
    setTranslation(null)

    try {
      const response = await fetch('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: result.text,
          source_lang: result.language || 'en',
          target_lang: targetLang,
          translator: translatorType,
        }),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || 'Translation failed')
      }

      const data = await response.json()
      setTranslation(data.translated_text)
    } catch (error) {
      setTranslationError(error instanceof Error ? error.message : 'Translation failed')
    } finally {
      setTranslationLoading(false)
    }
  }

  const handleCopyTranslation = async () => {
    if (!translation) return
    await navigator.clipboard.writeText(translation)
    setTranslationCopied(true)
    setTimeout(() => setTranslationCopied(false), 2000)
  }

  const handleExportToObsidian = async () => {
    if (!jobId) return

    setObsidianExporting(true)
    setObsidianResult(null)

    try {
      const response = await fetch('/api/obsidian/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Export failed')
      }

      setObsidianResult(data)
    } catch (error) {
      setObsidianResult({
        success: false,
        error: error instanceof Error ? error.message : 'Export failed',
      })
    } finally {
      setObsidianExporting(false)
    }
  }

  return (
    <div className="w-full max-w-3xl mx-auto stagger">
      {/* Header */}
      <div className="mb-6 animate-fade-up">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 bg-green-500" />
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            Transcription complete
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground mt-2">
          <span>{result.language} ({(result.language_probability * 100).toFixed(0)}%)</span>
          <span>{formatDuration(result.duration_seconds)}</span>
          {result.diarized && (
            <span>{uniqueSpeakers.length} speaker{uniqueSpeakers.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      </div>

      {/* Speaker Renaming Panel */}
      {result.diarized && uniqueSpeakers.length > 0 && (
        <div className="border border-border p-3 sm:p-4 mb-4 animate-fade-up">
          <button
            onClick={() => setShowRenaming(!showRenaming)}
            className="flex items-center gap-2 w-full text-left min-h-[44px]"
          >
            <Users className="h-4 w-4 text-primary shrink-0" />
            <span className="font-medium flex-1 text-sm">Rename Speakers</span>
            <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${showRenaming ? 'rotate-180' : ''}`} />
          </button>
          {showRenaming && (
            <div className="mt-3 space-y-3 border-t border-border pt-3">
              {uniqueSpeakers.map(speaker => (
                <div key={speaker} className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3">
                  <span className="text-sm text-muted-foreground sm:w-24 shrink-0 font-mono">{speaker}:</span>
                  <Input
                    type="text"
                    placeholder="e.g., Host, Guest"
                    value={speakerNames[speaker] || ''}
                    onChange={(e) => handleSpeakerRename(speaker, e.target.value)}
                    className="h-9 flex-1"
                  />
                </div>
              ))}
              <p className="text-xs text-muted-foreground">
                Names apply to the transcript and downloads.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Transcript */}
      <div className="border border-border p-3 sm:p-4 mb-4 animate-fade-up">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            <span className="font-medium text-sm">Transcript</span>
            <span className="text-[10px] text-muted-foreground uppercase font-mono">({result.output_format})</span>
          </div>
          <Button variant="ghost" size="sm" onClick={handleCopy} className="h-8 w-8 p-0">
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </Button>
        </div>
        <div className="bg-muted p-3 sm:p-4 max-h-60 sm:max-h-80 overflow-y-auto">
          <pre className="text-xs sm:text-sm whitespace-pre-wrap font-mono text-foreground">{displayOutput}</pre>
        </div>
      </div>

      {/* Summarization Section */}
      <div className="border border-border p-3 sm:p-4 mb-4 animate-fade-up">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="font-medium text-sm">AI Summary</span>
        </div>

        <div className="flex flex-wrap gap-1 mb-3">
          {SUMMARY_TYPES.map((type) => (
            <button
              key={type.value}
              onClick={() => setSummaryType(type.value)}
              disabled={summaryLoading}
              className={`px-2.5 py-1.5 text-xs font-medium border transition-colors ${
                summaryType === type.value
                  ? 'border-foreground bg-foreground text-background'
                  : 'border-border text-muted-foreground hover:text-foreground hover:border-foreground/30'
              } disabled:opacity-50`}
            >
              {type.label}
            </button>
          ))}
        </div>

        <Button
          onClick={handleSummarize}
          disabled={summaryLoading}
          className="w-full mb-3 h-9"
          variant={summary ? 'outline' : 'default'}
        >
          {summaryLoading ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Sparkles className="mr-2 h-3.5 w-3.5" />
              {summary ? 'Regenerate' : 'Generate Summary'}
            </>
          )}
        </Button>

        {summaryError && (
          <div className="text-destructive text-sm mb-3">{summaryError}</div>
        )}

        {summary && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {SUMMARY_TYPES.find(t => t.value === summaryType)?.label}
              </span>
              <Button variant="ghost" size="sm" onClick={handleCopySummary} className="h-8 w-8 p-0">
                {summaryCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            <div className="bg-muted p-3 sm:p-4 max-h-48 sm:max-h-60 overflow-y-auto">
              <div className="text-xs sm:text-sm whitespace-pre-wrap">{summary}</div>
            </div>
          </div>
        )}
      </div>

      {/* Translation Section */}
      <div className="border border-border p-3 sm:p-4 mb-4 animate-fade-up">
        <div className="flex items-center gap-2 mb-3">
          <Languages className="h-4 w-4 text-primary" />
          <span className="font-medium text-sm">Translate</span>
          {!translateAvailable && (
            <span className="text-xs text-muted-foreground">(No translator available)</span>
          )}
        </div>

        {translateAvailable && (translateGemmaAvailable || aiProviderInfo.available) && (
          <div className="flex flex-wrap gap-1 mb-3">
            {aiProviderInfo.available && (
              <button
                onClick={() => setTranslatorType('ai_provider')}
                disabled={translationLoading}
                className={`px-2.5 py-1.5 text-xs font-medium border transition-colors ${
                  translatorType === 'ai_provider'
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border text-muted-foreground hover:text-foreground'
                } ${translationLoading ? 'opacity-50' : ''}`}
              >
                AI ({aiProviderInfo.provider}/{aiProviderInfo.model?.split('/').pop()})
              </button>
            )}
            {translateGemmaAvailable && (
              <button
                onClick={() => setTranslatorType('translategemma')}
                disabled={translationLoading}
                className={`px-2.5 py-1.5 text-xs font-medium border transition-colors ${
                  translatorType === 'translategemma'
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border text-muted-foreground hover:text-foreground'
                } ${translationLoading ? 'opacity-50' : ''}`}
              >
                TranslateGemma (Local)
              </button>
            )}
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-2 mb-3">
          <div className="flex-1">
            <SearchableSelect
              value={targetLang}
              onValueChange={setTargetLang}
              options={languages.map(l => ({ value: l.code, label: l.name }))}
              placeholder="Select target language..."
              disabled={translationLoading || !translateAvailable}
            />
          </div>
          <Button
            onClick={handleTranslate}
            disabled={translationLoading || !targetLang || !translateAvailable}
            className="h-10 px-4"
            variant={translation ? 'outline' : 'default'}
          >
            {translationLoading ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Translating...
              </>
            ) : (
              <>
                <Languages className="mr-2 h-3.5 w-3.5" />
                {translation ? 'Re-translate' : 'Translate'}
              </>
            )}
          </Button>
        </div>

        {!translateAvailable && (
          <div className="bg-muted p-3 text-xs text-muted-foreground">
            To enable translation, either:
            <ul className="list-disc list-inside mt-1 space-y-1">
              <li>Configure an AI provider in Settings</li>
              <li>Or install TranslateGemma: <code className="bg-background px-1 py-0.5 font-mono">ollama pull translategemma</code></li>
            </ul>
          </div>
        )}

        {translationError && (
          <div className="text-destructive text-sm mb-3">{translationError}</div>
        )}

        {translation && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {languages.find(l => l.code === targetLang)?.name || targetLang}
              </span>
              <Button variant="ghost" size="sm" onClick={handleCopyTranslation} className="h-8 w-8 p-0">
                {translationCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            <div className="bg-muted p-3 sm:p-4 max-h-48 sm:max-h-60 overflow-y-auto">
              <div className="text-xs sm:text-sm whitespace-pre-wrap">{translation}</div>
            </div>
          </div>
        )}
      </div>

      {/* Obsidian Export Section */}
      {jobId && (
        <div className="border border-border p-3 sm:p-4 mb-4 animate-fade-up">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen className="h-4 w-4 text-primary" />
            <span className="font-medium text-sm">Export to Obsidian</span>
          </div>

          {obsidianConfigured ? (
            <>
              <Button
                onClick={handleExportToObsidian}
                disabled={obsidianExporting}
                className="w-full mb-3 h-9"
                variant={obsidianResult?.success ? 'outline' : 'default'}
              >
                {obsidianExporting ? (
                  <>
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    Exporting...
                  </>
                ) : (
                  <>
                    <BookOpen className="mr-2 h-3.5 w-3.5" />
                    {obsidianResult?.success ? 'Export Again' : 'Export to Obsidian'}
                  </>
                )}
              </Button>

              {obsidianResult && (
                <div className={`p-3 border ${
                  obsidianResult.success
                    ? 'border-green-500/30 bg-green-500/5'
                    : 'border-destructive/30 bg-destructive/5'
                }`}>
                  <div className="flex items-start gap-2">
                    {obsidianResult.success ? (
                      <Check className="h-3.5 w-3.5 text-green-600 dark:text-green-400 shrink-0 mt-0.5" />
                    ) : (
                      <ExternalLink className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-foreground text-sm">
                        {obsidianResult.success ? 'Exported successfully' : 'Export failed'}
                      </div>
                      {obsidianResult.note_name && (
                        <div className="text-xs text-muted-foreground mt-0.5 truncate font-mono">
                          {obsidianResult.note_name}
                        </div>
                      )}
                      {obsidianResult.error && (
                        <div className="text-xs text-destructive mt-0.5">{obsidianResult.error}</div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="bg-muted p-3 text-xs text-muted-foreground">
              <p className="mb-2">
                Export transcriptions as markdown notes to your Obsidian vault.
              </p>
              <Button variant="outline" size="sm" asChild className="mt-1">
                <a href="/settings?tab=obsidian">
                  <Settings className="mr-2 h-3 w-3" />
                  Configure in Settings
                </a>
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Sentiment Analysis Section */}
      {jobId && result.segments && result.segments.length > 0 && (
        <SentimentSection
          jobId={jobId}
          hasSegments={result.segments.length > 0}
        />
      )}

      {/* Structured Data Extraction Section */}
      {jobId && result.text && (
        <ExtractSection
          jobId={jobId}
          hasTranscript={!!result.text}
        />
      )}

      {/* Viral Clips Hint */}
      {jobId && result.segments && result.segments.length > 0 && (
        <div className="border border-dashed border-primary/30 p-3 mb-4 animate-fade-up">
          <p className="text-sm text-muted-foreground">
            <Scissors className="inline h-3.5 w-3.5 mr-1.5 text-primary" />
            Create viral clips from this transcription in the <strong className="text-foreground">Clips</strong> tab.
          </p>
        </div>
      )}

      {/* Bottom actions */}
      <div className="flex gap-2 animate-fade-up">
        <button
          onClick={onReset}
          className="px-4 py-2.5 text-sm font-medium text-muted-foreground border border-border hover:text-foreground hover:border-foreground/30 transition-colors"
        >
          <ArrowLeft className="inline mr-1.5 h-3.5 w-3.5" />
          Back
        </button>
        <button
          onClick={handleDownload}
          className="inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
        >
          <Download className="mr-1.5 h-3.5 w-3.5" />
          Download
        </button>
      </div>
    </div>
  )
}
