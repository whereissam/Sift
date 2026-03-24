import { useState, useCallback, useEffect } from 'react'
import { Mic, Square, RotateCcw, Copy, AlertCircle, Check, Sparkles, Info } from 'lucide-react'
import { useAudioCapture, isAudioCaptureSupported } from '@/hooks/useAudioCapture'
import { useRealtimeTranscription } from '@/hooks/useRealtimeTranscription'
import { TranscriptDisplay, FullTranscriptView } from './TranscriptDisplay'
import { WHISPER_MODELS, TRANSCRIPTION_LANGUAGES, WhisperModel } from '@/components/downloader'

export function LiveTranscriber() {
  const [model, setModel] = useState<WhisperModel>('base')
  const [language, setLanguage] = useState('')
  const [llmPolish, setLlmPolish] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showRaw, setShowRaw] = useState(false)

  const audioCapture = useAudioCapture({ chunkInterval: 250 })
  const transcription = useRealtimeTranscription()

  const isSupported = isAudioCaptureSupported()
  const isActive = audioCapture.isCapturing && transcription.isConnected
  const isCompleted = transcription.status === 'completed'

  // Handle audio chunks - send to WebSocket
  const handleAudioChunk = useCallback((blob: Blob) => {
    transcription.sendAudio(blob)
  }, [transcription.sendAudio])

  // Start live transcription
  const handleStart = useCallback(async () => {
    // First connect to WebSocket
    transcription.connect({
      model,
      language: language || undefined,
      llmPolish: llmPolish && transcription.llmPolishAvailable,
    })
  }, [model, language, llmPolish, transcription])

  // Start audio capture once connected
  useEffect(() => {
    if (transcription.status === 'connected' && !audioCapture.isCapturing) {
      audioCapture.startCapture(handleAudioChunk)
    }
  }, [transcription.status, audioCapture.isCapturing, audioCapture.startCapture, handleAudioChunk])

  // Stop live transcription
  const handleStop = useCallback(() => {
    audioCapture.stopCapture()
    transcription.stop()
  }, [audioCapture, transcription])

  // Reset everything
  const handleReset = useCallback(() => {
    audioCapture.stopCapture()
    transcription.disconnect()
    setCopied(false)
    setShowRaw(false)
  }, [audioCapture, transcription])

  // Copy transcript to clipboard
  const handleCopy = useCallback(async () => {
    const textToCopy = showRaw && transcription.rawText
      ? transcription.rawText
      : transcription.fullText
    try {
      await navigator.clipboard.writeText(textToCopy)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      console.error('Failed to copy:', error)
    }
  }, [transcription.fullText, transcription.rawText, showRaw])

  // Download transcript
  const handleDownload = useCallback(() => {
    const textToDownload = showRaw && transcription.rawText
      ? transcription.rawText
      : transcription.fullText
    const suffix = showRaw ? '-raw' : (transcription.llmPolished ? '-polished' : '')
    const blob = new Blob([textToDownload], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `transcript${suffix}-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }, [transcription.fullText, transcription.rawText, transcription.llmPolished, showRaw])

  // Show unsupported browser message
  if (!isSupported) {
    return (
      <div className="bg-card rounded-xl shadow-lg p-6">
        <div className="flex flex-col items-center gap-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive" />
          <h2 className="text-xl font-semibold">Browser Not Supported</h2>
          <p className="text-muted-foreground">
            Live transcription requires microphone access and the MediaRecorder API.
            Please use a modern browser like Chrome, Firefox, or Edge.
          </p>
        </div>
      </div>
    )
  }

  // Show completed view
  if (isCompleted) {
    return (
      <div className="bg-card rounded-xl shadow-lg p-6">
        <FullTranscriptView
          fullText={showRaw && transcription.rawText ? transcription.rawText : transcription.fullText}
          segments={transcription.segments}
          language={transcription.language}
          duration={transcription.duration}
          onCopy={handleCopy}
          onDownload={handleDownload}
          llmPolished={transcription.llmPolished}
          tokensUsed={transcription.tokensUsed}
          rawText={transcription.rawText}
          showRaw={showRaw}
          onToggleRaw={() => setShowRaw(!showRaw)}
        />
        <div className="mt-4 flex justify-center">
          <button
            onClick={handleReset}
            className="flex items-center gap-2 px-4 py-2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <RotateCcw className="h-4 w-4" />
            Start New Session
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-card rounded-xl shadow-lg p-6 space-y-6">
      {/* Configuration */}
      {!isActive && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">
                Model
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value as WhisperModel)}
                className="w-full px-3 py-2 bg-background border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {WHISPER_MODELS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label} - {m.desc}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">
                Language
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full px-3 py-2 bg-background border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {TRANSCRIPTION_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* LLM Polish option */}
          <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
            <div className="flex items-center gap-3">
              <Sparkles className={`h-5 w-5 ${transcription.llmPolishAvailable ? 'text-primary' : 'text-muted-foreground'}`} />
              <div>
                <div className="text-sm font-medium">AI Polish</div>
                <div className="text-xs text-muted-foreground">
                  Use LLM to clean up and polish the final transcript
                </div>
              </div>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={llmPolish}
                onChange={(e) => setLlmPolish(e.target.checked)}
                disabled={!transcription.llmPolishAvailable}
                className="sr-only peer"
              />
              <div className={`w-11 h-6 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all ${
                transcription.llmPolishAvailable
                  ? 'bg-muted peer-checked:bg-primary'
                  : 'bg-muted cursor-not-allowed opacity-50'
              }`} />
            </label>
          </div>

          {!transcription.llmPolishAvailable && (
            <div className="flex items-start gap-2 p-3 bg-muted/30 rounded-lg text-xs text-muted-foreground">
              <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>
                AI polish requires an LLM provider to be configured in Settings.
                The transcript will still work without it.
              </span>
            </div>
          )}
        </div>
      )}

      {/* Error message */}
      {(audioCapture.error || transcription.error) && (
        <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <p className="text-sm">{audioCapture.error || transcription.error}</p>
        </div>
      )}

      {/* Audio level indicator */}
      {isActive && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Audio Level</span>
            <span className="text-muted-foreground">
              {transcription.status === 'transcribing' ? 'Transcribing...' : 'Listening...'}
            </span>
          </div>
          <div className="h-2 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-75"
              style={{ width: `${audioCapture.audioLevel * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Transcript display */}
      <TranscriptDisplay
        segments={transcription.segments}
        partialText={transcription.partialText}
      />

      {/* Controls */}
      <div className="flex items-center justify-center gap-4">
        {!isActive ? (
          <button
            onClick={handleStart}
            disabled={transcription.status === 'connecting'}
            className="flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-full hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Mic className="h-5 w-5" />
            {transcription.status === 'connecting' ? 'Connecting...' : 'Start Transcription'}
          </button>
        ) : (
          <button
            onClick={handleStop}
            className="flex items-center gap-2 px-6 py-3 bg-destructive text-destructive-foreground rounded-full hover:bg-destructive/90 transition-colors"
          >
            <Square className="h-5 w-5" />
            Stop
          </button>
        )}

        {/* Copy button (when there's content) */}
        {transcription.fullText && !isActive && (
          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-4 py-3 bg-secondary text-secondary-foreground rounded-full hover:bg-secondary/80 transition-colors"
          >
            {copied ? (
              <>
                <Check className="h-5 w-5" />
                Copied!
              </>
            ) : (
              <>
                <Copy className="h-5 w-5" />
                Copy
              </>
            )}
          </button>
        )}

        {/* Reset button */}
        {(transcription.segments.length > 0 || transcription.partialText) && !isActive && (
          <button
            onClick={handleReset}
            className="flex items-center gap-2 px-4 py-3 text-muted-foreground hover:text-foreground transition-colors"
          >
            <RotateCcw className="h-5 w-5" />
            Reset
          </button>
        )}
      </div>

      {/* Status indicators */}
      <div className="flex items-center justify-center gap-6 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-500 animate-pulse' : 'bg-muted'}`} />
          <span>Microphone</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${
            transcription.isConnected ? 'bg-green-500' :
            transcription.status === 'connecting' ? 'bg-yellow-500 animate-pulse' :
            'bg-muted'
          }`} />
          <span>Server</span>
        </div>
        {transcription.llmPolishEnabled && (
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-3 w-3 text-primary" />
            <span>AI Polish</span>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <span>Segments: {transcription.segments.length}</span>
        </div>
      </div>
    </div>
  )
}
