import { createFileRoute } from '@tanstack/react-router'
import { useState, useEffect, useRef } from 'react'
import {
  DownloadStatus,
  TranscriptionEngineType,
  WhisperModel,
  TranscriptionFormat,
  EnhancementPreset,
  TranscriptionResult,
} from '@/components/downloader'
import { TranscribeForm, TranscriptionSuccess } from '@/components/downloader'

export const Route = createFileRoute('/transcribe')({
  component: TranscribePage,
})

function TranscribePage() {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<DownloadStatus>('idle')
  const [message, setMessage] = useState('')
  const [engine, setEngine] = useState<TranscriptionEngineType>('auto')
  const [whisperModel, setWhisperModel] = useState<WhisperModel>('base')
  const [transcriptionFormat, setTranscriptionFormat] = useState<TranscriptionFormat>('text')
  const [transcriptionResult, setTranscriptionResult] = useState<TranscriptionResult | null>(null)
  const [transcriptionJobId, setTranscriptionJobId] = useState<string | null>(null)
  const [transcribeMode, setTranscribeMode] = useState<'url' | 'file'>('url')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [language, setLanguage] = useState<string>('')
  const [diarize, setDiarize] = useState(false)
  const [numSpeakers, setNumSpeakers] = useState<number | null>(null)
  const [enhance, setEnhance] = useState(false)
  const [enhancementPreset, setEnhancementPreset] = useState<EnhancementPreset>('medium')

  // Fetch transcript state
  const [transcriptAvailable, setTranscriptAvailable] = useState(false)
  const [transcriptPlatform, setTranscriptPlatform] = useState<string | null>(null)
  const [transcriptLanguages, setTranscriptLanguages] = useState<{ language_code: string; language: string; is_generated: boolean }[]>([])
  const [fetchLoading, setFetchLoading] = useState(false)

  // Debounced check for transcript availability
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (transcribeMode !== 'url' || !url.trim()) {
      setTranscriptAvailable(false)
      setTranscriptPlatform(null)
      setTranscriptLanguages([])
      return
    }

    if (debounceRef.current) clearTimeout(debounceRef.current)

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/transcript/check?url=${encodeURIComponent(url.trim())}`)
        if (res.ok) {
          const data = await res.json()
          setTranscriptAvailable(data.available)
          setTranscriptPlatform(data.platform)
          setTranscriptLanguages(data.languages || [])
        } else {
          setTranscriptAvailable(false)
          setTranscriptPlatform(null)
          setTranscriptLanguages([])
        }
      } catch {
        setTranscriptAvailable(false)
        setTranscriptPlatform(null)
        setTranscriptLanguages([])
      }
    }, 500)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [url, transcribeMode])

  const handleReset = () => {
    setStatus('idle')
    setMessage('')
    setTranscriptionResult(null)
    setTranscriptionJobId(null)
    setUrl('')
    setSelectedFile(null)
    setEngine('auto')
    setLanguage('')
    setDiarize(false)
    setNumSpeakers(null)
    setEnhance(false)
    setEnhancementPreset('medium')
    setTranscriptAvailable(false)
    setTranscriptPlatform(null)
    setTranscriptLanguages([])
    setFetchLoading(false)
  }

  const handleFetchTranscript = async () => {
    if (!url.trim()) return

    setFetchLoading(true)
    setStatus('loading')
    setMessage('Fetching transcript...')
    setTranscriptionResult(null)

    try {
      const response = await fetch('/api/transcript/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          language: language || undefined,
          output_format: transcriptionFormat,
        }),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to fetch transcript')
      }

      const job = await response.json()

      setStatus('success')
      setTranscriptionJobId(job.job_id)
      setTranscriptionResult({
        text: job.text,
        language: job.language,
        language_probability: 1.0,
        duration_seconds: job.duration_seconds,
        formatted_output: job.formatted_output,
        output_format: job.output_format,
        segments: job.segments,
        diarized: false,
      })
    } catch (error) {
      setStatus('error')
      setMessage(error instanceof Error ? error.message : 'Failed to fetch transcript')
    } finally {
      setFetchLoading(false)
    }
  }

  const handleTranscribe = async () => {
    if (transcribeMode === 'url' && !url.trim()) {
      setStatus('error')
      setMessage('Please enter a valid URL')
      return
    }
    if (transcribeMode === 'file' && !selectedFile) {
      setStatus('error')
      setMessage('Please select a file')
      return
    }

    setStatus('loading')
    setMessage(transcribeMode === 'file' ? 'Uploading and transcribing...' : 'Transcribing...')
    setTranscriptionResult(null)

    try {
      let response: Response

      if (transcribeMode === 'file' && selectedFile) {
        const formData = new FormData()
        formData.append('file', selectedFile)
        formData.append('engine', engine)
        formData.append('model', whisperModel)
        formData.append('output_format', transcriptionFormat)
        if (language) {
          formData.append('language', language)
        }
        if (diarize) {
          formData.append('diarize', 'true')
          if (numSpeakers) {
            formData.append('num_speakers', numSpeakers.toString())
          }
        }
        if (enhance) {
          formData.append('enhance', 'true')
          formData.append('enhancement_preset', enhancementPreset)
        }
        response = await fetch('/api/transcribe/upload', { method: 'POST', body: formData })
      } else {
        response = await fetch('/api/transcribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url,
            engine,
            model: whisperModel,
            output_format: transcriptionFormat,
            language: language || undefined,
            diarize,
            num_speakers: numSpeakers,
            enhance,
            enhancement_preset: enhancementPreset,
          }),
        })
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Transcription failed')
      }

      const data = await response.json()
      const jobId = data.job_id

      for (let i = 0; i < 1800; i++) {
        await new Promise(r => setTimeout(r, 1000))
        const res = await fetch(`/api/transcribe/${jobId}`)
        const job = await res.json()

        if (job.status === 'completed') {
          setStatus('success')
          setTranscriptionJobId(jobId)
          setTranscriptionResult({
            text: job.text,
            language: job.language,
            language_probability: job.language_probability,
            duration_seconds: job.duration_seconds,
            formatted_output: job.formatted_output,
            output_format: job.output_format,
            segments: job.segments,
            diarized: job.segments?.some((s: { speaker?: string }) => s.speaker),
          })
          return
        } else if (job.status === 'failed') {
          throw new Error(job.error || 'Transcription failed')
        }

        if (i % 10 === 0) {
          setMessage(`Transcribing... ${Math.min(Math.floor(i / 18), 95)}%`)
        }
      }
      throw new Error('Transcription timed out')
    } catch (error) {
      setStatus('error')
      setMessage(error instanceof Error ? error.message : 'Transcription failed')
    }
  }

  const handleDownloadTranscription = (renamedOutput?: string) => {
    if (!transcriptionResult) return
    const ext = transcriptionFormat === 'json' ? 'json' : transcriptionFormat === 'text' || transcriptionFormat === 'dialogue' ? 'txt' : transcriptionFormat
    const content = renamedOutput || transcriptionResult.formatted_output
    const blob = new Blob([content], { type: 'text/plain' })
    const downloadUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `transcription.${ext}`
    a.click()
    URL.revokeObjectURL(downloadUrl)
  }

  if (status === 'success' && transcriptionResult) {
    return (
      <TranscriptionSuccess
        result={transcriptionResult}
        jobId={transcriptionJobId}
        onReset={handleReset}
        onDownload={handleDownloadTranscription}
      />
    )
  }

  return (
    <div className="bg-card rounded-xl shadow-lg p-4 sm:p-6 md:p-8">
      <TranscribeForm
        url={url}
        setUrl={setUrl}
        transcribeMode={transcribeMode}
        setTranscribeMode={setTranscribeMode}
        selectedFile={selectedFile}
        setSelectedFile={setSelectedFile}
        engine={engine}
        setEngine={setEngine}
        whisperModel={whisperModel}
        setWhisperModel={setWhisperModel}
        transcriptionFormat={transcriptionFormat}
        setTranscriptionFormat={setTranscriptionFormat}
        language={language}
        setLanguage={setLanguage}
        enhance={enhance}
        setEnhance={setEnhance}
        enhancementPreset={enhancementPreset}
        setEnhancementPreset={setEnhancementPreset}
        diarize={diarize}
        setDiarize={setDiarize}
        numSpeakers={numSpeakers}
        setNumSpeakers={setNumSpeakers}
        status={status}
        message={message}
        onTranscribe={handleTranscribe}
        transcriptAvailable={transcriptAvailable}
        transcriptPlatform={transcriptPlatform}
        transcriptLanguages={transcriptLanguages}
        fetchLoading={fetchLoading}
        onFetchTranscript={handleFetchTranscript}
      />
    </div>
  )
}
