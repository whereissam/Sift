// Single source of truth for platform detection, shared by the content script,
// the popup, and the generated content-script `matches`. Keep in sync with the
// server's DownloaderFactory (app/core/platforms/).

export interface PlatformMatch {
  /** Server platform id (matches app/core/base.py Platform enum values). */
  type: string;
  /** Human-friendly label shown in the popup. */
  name: string;
}

interface PlatformPattern extends PlatformMatch {
  /**
   * Domains this pattern applies to. The parsed hostname must equal one of
   * these or be a subdomain of it (mirrors the server's platform host lists).
   */
  hosts: readonly string[];
  /** Anchored pattern tested against `pathname + search` of the parsed URL. */
  path: RegExp;
}

const X_HOSTS = ['x.com', 'twitter.com'] as const;
const YOUTUBE_HOSTS = ['youtube.com'] as const;

// Order matters: more specific patterns (e.g. X Spaces) before generic ones.
export const PLATFORM_PATTERNS: PlatformPattern[] = [
  { hosts: X_HOSTS, path: /^\/i\/spaces\//i, type: 'x_spaces', name: 'X Space' },
  { hosts: X_HOSTS, path: /^\/\w+\/status\//i, type: 'x_video', name: 'X Video' },
  { hosts: ['music.youtube.com'], path: /^\/watch\?(?:.*&)?v=/i, type: 'youtube', name: 'YouTube Music' },
  { hosts: YOUTUBE_HOSTS, path: /^\/watch\?(?:.*&)?v=/i, type: 'youtube', name: 'YouTube' },
  { hosts: YOUTUBE_HOSTS, path: /^\/shorts\//i, type: 'youtube', name: 'YouTube Shorts' },
  { hosts: ['youtu.be'], path: /^\/[\w-]+/i, type: 'youtube', name: 'YouTube' },
  { hosts: ['podcasts.apple.com'], path: /^\/.*\/podcast\//i, type: 'apple_podcasts', name: 'Apple Podcast' },
  { hosts: ['open.spotify.com'], path: /^\/(?:intl-[\w-]+\/)?episode\//i, type: 'spotify', name: 'Spotify Episode' },
  { hosts: ['xiaoyuzhoufm.com'], path: /^\/episode\//i, type: 'xiaoyuzhou', name: '小宇宙 Episode' },
  { hosts: ['ximalaya.com'], path: /^\/sound\/\d+/i, type: 'ximalaya', name: '喜马拉雅 Episode' },
  { hosts: ['xiaohongshu.com'], path: /^\/explore\//i, type: 'xiaohongshu', name: '小红书 Post' },
  { hosts: ['xhslink.com'], path: /^\/./i, type: 'xiaohongshu', name: '小红书 Post' },
  { hosts: ['instagram.com', 'instagr.am'], path: /^\/(?:reel|reels|p|tv)\//i, type: 'instagram', name: 'Instagram' },
];

/** True when `hostname` is `domain` itself or a subdomain of it. */
export function hostMatches(hostname: string, domain: string): boolean {
  const h = hostname.toLowerCase();
  return h === domain || h.endsWith(`.${domain}`);
}

/**
 * Return the first matching platform for a URL, or null if unsupported.
 *
 * The URL is parsed (never regex-matched as a whole string) so platform
 * look-alikes in the query, fragment, userinfo, or a suffix domain
 * (`https://evil.example/?u=x.com/i/spaces/1`, `https://x.com@evil.example/`,
 * `https://x.com.evil.example/`) are rejected. Only http(s) is accepted.
 */
export function detectPlatform(url: string): PlatformMatch | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;

  const target = parsed.pathname + parsed.search;
  for (const p of PLATFORM_PATTERNS) {
    if (!p.hosts.some((d) => hostMatches(parsed.hostname, d))) continue;
    if (p.path.test(target)) {
      return { type: p.type, name: p.name };
    }
  }
  return null;
}

// Host match patterns for the content script (derived so they can't drift from
// the detection list above). Broad per-host; precise URL matching happens in
// detectPlatform() at runtime.
export const CONTENT_MATCHES: string[] = [
  '*://x.com/*',
  '*://twitter.com/*',
  '*://*.youtube.com/*',
  '*://youtube.com/*',
  '*://youtu.be/*',
  '*://podcasts.apple.com/*',
  '*://open.spotify.com/*',
  '*://*.xiaoyuzhoufm.com/*',
  '*://*.ximalaya.com/*',
  '*://*.xiaohongshu.com/*',
  '*://xhslink.com/*',
  '*://*.instagram.com/*',
];
