import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { Loader2, AlertCircle, Mic, FileAudio, FileText, Upload, Link, Users, Sparkles, Globe, Zap, Info } from 'lucide-react'
import {
  DownloadStatus,
  TranscriptionEngineType,
  WhisperModel,
  TranscriptionFormat,
  EnhancementPreset,
  TRANSCRIPTION_ENGINES,
  WHISPER_MODELS,
  TRANSCRIPTION_FORMATS,
  ENHANCEMENT_PRESETS,
  TRANSCRIPTION_LANGUAGES,
} from './types'

interface TranscribeFormProps {
  url: string
  setUrl: (url: string) => void
  transcribeMode: 'url' | 'file'
  setTranscribeMode: (mode: 'url' | 'file') => void
  selectedFile: File | null
  setSelectedFile: (file: File | null) => void
  engine: TranscriptionEngineType
  setEngine: (engine: TranscriptionEngineType) => void
  whisperModel: WhisperModel
  setWhisperModel: (model: WhisperModel) => void
  transcriptionFormat: TranscriptionFormat
  setTranscriptionFormat: (format: TranscriptionFormat) => void
  language: string
  setLanguage: (language: string) => void
  enhance: boolean
  setEnhance: (enhance: boolean) => void
  enhancementPreset: EnhancementPreset
  setEnhancementPreset: (preset: EnhancementPreset) => void
  diarize: boolean
  setDiarize: (diarize: boolean) => void
  numSpeakers: number | null
  setNumSpeakers: (num: number | null) => void
  status: DownloadStatus
  message: string
  onTranscribe: () => void
  // Fetch transcript props
  transcriptAvailable?: boolean
  transcriptPlatform?: string | null
  transcriptLanguages?: { language_code: string; language: string; is_generated: boolean }[]
  fetchLoading?: boolean
  onFetchTranscript?: () => void
}

