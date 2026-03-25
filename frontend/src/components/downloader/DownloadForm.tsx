import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Download, Loader2, AlertCircle, HelpCircle, ChevronDown } from 'lucide-react'
import {
  Platform,
  DownloadStatus,
  PLATFORM_FORMATS,
  PLATFORM_PLACEHOLDERS,
  PLATFORM_LABELS,
  PLATFORM_GUIDES,
  QUALITY_OPTIONS,
} from './types'

interface DownloadFormProps {
  platform: Platform
  url: string
  setUrl: (url: string) => void
  format: string
  setFormat: (format: string) => void
  quality?: string
  setQuality?: (quality: string) => void
  status: DownloadStatus
  message: string
  onDownload: () => void
  isVideo?: boolean
}

export function DownloadForm({
  platform,
  url,
  setUrl,
  format,
  setFormat,
  quality,
  setQuality,
  status,
  message,
  onDownload,
  isVideo,
}: DownloadFormProps) {
  const [showGuide, setShowGuide] = useState(false)
  const guide = PLATFORM_GUIDES[platform]

  return (
    <div className="space-y-5">
      {/* ─── URL Input: the hero ─── */}
      <div>
        <div className="relative">
          <input
            id="url-input"
            type="url"
            placeholder={PLATFORM_PLACEHOLDERS[platform]}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && status !== 'loading') {
                onDownload()
              }
            }}
            disabled={status === 'loading'}
            className="w-full h-14 sm:h-16 px-4 bg-card border border-border text-foreground font-mono text-sm sm:text-base placeholder:text-muted-foreground/60 placeholder:font-sans focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary disabled:opacity-50 transition-colors"
          />
          {/* Keyboard hint */}
          {url.trim() && status !== 'loading' && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5 text-muted-foreground">
              <kbd className="px-1.5 py-0.5 text-[10px] font-mono bg-muted border border-border">
                Enter
              </kbd>
            </div>
          )}
        </div>

        {/* ─── How to get URL ─── */}
        <button
          type="button"
          onClick={() => setShowGuide(!showGuide)}
          className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <HelpCircle className="w-3 h-3" />
          <span>How to get {PLATFORM_LABELS[platform]} URL</span>
          <ChevronDown className={`w-3 h-3 transition-transform ${showGuide ? 'rotate-180' : ''}`} />
        </button>

        {showGuide && (
          <div className="mt-2 py-3 px-3.5 border border-dashed border-border bg-muted/50 animate-fade-up">
            <ol className="space-y-1.5">
              {guide.steps.map((step, i) => (
                <li key={i} className="flex gap-2.5 text-xs text-muted-foreground">
                  <span className="font-mono text-foreground/50 shrink-0 w-4 text-right">{i + 1}.</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
            {guide.tip && (
              <p className="mt-2.5 pt-2.5 border-t border-border text-[11px] text-muted-foreground/80">
                {guide.tip}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ─── Controls row: format + quality + download ─── */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3 sm:gap-4">
        {/* Format */}
        <div className="flex-1">
          <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
            Format
          </label>
          <div className="flex gap-1">
            {PLATFORM_FORMATS[platform].map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFormat(opt.value)}
                disabled={status === 'loading'}
                className={`px-3 py-2 text-xs sm:text-sm font-medium border transition-colors ${
                  format === opt.value
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border bg-background text-muted-foreground hover:text-foreground hover:border-foreground/30'
                } disabled:opacity-50`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Quality (video only) */}
        {isVideo && setQuality && (
          <div className="flex-1">
            <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
              Quality
            </label>
            <div className="flex gap-1">
              {QUALITY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setQuality(opt.value)}
                  disabled={status === 'loading'}
                  className={`px-3 py-2 text-xs sm:text-sm font-medium border transition-colors ${
                    quality === opt.value
                      ? 'border-foreground bg-foreground text-background'
                      : 'border-border bg-background text-muted-foreground hover:text-foreground hover:border-foreground/30'
                  } disabled:opacity-50`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Download button */}
        <Button
          onClick={onDownload}
          disabled={status === 'loading' || !url.trim()}
          className="h-10 px-6 text-sm font-semibold shrink-0"
        >
          {status === 'loading' ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Downloading...
            </>
          ) : (
            <>
              <Download className="mr-2 h-4 w-4" />
              Download
            </>
          )}
        </Button>
      </div>

      {/* ─── Status ─── */}
      {message && status !== 'success' && (
        <div className={`flex items-center gap-2 text-sm ${
          status === 'error' ? 'text-destructive' : 'text-muted-foreground'
        }`}>
          {status === 'error' && <AlertCircle className="h-3.5 w-3.5 shrink-0" />}
          {status === 'loading' && <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />}
          <span>{message}</span>
        </div>
      )}
    </div>
  )
}
