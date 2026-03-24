export type SubscriptionType = 'rss' | 'youtube_channel' | 'youtube_playlist'
export type SubscriptionPlatform = 'podcast' | 'youtube'
export type SubscriptionItemStatus = 'pending' | 'downloading' | 'completed' | 'failed' | 'skipped'

export interface Subscription {
  id: string
  name: string
  subscription_type: SubscriptionType
  source_url: string | null
  source_id: string | null
  platform: SubscriptionPlatform
  enabled: boolean
  auto_transcribe: boolean
  transcribe_model: string
  transcribe_language: string | null
  download_limit: number
  output_format: string
  quality: string
  output_dir: string | null
  last_checked_at: string | null
  last_new_content_at: string | null
  total_downloaded: number
  created_at: string
  updated_at: string
  pending_count?: number
  completed_count?: number
}

export interface SubscriptionItem {
  id: string
  subscription_id: string
  content_id: string
  content_url: string
  title: string | null
  published_at: string | null
  status: SubscriptionItemStatus
  job_id: string | null
  file_path: string | null
  transcription_path: string | null
  error: string | null
  discovered_at: string
  downloaded_at: string | null
}

export interface SubscriptionListResponse {
  subscriptions: Subscription[]
  total: number
}

export interface SubscriptionItemListResponse {
  items: SubscriptionItem[]
  total: number
  subscription_id: string
}

export const SUBSCRIPTION_TYPES: { value: SubscriptionType; label: string; desc: string }[] = [
  { value: 'rss', label: 'RSS/Podcast', desc: 'Apple Podcasts, RSS feeds' },
  { value: 'youtube_channel', label: 'YouTube Channel', desc: 'All videos from a channel' },
  { value: 'youtube_playlist', label: 'YouTube Playlist', desc: 'Videos from a playlist' },
]

export const WHISPER_MODELS = [
  { value: 'tiny', label: 'Tiny' },
  { value: 'base', label: 'Base' },
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large-v3', label: 'Large' },
]

export const OUTPUT_FORMATS = [
  { value: 'm4a', label: 'M4A' },
  { value: 'mp3', label: 'MP3' },
]

export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`

  return date.toLocaleDateString()
}

export function getStatusColor(status: SubscriptionItemStatus): string {
  switch (status) {
    case 'completed':
      return 'text-green-600 bg-green-100 dark:text-green-400 dark:bg-green-900/30'
    case 'downloading':
      return 'text-blue-600 bg-blue-100 dark:text-blue-400 dark:bg-blue-900/30'
    case 'pending':
      return 'text-yellow-600 bg-yellow-100 dark:text-yellow-400 dark:bg-yellow-900/30'
    case 'failed':
      return 'text-red-600 bg-red-100 dark:text-red-400 dark:bg-red-900/30'
    case 'skipped':
      return 'text-gray-600 bg-gray-100 dark:text-gray-400 dark:bg-gray-800'
    default:
      return 'text-gray-600 bg-gray-100'
  }
}

export function getPlatformIcon(type: SubscriptionType): string {
  switch (type) {
    case 'rss':
      return '🎙️'
    case 'youtube_channel':
    case 'youtube_playlist':
      return '📺'
    default:
      return '📁'
  }
}