export function TranscribeForm({
  url,
  setUrl,
  transcribeMode,
  setTranscribeMode,
  selectedFile,
  setSelectedFile,
  engine,
  setEngine,
  whisperModel,
  setWhisperModel,
  transcriptionFormat,
  setTranscriptionFormat,
  language,
  setLanguage,
  enhance,
  setEnhance,
  enhancementPreset,
  setEnhancementPreset,
  diarize,
  setDiarize,
  numSpeakers,
  setNumSpeakers,
  status,
  message,
  onTranscribe,
  transcriptAvailable = false,
  transcriptPlatform = null,
  transcriptLanguages = [],
  fetchLoading = false,
  onFetchTranscript,
}: TranscribeFormProps) {
  const platformLabel = transcriptPlatform === 'youtube' ? 'YouTube' : transcriptPlatform === 'spotify' ? 'Spotify' : transcriptPlatform

  return (
    <div className="space-y-4">
      {/* Mode Toggle */}
      <div className="flex gap-2 p-1 bg-muted rounded-lg">
        <button
          type="button"
          onClick={() => setTranscribeMode('url')}
          className={`flex-1 flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 sm:py-2 rounded-md text-sm font-medium transition-all active:scale-95 ${
            transcribeMode === 'url'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          <Link className="h-4 w-4" />
          <span>From URL</span>
        </button>
        <button
          type="button"
          onClick={() => setTranscribeMode('file')}
          className={`flex-1 flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 sm:py-2 rounded-md text-sm font-medium transition-all active:scale-95 ${
            transcribeMode === 'file'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          <Upload className="h-4 w-4" />
          <span>Upload</span>
        </button>
      </div>

      {/* URL Input */}
      {transcribeMode === 'url' && (
        <div>
          <label htmlFor="transcribe-url" className="block text-sm font-medium text-foreground mb-2">
            Audio/Video URL
          </label>
          <Input
            id="transcribe-url"
            type="url"
            placeholder="https://youtube.com/watch?v=... or any supported URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && status !== 'loading') {
                onTranscribe()
              }
            }}
            disabled={status === 'loading'}
            className="h-12 text-base"
          />
          <p className="text-xs text-muted-foreground mt-1">
            Supports: YouTube, X Spaces, Apple Podcasts, Spotify, 小宇宙
          </p>
        </div>
      )}

      {/* Fetch Transcript Banner */}
      {transcribeMode === 'url' && transcriptAvailable && (
        <div className="flex items-start gap-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
          <Info className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
              Transcript available on {platformLabel}
            </p>
            <p className="text-xs text-emerald-600/80 dark:text-emerald-400/70 mt-0.5">
              Fetch it instantly without Whisper processing
            </p>
            {transcriptLanguages.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {transcriptLanguages.map((lang) => (
                  <span
                    key={lang.language_code}
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${
                      lang.is_generated
                        ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                        : 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 font-medium'
                    }`}
                  >
                    {lang.language}{lang.is_generated ? ' (auto)' : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* File Upload */}
      {transcribeMode === 'file' && (
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            Audio/Video File
          </label>
          <div
            className={`relative border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
              selectedFile
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/50'
            }`}
          >
            <input
              type="file"
              accept=".mp3,.m4a,.wav,.mp4,.webm,.ogg,.flac,.aac"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              disabled={status === 'loading'}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
            {selectedFile ? (
              <div className="flex flex-col sm:flex-row items-center justify-center gap-2 text-muted-foreground">
                <FileAudio className="h-6 w-6 text-primary flex-shrink-0" />
                <span className="font-medium text-center break-all line-clamp-2 sm:line-clamp-1">{selectedFile.name}</span>
                <span className="text-sm text-muted-foreground whitespace-nowrap">
                  ({(selectedFile.size / 1024 / 1024).toFixed(1)} MB)
                </span>
              </div>
            ) : (
              <div>
                <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Drop a file here or click to browse
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  MP3, M4A, WAV, MP4, WebM, OGG, FLAC
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Engine Selector */}
      <div>
        <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
          <Zap className="inline h-3 w-3 mr-1" />
          Engine
        </label>
        <div className="flex flex-wrap gap-1">
          {TRANSCRIPTION_ENGINES.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setEngine(opt.value)}
              disabled={status === 'loading'}
              className={`px-3 py-1.5 text-xs sm:text-sm font-medium border transition-colors ${
                engine === opt.value
                  ? 'border-foreground bg-foreground text-background'
                  : 'border-border bg-background text-muted-foreground hover:text-foreground hover:border-foreground/30'
              } ${status === 'loading' ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {opt.label}
              <span className="hidden sm:inline text-[10px] ml-1 opacity-70">({opt.desc})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Model & Language Row */}
      <div className="grid gap-4 sm:grid-cols-2">
        {/* Model Selector (only for whisper engine) */}
        {(engine === 'whisper' || engine === 'auto') && (
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            <Mic className="inline h-4 w-4 mr-1" />
            Whisper Model
          </label>
          <div className="grid gap-2 grid-cols-2 sm:grid-cols-3">
            {WHISPER_MODELS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setWhisperModel(opt.value)}
                disabled={status === 'loading'}
                className={`p-2.5 sm:p-2 rounded-lg border-2 transition-all active:scale-95 ${
                  whisperModel === opt.value
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-background text-foreground hover:border-primary/50'
                } ${status === 'loading' ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="font-semibold text-sm">{opt.label}</div>
                <div className="text-xs text-muted-foreground hidden sm:block">{opt.desc}</div>
              </button>
            ))}
          </div>
        </div>
        )}

        {/* Language Selector */}
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            <Globe className="inline h-4 w-4 mr-1" />
            Audio Language
          </label>
          <SearchableSelect
            value={language}
            onValueChange={setLanguage}
            options={TRANSCRIPTION_LANGUAGES}
            placeholder="Auto-detect"
            disabled={status === 'loading'}
          />
          <p className="text-xs text-muted-foreground mt-1">
            Specify language for better accuracy (especially for Japanese, Chinese, Korean)
          </p>
        </div>
      </div>

      {/* Output Format Selector */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          <FileText className="inline h-4 w-4 mr-1" />
          Output Format
        </label>
        <div className="grid gap-2 grid-cols-3 sm:grid-cols-5">
          {TRANSCRIPTION_FORMATS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setTranscriptionFormat(opt.value)
                if (opt.value === 'dialogue') {
                  setDiarize(true)
                }
              }}
              disabled={status === 'loading'}
              className={`p-2.5 sm:p-3 rounded-lg border-2 transition-all active:scale-95 ${
                transcriptionFormat === opt.value
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-background text-foreground hover:border-primary/50'
              } ${status === 'loading' ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              <div className="font-semibold text-sm">{opt.label}</div>
              <div className="text-xs text-muted-foreground hidden sm:block">{opt.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Audio Enhancement */}
      <div className="space-y-3 p-3 sm:p-0 bg-muted/50 sm:bg-transparent rounded-lg">
        <label className="flex items-center gap-3 cursor-pointer min-h-[44px]">
          <input
            type="checkbox"
            checked={enhance}
            onChange={(e) => setEnhance(e.target.checked)}
            disabled={status === 'loading'}
            className="w-5 h-5 sm:w-4 sm:h-4 rounded border-border text-primary focus:ring-primary"
          />
          <span className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Sparkles className="h-4 w-4" />
            Enhance Audio Quality
          </span>
        </label>
        {enhance && (
          <div className="sm:ml-7 grid gap-2 grid-cols-3">
            {ENHANCEMENT_PRESETS.filter(p => p.value !== 'none').map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setEnhancementPreset(opt.value)}
                disabled={status === 'loading'}
                className={`p-2 rounded-lg border-2 transition-all active:scale-95 ${
                  enhancementPreset === opt.value
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-background text-foreground hover:border-primary/50'
                } ${status === 'loading' ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="font-semibold text-xs">{opt.label}</div>
                <div className="text-xs text-muted-foreground hidden sm:block">{opt.desc}</div>
              </button>
            ))}
          </div>
        )}
        {enhance && (
          <p className="sm:ml-7 text-xs text-muted-foreground">
            Reduces background noise and isolates voice for clearer transcription.
          </p>
        )}
      </div>

      {/* Speaker Diarization */}
      <div className="space-y-3 p-3 sm:p-0 bg-muted/50 sm:bg-transparent rounded-lg">
        <label className="flex items-center gap-3 cursor-pointer min-h-[44px]">
          <input
            type="checkbox"
            checked={diarize}
            onChange={(e) => setDiarize(e.target.checked)}
            disabled={status === 'loading'}
            className="w-5 h-5 sm:w-4 sm:h-4 rounded border-border text-primary focus:ring-primary"
          />
          <span className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Users className="h-4 w-4" />
            Enable Speaker Diarization
          </span>
        </label>
        {diarize && (
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 sm:ml-7">
            <label htmlFor="num-speakers" className="text-sm text-muted-foreground">
              Number of speakers (optional):
            </label>
            <Input
              id="num-speakers"
              type="number"
              min={1}
              max={20}
              placeholder="Auto-detect"
              value={numSpeakers ?? ''}
              onChange={(e) => setNumSpeakers(e.target.value ? parseInt(e.target.value) : null)}
              disabled={status === 'loading'}
              className="w-full sm:w-24 h-10 sm:h-8"
            />
          </div>
        )}
        {diarize && (
          <p className="sm:ml-7 text-xs text-muted-foreground">
            Identifies different speakers in the audio. Requires HuggingFace token.
          </p>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        {/* Fetch Transcript Button */}
        {transcribeMode === 'url' && transcriptAvailable && onFetchTranscript && (
          <Button
            onClick={onFetchTranscript}
            disabled={status === 'loading' || !url.trim()}
            className="flex-1 h-12 text-base bg-emerald-600 hover:bg-emerald-700 text-white"
            size="lg"
          >
            {fetchLoading ? (
              <>
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Fetching...
              </>
            ) : (
              <>
                <Zap className="mr-2 h-5 w-5" />
                Fetch Transcript
              </>
            )}
          </Button>
        )}

        {/* Transcribe Button */}
        <Button
          onClick={onTranscribe}
          disabled={status === 'loading' || (transcribeMode === 'url' ? !url.trim() : !selectedFile)}
          className={`h-12 text-base ${transcriptAvailable && transcribeMode === 'url' ? 'flex-1' : 'w-full'}`}
          size="lg"
          variant={transcriptAvailable && transcribeMode === 'url' ? 'outline' : 'default'}
        >
          {status === 'loading' && !fetchLoading ? (
            <>
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Transcribing...
            </>
          ) : (
            <>
              <FileText className="mr-2 h-5 w-5" />
              Transcribe{transcriptAvailable && transcribeMode === 'url' ? ' with Whisper' : ''}
            </>
          )}
        </Button>
      </div>

      {/* Status Message */}
      {message && status !== 'success' && (
        <div
          className={`flex items-center gap-2 p-3 rounded-lg text-sm ${
            status === 'error'
              ? 'bg-destructive/10 text-destructive'
              : 'bg-primary/10 text-primary'
          }`}
        >
          {status === 'error' && <AlertCircle className="h-4 w-4 flex-shrink-0" />}
          {status === 'loading' && <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />}
          <span>{message}</span>
        </div>
      )}
    </div>
  )
}
