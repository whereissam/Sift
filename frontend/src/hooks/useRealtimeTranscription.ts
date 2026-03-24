import { useState, useRef, useCallback, useEffect } from 'react'

export interface TranscriptionSegment {
  start: number
  end: number
  text: string
}

export interface TranscriptionConfig {
  model: string
  language?: string
  minChunkDuration?: number
  useContext?: boolean
  llmPolish?: boolean
}

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'transcribing' | 'error' | 'completed'

export interface RealtimeTranscriptionState {
  status: ConnectionStatus
  segments: TranscriptionSegment[]
  partialText: string
  fullText: string
  rawText: string | null
  language: string | null
  duration: number
  error: string | null
  llmPolishAvailable: boolean
  llmPolishEnabled: boolean
  llmPolished: boolean
  tokensUsed: number | null
}

export function useRealtimeTranscription() {
  const [state, setState] = useState<RealtimeTranscriptionState>({
    status: 'idle',
    segments: [],
    partialText: '',
    fullText: '',
    rawText: null,
    language: null,
    duration: 0,
    error: null,
    llmPolishAvailable: false,
    llmPolishEnabled: false,
    llmPolished: false,
    tokensUsed: null,
  })

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Clean up WebSocket and timers
  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // Check if LLM polish is available
  const checkLLMAvailability = useCallback(async () => {
    try {
      const response = await fetch('/api/transcribe/live/status')
      if (response.ok) {
        const data = await response.json()
        setState(prev => ({
          ...prev,
          llmPolishAvailable: data.llm_polish_available,
        }))
        return data.llm_polish_available
      }
    } catch {
      // Ignore errors
    }
    return false
  }, [])

  // Connect to WebSocket server
  const connect = useCallback((config: TranscriptionConfig) => {
    cleanup()

    setState(prev => ({
      ...prev,
      status: 'connecting',
      error: null,
      segments: [],
      partialText: '',
      fullText: '',
      rawText: null,
      language: null,
      duration: 0,
      llmPolished: false,
      tokensUsed: null,
    }))

    // Build WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/transcribe/live`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      // Send start message with configuration
      ws.send(JSON.stringify({
        type: 'start',
        config: {
          model: config.model,
          language: config.language || null,
          min_chunk_duration: config.minChunkDuration ?? 3.0,
          use_context: config.useContext ?? true,
          llm_polish: config.llmPolish ?? false,
        },
      }))

      // Set up ping interval to keep connection alive
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        switch (data.type) {
          case 'connected':
            setState(prev => ({
              ...prev,
              status: 'connected',
              error: null,
              llmPolishAvailable: data.llm_polish_available ?? false,
              llmPolishEnabled: data.llm_polish_enabled ?? false,
            }))
            break

          case 'language_detected':
            setState(prev => ({
              ...prev,
              language: data.language,
            }))
            break

          case 'partial':
            setState(prev => ({
              ...prev,
              status: 'transcribing',
              partialText: data.text || '',
            }))
            break

          case 'segment':
            setState(prev => {
              const newSegments = [...prev.segments, data.segment]
              const newFullText = newSegments.map(s => s.text).join(' ')
              return {
                ...prev,
                status: 'transcribing',
                segments: newSegments,
                partialText: '',
                fullText: newFullText,
              }
            })
            break

          case 'complete':
            setState(prev => ({
              ...prev,
              status: 'completed',
              fullText: data.full_text || '',
              rawText: data.raw_text || null,
              segments: data.segments || prev.segments,
              language: data.language || null,
              duration: data.duration || 0,
              partialText: '',
              llmPolished: data.llm_polished ?? false,
              tokensUsed: data.tokens_used ?? null,
            }))
            break

          case 'error':
            setState(prev => ({
              ...prev,
              status: data.recoverable ? prev.status : 'error',
              error: data.error || 'Unknown error',
            }))
            break

          case 'pong':
            // Keep-alive response, ignore
            break

          default:
            console.warn('Unknown message type:', data.type)
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }

    ws.onerror = () => {
      setState(prev => ({
        ...prev,
        status: 'error',
        error: 'Connection error. Please try again.',
      }))
    }

    ws.onclose = () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }

      // Only update status if not already completed or error
      setState(prev => {
        if (prev.status === 'completed' || prev.status === 'error') {
          return prev
        }
        return {
          ...prev,
          status: 'idle',
        }
      })
    }
  }, [cleanup])

  // Send audio chunk to server
  const sendAudio = useCallback(async (blob: Blob) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return
    }

    try {
      // Convert blob to base64
      const arrayBuffer = await blob.arrayBuffer()
      const base64 = btoa(
        new Uint8Array(arrayBuffer).reduce(
          (data, byte) => data + String.fromCharCode(byte),
          ''
        )
      )

      wsRef.current.send(JSON.stringify({
        type: 'audio',
        data: base64,
      }))

      // Update status to transcribing if connected
      setState(prev => {
        if (prev.status === 'connected') {
          return { ...prev, status: 'transcribing' }
        }
        return prev
      })
    } catch (error) {
      console.error('Failed to send audio:', error)
    }
  }, [])

  // Stop transcription session
  const stop = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }))
    }
  }, [])

  // Disconnect and reset
  const disconnect = useCallback(() => {
    cleanup()
    setState({
      status: 'idle',
      segments: [],
      partialText: '',
      fullText: '',
      rawText: null,
      language: null,
      duration: 0,
      error: null,
      llmPolishAvailable: false,
      llmPolishEnabled: false,
      llmPolished: false,
      tokensUsed: null,
    })
  }, [cleanup])

  // Reset to initial state (keeping connection)
  const reset = useCallback(() => {
    setState(prev => ({
      ...prev,
      segments: [],
      partialText: '',
      fullText: '',
      rawText: null,
      language: null,
      duration: 0,
      error: null,
      llmPolished: false,
      tokensUsed: null,
      status: prev.status === 'completed' || prev.status === 'error' ? 'idle' : prev.status,
    }))
  }, [])

  // Check LLM availability on mount
  useEffect(() => {
    checkLLMAvailability()
  }, [checkLLMAvailability])

  // Clean up on unmount
  useEffect(() => {
    return cleanup
  }, [cleanup])

  return {
    ...state,
    connect,
    sendAudio,
    stop,
    disconnect,
    reset,
    checkLLMAvailability,
    isConnected: state.status === 'connected' || state.status === 'transcribing',
  }
}

// Utility to convert blob to base64
export async function blobToBase64(blob: Blob): Promise<string> {
  const arrayBuffer = await blob.arrayBuffer()
  return btoa(
    new Uint8Array(arrayBuffer).reduce(
      (data, byte) => data + String.fromCharCode(byte),
      ''
    )
  )
}
