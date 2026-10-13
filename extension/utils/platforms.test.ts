import { describe, expect, it } from 'vitest';
import { detectPlatform, hostMatches } from './platforms';

describe('detectPlatform', () => {
  it.each([
    ['https://x.com/i/spaces/1vOxwdyYrlqKB', 'x_spaces'],
    ['https://twitter.com/i/spaces/abc', 'x_spaces'],
    ['https://x.com/SpaceX/status/2072695632104468543', 'x_video'],
    ['https://www.youtube.com/watch?v=I-PMiyYZkrs', 'youtube'],
    ['https://www.youtube.com/shorts/abc123', 'youtube'],
    ['https://youtu.be/I-PMiyYZkrs', 'youtube'],
    ['https://podcasts.apple.com/de/podcast/show/id123?i=456', 'apple_podcasts'],
    ['https://open.spotify.com/episode/abc123', 'spotify'],
    ['https://www.xiaoyuzhoufm.com/episode/6a4123349d2f5743683f2bd6', 'xiaoyuzhou'],
    ['https://www.ximalaya.com/sound/998052123', 'ximalaya'],
    ['https://www.xiaohongshu.com/explore/6a2417ff0000000006031044', 'xiaohongshu'],
    ['https://www.instagram.com/reel/DZKus9XB34d/', 'instagram'],
  ])('detects %s → %s', (url, type) => {
    expect(detectPlatform(url)?.type).toBe(type);
  });

  it('returns null for unsupported URLs', () => {
    expect(detectPlatform('https://example.com/page')).toBeNull();
    // A Ximalaya album page is not a single episode.
    expect(detectPlatform('https://www.ximalaya.com/waiyu/3240558/')).toBeNull();
  });

  it('X Spaces takes precedence over the generic status matcher', () => {
    expect(detectPlatform('https://x.com/i/spaces/123')?.type).toBe('x_spaces');
  });

  it.each([
    ['https://mobile.twitter.com/user/status/1', 'x_video'],
    ['https://m.youtube.com/watch?v=abc', 'youtube'],
    ['https://www.youtube.com/watch?feature=share&v=abc', 'youtube'],
    ['https://music.youtube.com/watch?v=abc', 'youtube'],
    ['https://open.spotify.com/intl-de/episode/abc123', 'spotify'],
    ['https://xhslink.com/a/AbCd', 'xiaohongshu'],
    ['https://instagram.com/p/abc/', 'instagram'],
    ['https://instagr.am/p/abc/', 'instagram'],
    ['HTTPS://WWW.YOUTUBE.COM/watch?v=abc', 'youtube'],
    ['http://x.com/i/spaces/abc', 'x_spaces'],
  ])('accepts genuine URL %s → %s', (url, type) => {
    expect(detectPlatform(url)?.type).toBe(type);
  });

  it('labels YouTube Music correctly', () => {
    expect(detectPlatform('https://music.youtube.com/watch?v=abc')?.name).toBe('YouTube Music');
  });

  it.each([
    // Platform-looking strings in query / fragment / path of a foreign host.
    'https://evil.example/?x=x.com/i/spaces/abc',
    'https://evil.example/#x.com/i/spaces/abc',
    'https://evil.example/x.com/i/spaces/abc',
    'https://evil.example/redirect?u=https://www.youtube.com/watch?v=abc',
    'https://evil.example/?q=open.spotify.com/episode/abc',
    // Userinfo tricks: hostname is evil.example.
    'https://x.com@evil.example/i/spaces/abc',
    'https://www.youtube.com:pw@evil.example/watch?v=abc',
    // Suffix / look-alike domains.
    'https://x.com.evil.example/i/spaces/abc',
    'https://notx.com/i/spaces/abc',
    'https://evilyoutube.com/watch?v=abc',
    'https://youtube.com.evil.example/watch?v=abc',
    'https://podcasts.apple.com.evil.example/us/podcast/x/id1',
    // Non-http(s) schemes.
    'javascript:alert(1)//x.com/i/spaces/abc',
    'data:text/html,x.com/i/spaces/abc',
    'file:///x.com/i/spaces/abc',
    'ftp://x.com/i/spaces/abc',
    'chrome://x.com/i/spaces/abc',
    // Garbage.
    '',
    'not a url x.com/i/spaces/abc',
    // Right host, wrong path (platform marker only in the query).
    'https://x.com/home?next=/i/spaces/abc',
  ])('rejects %s', (url) => {
    expect(detectPlatform(url)).toBeNull();
  });
});

describe('hostMatches', () => {
  it('matches the domain and its subdomains only', () => {
    expect(hostMatches('x.com', 'x.com')).toBe(true);
    expect(hostMatches('www.x.com', 'x.com')).toBe(true);
    expect(hostMatches('notx.com', 'x.com')).toBe(false);
    expect(hostMatches('x.com.evil.example', 'x.com')).toBe(false);
  });
});
