export type DownloadStatus = 'idle' | 'loading' | 'success' | 'error'
export type Platform = 'x_spaces' | 'apple_podcasts' | 'spotify' | 'youtube' | 'xiaoyuzhou' | 'x_video' | 'youtube_video' | 'instagram' | 'xiaohongshu'
export type MediaType = 'audio' | 'video' | 'transcribe' | 'clips'
export type WhisperModel = 'tiny' | 'base' | 'small' | 'medium' | 'large-v3' | 'turbo'
export type TranscriptionFormat = 'text' | 'srt' | 'vtt' | 'json' | 'dialogue'
export type EnhancementPreset = 'none' | 'light' | 'medium' | 'heavy'

export interface ContentInfo {
  title: string
  creator_name?: string
  creator_username?: string
  duration_seconds?: number
  file_size_mb?: number
  show_name?: string
  platform?: Platform
}

export interface TranscriptionSegment {
  start: number
  end: number
  text: string
  speaker?: string
}

export interface TranscriptionResult {
  text: string
  language: string
  language_probability: number
  duration_seconds: number
  formatted_output: string
  output_format: TranscriptionFormat
  segments?: TranscriptionSegment[]
  diarized?: boolean
}

export const AUDIO_PLATFORMS: Platform[] = ['x_spaces', 'apple_podcasts', 'spotify', 'youtube', 'xiaoyuzhou']
export const VIDEO_PLATFORMS: Platform[] = ['x_video', 'youtube_video', 'instagram', 'xiaohongshu']

export const PLATFORM_FORMATS: Record<Platform, { value: string; label: string; desc: string }[]> = {
  x_spaces: [
    { value: 'm4a', label: 'M4A', desc: 'Original quality' },
    { value: 'mp3', label: 'MP3', desc: 'Most compatible' },
  ],
  apple_podcasts: [
    { value: 'm4a', label: 'M4A', desc: 'Original quality' },
    { value: 'mp3', label: 'MP3', desc: 'Most compatible' },
  ],
  spotify: [
    { value: 'mp3', label: 'MP3', desc: 'Most compatible' },
    { value: 'm4a', label: 'M4A', desc: 'AAC format' },
  ],
  youtube: [
    { value: 'm4a', label: 'M4A', desc: 'Best quality' },
    { value: 'mp3', label: 'MP3', desc: 'Most compatible' },
  ],
  xiaoyuzhou: [
    { value: 'm4a', label: 'M4A', desc: 'Original quality' },
    { value: 'mp3', label: 'MP3', desc: 'Most compatible' },
  ],
  x_video: [
    { value: 'mp4', label: 'MP4', desc: 'Best quality' },
  ],
  youtube_video: [
    { value: 'mp4', label: 'MP4', desc: 'Best quality' },
  ],
  instagram: [
    { value: 'mp4', label: 'MP4', desc: 'Best quality' },
  ],
  xiaohongshu: [
    { value: 'mp4', label: 'MP4', desc: 'Best quality' },
  ],
}

export const PLATFORM_PLACEHOLDERS: Record<Platform, string> = {
  x_spaces: 'https://x.com/i/spaces/1vOxwdyYrlqKB',
  apple_podcasts: 'https://podcasts.apple.com/us/podcast/show-name/id123456789',
  spotify: 'https://open.spotify.com/episode/abc123',
  youtube: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  xiaoyuzhou: 'https://www.xiaoyuzhoufm.com/episode/abc123',
  x_video: 'https://x.com/user/status/123456789',
  youtube_video: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  instagram: 'https://www.instagram.com/reel/ABC123xyz',
  xiaohongshu: 'https://www.xiaohongshu.com/explore/abc123',
}

export const PLATFORM_LABELS: Record<Platform, string> = {
  x_spaces: 'X Spaces',
  apple_podcasts: 'Apple Podcasts',
  spotify: 'Spotify',
  youtube: 'YouTube',
  xiaoyuzhou: '小宇宙',
  x_video: 'X/Twitter',
  youtube_video: 'YouTube',
  instagram: 'Instagram',
  xiaohongshu: '小红书',
}

export const QUALITY_OPTIONS = [
  { value: 'medium', label: '480p' },
  { value: 'high', label: '720p' },
  { value: 'highest', label: '1080p' },
]

