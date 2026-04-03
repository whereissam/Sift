import { useState, useEffect } from 'react'
import { Loader2, Check, AlertCircle, FolderOpen, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface ObsidianSettings {
  vault_path: string
  subfolder: string
  template: string | null
  default_tags: string[]
  is_configured: boolean
}

export function ObsidianSettings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [validationResult, setValidationResult] = useState<{
    valid: boolean
    error?: string
  } | null>(null)

  const [vaultPath, setVaultPath] = useState('')
  const [subfolder, setSubfolder] = useState('Sift')
  const [defaultTags, setDefaultTags] = useState('sift, transcript')
  const [isConfigured, setIsConfigured] = useState(false)

  // Fetch current settings on mount
  useEffect(() => {
    fetchSettings()
  }, [])

  const fetchSettings = async () => {
    try {
      const response = await fetch('/api/obsidian/settings')
      if (response.ok) {
        const data: ObsidianSettings = await response.json()
        setVaultPath(data.vault_path || '')
        setSubfolder(data.subfolder || 'Sift')
        setDefaultTags(data.default_tags?.join(', ') || 'sift, transcript')
        setIsConfigured(data.is_configured)
      }
    } catch (err) {
      console.error('Failed to fetch Obsidian settings:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleValidate = async () => {
    if (!vaultPath.trim()) {
      setError('Please enter a vault path')
      return
    }

    setValidating(true)
    setValidationResult(null)
    setError(null)

    try {
      const response = await fetch(`/api/obsidian/validate?vault_path=${encodeURIComponent(vaultPath)}`, {
        method: 'POST',
      })

      const data = await response.json()
      setValidationResult(data)

      if (!data.valid) {
        setError(data.error || 'Vault validation failed')
      }
    } catch (err) {
      setValidationResult({
        valid: false,
        error: err instanceof Error ? err.message : 'Validation failed',
      })
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!vaultPath.trim()) {
      setError('Vault path is required')
      return
    }

    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      // Parse tags from comma-separated string
      const tags = defaultTags
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t.length > 0)

      const response = await fetch('/api/obsidian/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          vault_path: vaultPath,
          subfolder: subfolder || 'Sift',
          default_tags: tags,
        }),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to save settings')
      }

      const data = await response.json()
      setIsConfigured(data.is_configured)
      setSuccess('Settings saved successfully')
      setValidationResult({ valid: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-card rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    )
  }

  return (
    <div className="bg-card rounded-xl shadow-lg p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground mb-2">Obsidian Integration</h2>
        <p className="text-sm text-muted-foreground">
          Export transcriptions directly to your Obsidian vault as markdown notes with YAML frontmatter.
        </p>
      </div>

      {/* Vault Path */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Vault Path
          {isConfigured && (
            <span className="ml-2 text-xs text-green-600 font-normal">(configured)</span>
          )}
        </label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <FolderOpen className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              type="text"
              value={vaultPath}
              onChange={(e) => {
                setVaultPath(e.target.value)
                setValidationResult(null)
              }}
              placeholder="/path/to/your/obsidian/vault"
              className="h-10 pl-10"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          The root directory of your Obsidian vault (contains .obsidian folder)
        </p>
      </div>

      {/* Subfolder */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Subfolder
        </label>
        <Input
          type="text"
          value={subfolder}
          onChange={(e) => setSubfolder(e.target.value)}
          placeholder="Sift"
          className="h-10"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Notes will be saved in this subfolder within your vault. Leave empty for vault root.
        </p>
      </div>

      {/* Default Tags */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Default Tags
        </label>
        <Input
          type="text"
          value={defaultTags}
          onChange={(e) => setDefaultTags(e.target.value)}
          placeholder="sift, transcript"
          className="h-10"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Comma-separated tags to add to every exported note
        </p>
      </div>

      {/* Validation Result */}
      {validationResult && (
        <div
          className={`p-4 rounded-lg ${
            validationResult.valid
              ? 'bg-green-500/10 border border-green-500/20'
              : 'bg-destructive/10 border border-destructive/20'
          }`}
        >
          <div className="flex items-start gap-3">
            {validationResult.valid ? (
              <Check className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
            ) : (
              <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            )}
            <div className="flex-1 min-w-0">
              <div className="font-medium text-foreground">
                {validationResult.valid ? 'Vault is valid and writable!' : 'Vault validation failed'}
              </div>
              {validationResult.error && (
                <div className="text-sm text-destructive mt-1">{validationResult.error}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Error/Success Messages */}
      {error && !validationResult && (
        <div className="bg-destructive/10 text-destructive p-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {success && (
        <div className="bg-green-500/10 text-green-600 p-3 rounded-lg text-sm flex items-center gap-2">
          <Check className="h-4 w-4" />
          {success}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2 text-muted-foreground">
        <Button
          type="button"
          variant="outline"
          onClick={handleValidate}
          disabled={validating || saving || !vaultPath.trim()}
          className="flex-1"
        >
          {validating ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Validating...
            </>
          ) : (
            <>
              <Zap className="h-4 w-4 mr-2" />
              Validate Vault
            </>
          )}
        </Button>
        <Button
          type="button"
          onClick={handleSave}
          disabled={saving || validating || !vaultPath.trim()}
          className="flex-1"
        >
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Check className="h-4 w-4 mr-2" />
              Save Settings
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
