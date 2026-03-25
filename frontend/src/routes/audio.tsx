import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { Twitter, Podcast, Music, Youtube, Radio } from 'lucide-react'
import {
  DownloadStatus,
  Platform,
  ContentInfo,
  AUDIO_PLATFORMS,
  PLATFORM_FORMATS,
  PLATFORM_LABELS,
} from '@/components/downloader'
import { DownloadForm, DownloadSuccess } from '@/components/downloader'

export const Route = createFileRoute('/audio')({
  component: AudioPage,
})

const PLATFORM_ICONS: Record<string, typeof Twitter> = {
  x_spaces: Twitter,
  apple_podcasts: Podcast,
  spotify: Music,
  youtube: Youtube,
  xiaoyuzhou: Radio,
}

function AudioPage() {
  const [platform, setPlatform] = useState<Platform>('x_spaces')
  const [url, setUrl] = useState('')
  const [format, setFormat] = useState<string>('m4a')
  const [status, setStatus] = useState<DownloadStatus>('idle')
  const [message, setMessage] = useState('')
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  const [contentInfo, setContentInfo] = useState<ContentInfo | null>(null)

  const handlePlatformChange = (newPlatform: Platform) => {
    setPlatform(newPlatform)
    setUrl('')
    setFormat(PLATFORM_FORMATS[newPlatform][0].value)
    setStatus('idle')
    setMessage('')
  }

  const handleReset = () => {
    setStatus('idle')
    setMessage('')
    setDownloadUrl(null)
    setContentInfo(null)
    setUrl('')
  }

  const handleDownload = async () => {
    if (!url.trim()) {
      setStatus('error')
      setMessage('Please enter a valid URL')
      return
    }

    setStatus('loading')
    setMessage(`Downloading from ${PLATFORM_LABELS[platform]}...`)
    setDownloadUrl(null)
    setContentInfo(null)

    try {
      const response = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, format, platform }),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Download failed')
      }

      const data = await response.json()
      const jobId = data.job_id

      for (let i = 0; i < 600; i++) {
        await new Promise(r => setTimeout(r, 1000))
        const res = await fetch(`/api/download/${jobId}`)
        const job = await res.json()

        if (job.status === 'completed') {
          setStatus('success')
          setDownloadUrl(`/api/download/${jobId}/file`)
          const info = job.content_info || job.space_info
          setContentInfo({
            title: info?.title || 'Downloaded Media',
            creator_name: info?.creator_name,
            creator_username: info?.creator_username,
            duration_seconds: info?.duration_seconds,
            file_size_mb: job.file_size_mb,
            show_name: info?.show_name,
          })
          return
        } else if (job.status === 'failed') {
          throw new Error(job.error || 'Download failed')
        }

        if (i % 10 === 0) {
          setMessage(`Downloading... ${Math.min(Math.floor(i / 6), 95)}%`)
        }
      }
      throw new Error('Download timed out')
    } catch (error) {
      setStatus('error')
      setMessage(error instanceof Error ? error.message : 'Download failed')
    }
  }

  if (status === 'success' && contentInfo && downloadUrl) {
    return (
      <DownloadSuccess
        contentInfo={contentInfo}
        downloadUrl={downloadUrl}
        format={format}
        mediaType="audio"
        onReset={handleReset}
      />
    )
  }

  return (
    <div className="stagger">
      {/* Page title */}
      <div className="mb-6 sm:mb-8 animate-fade-up">
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
          Audio
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Grab audio from podcasts, spaces, and streams
        </p>
      </div>

      {/* Platform selector — compact inline pills */}
      <div className="flex flex-wrap gap-1.5 mb-6 animate-fade-up">
        {AUDIO_PLATFORMS.map((p) => {
          const Icon = PLATFORM_ICONS[p]
          const active = platform === p
          return (
            <button
              key={p}
              onClick={() => handlePlatformChange(p)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs sm:text-sm font-medium border transition-colors ${
                active
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background text-muted-foreground hover:text-foreground hover:border-foreground/30'
              }`}
            >
              {Icon && <Icon className="w-3.5 h-3.5" />}
              {PLATFORM_LABELS[p]}
            </button>
          )
        })}
      </div>

      {/* Download form */}
      <div className="animate-fade-up">
        <DownloadForm
          platform={platform}
          url={url}
          setUrl={setUrl}
          format={format}
          setFormat={setFormat}
          status={status}
          message={message}
          onDownload={handleDownload}
        />
      </div>
    </div>
  )
}