export const WHISPER_MODELS: { value: WhisperModel; label: string; desc: string }[] = [
  { value: 'tiny', label: 'Tiny', desc: 'Fastest' },
  { value: 'base', label: 'Base', desc: 'Balanced' },
  { value: 'small', label: 'Small', desc: 'Better' },
  { value: 'medium', label: 'Medium', desc: 'High quality' },
  { value: 'large-v3', label: 'Large', desc: 'Best quality' },
  { value: 'turbo', label: 'Turbo', desc: 'Fast + accurate' },
]

export const TRANSCRIPTION_FORMATS: { value: TranscriptionFormat; label: string; desc: string }[] = [
  { value: 'text', label: 'Text', desc: 'Plain text' },
  { value: 'srt', label: 'SRT', desc: 'Subtitles' },
  { value: 'vtt', label: 'VTT', desc: 'Web subtitles' },
  { value: 'json', label: 'JSON', desc: 'With timestamps' },
  { value: 'dialogue', label: 'Dialogue', desc: 'Speaker labels' },
]

export const ENHANCEMENT_PRESETS: { value: EnhancementPreset; label: string; desc: string }[] = [
  { value: 'none', label: 'None', desc: 'No enhancement' },
  { value: 'light', label: 'Light', desc: 'Basic noise reduction' },
  { value: 'medium', label: 'Medium', desc: 'Voice isolation' },
  { value: 'heavy', label: 'Heavy', desc: 'Aggressive filtering' },
]

// Common languages for transcription (Whisper supports 99 languages)
export const TRANSCRIPTION_LANGUAGES: { value: string; label: string }[] = [
  { value: '', label: 'Auto-detect' },
  { value: 'en', label: 'English' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ja', label: 'Japanese' },
  { value: 'ko', label: 'Korean' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
  { value: 'it', label: 'Italian' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'ru', label: 'Russian' },
  { value: 'ar', label: 'Arabic' },
  { value: 'hi', label: 'Hindi' },
  { value: 'th', label: 'Thai' },
  { value: 'vi', label: 'Vietnamese' },
  { value: 'id', label: 'Indonesian' },
  { value: 'tr', label: 'Turkish' },
  { value: 'pl', label: 'Polish' },
  { value: 'nl', label: 'Dutch' },
  { value: 'sv', label: 'Swedish' },
  { value: 'uk', label: 'Ukrainian' },
]

export function formatDuration(seconds: number): string {
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

// ============ Social Media Clip Types ============

export type SocialPlatform = 'tiktok' | 'reels' | 'shorts' | 'twitter'

export interface ClipSuggestion {
  clip_id: string
  start_time: number
  end_time: number
  duration: number
  transcript_text: string
  hook: string
  caption: string
  hashtags: string[]
  viral_score: number
  engagement_factors: Record<string, number>
  compatible_platforms: SocialPlatform[]
  exported_files?: Record<string, string>
}

export interface ClipsResponse {
  success: boolean
  job_id: string
  clips: ClipSuggestion[]
  model?: string
  provider?: string
  tokens_used?: number
  error?: string
}

export const SOCIAL_PLATFORMS: { value: SocialPlatform; label: string; maxDuration: number; icon: string }[] = [
  { value: 'tiktok', label: 'TikTok', maxDuration: 180, icon: '🎵' },
  { value: 'reels', label: 'Instagram Reels', maxDuration: 90, icon: '📸' },
  { value: 'shorts', label: 'YouTube Shorts', maxDuration: 60, icon: '📺' },
  { value: 'twitter', label: 'Twitter/X', maxDuration: 140, icon: '🐦' },
]

export const VIRAL_SCORE_LABELS: { min: number; label: string; color: string }[] = [
  { min: 0.8, label: 'High Viral', color: 'text-green-600' },
  { min: 0.6, label: 'Good Potential', color: 'text-blue-600' },
  { min: 0.4, label: 'Moderate', color: 'text-yellow-600' },
  { min: 0, label: 'Low', color: 'text-gray-600' },
]

export function getViralScoreLabel(score: number): { label: string; color: string } {
  for (const item of VIRAL_SCORE_LABELS) {
    if (score >= item.min) {
      return { label: item.label, color: item.color }
    }
  }
  return { label: 'Low', color: 'text-gray-600' }
}
