import { describe, expect, it } from 'vitest';
import {
  apiKeyDecision,
  buildAddUrl,
  isInsecureRemoteServer,
  isLoopbackHost,
  normalizeServerUrl,
  originPattern,
  serverOrigin,
} from './server';

describe('normalizeServerUrl', () => {
  it('trims whitespace and trailing slashes', () => {
    expect(normalizeServerUrl('  http://localhost:8000/  ')).toBe('http://localhost:8000');
    expect(normalizeServerUrl('http://localhost:8000///')).toBe('http://localhost:8000');
    expect(normalizeServerUrl('https://sift.example.com')).toBe('https://sift.example.com');
  });
});

describe('buildAddUrl', () => {
  it('builds an encoded /api/add URL', () => {
    const url = buildAddUrl('http://localhost:8000/', 'https://youtu.be/abc?x=1', 'download');
    expect(url).toBe(
      'http://localhost:8000/api/add?url=https%3A%2F%2Fyoutu.be%2Fabc%3Fx%3D1&action=download',
    );
  });

  it('supports the transcribe action', () => {
    expect(buildAddUrl('http://localhost:8000', 'https://x.com/a/status/1', 'transcribe')).toContain(
      'action=transcribe',
    );
  });
});

describe('originPattern', () => {
  it('derives an <origin>/* match pattern', () => {
    expect(originPattern('https://sift.example.com/path/')).toBe('https://sift.example.com/*');
    expect(originPattern('http://192.168.1.5:8000')).toBe('http://192.168.1.5:8000/*');
  });
});

describe('isInsecureRemoteServer', () => {
  it.each([
    'https://sift.example.com',
    'https://192.168.1.5:8000',
    'http://localhost:8000',
    'http://LOCALHOST:8000/',
    'http://127.0.0.1:8000',
    'http://[::1]:8000',
  ])('%s is not insecure-remote', (url) => {
    expect(isInsecureRemoteServer(url)).toBe(false);
  });

  it.each([
    'http://sift.example.com',
    'http://192.168.1.5:8000',
    'http://localhost.evil.example',
    'http://127.0.0.1.evil.example',
    'ftp://sift.example.com',
    'not a url',
  ])('%s is insecure-remote', (url) => {
    expect(isInsecureRemoteServer(url)).toBe(true);
  });
});

describe('isLoopbackHost', () => {
  it('only accepts exact loopback hostnames', () => {
    expect(isLoopbackHost('localhost')).toBe(true);
    expect(isLoopbackHost('127.0.0.1')).toBe(true);
    expect(isLoopbackHost('[::1]')).toBe(true);
    expect(isLoopbackHost('localhost.evil.example')).toBe(false);
    expect(isLoopbackHost('10.0.0.1')).toBe(false);
  });
});

describe('serverOrigin', () => {
  it('returns the origin or null', () => {
    expect(serverOrigin('http://192.168.1.5:8000/ui/')).toBe('http://192.168.1.5:8000');
    expect(serverOrigin('nope')).toBeNull();
  });
});

describe('apiKeyDecision', () => {
  it('returns none when no key is configured', () => {
    expect(apiKeyDecision('http://sift.example.com', '', [])).toBe('none');
  });

  it('sends the key over https and loopback http', () => {
    expect(apiKeyDecision('https://sift.example.com', 'k', [])).toBe('send');
    expect(apiKeyDecision('http://localhost:8000', 'k', [])).toBe('send');
    expect(apiKeyDecision('http://127.0.0.1:8000', 'k', [])).toBe('send');
    expect(apiKeyDecision('http://[::1]:8000', 'k', [])).toBe('send');
  });

  it('requires confirmation for remote plain http', () => {
    expect(apiKeyDecision('http://192.168.1.5:8000', 'k', [])).toBe('needs-confirmation');
    expect(apiKeyDecision('http://sift.example.com/', 'k', [])).toBe('needs-confirmation');
  });

  it('honours consent only for the exact origin', () => {
    const allowed = ['http://192.168.1.5:8000'];
    expect(apiKeyDecision('http://192.168.1.5:8000/', 'k', allowed)).toBe('send');
    expect(apiKeyDecision('http://192.168.1.5:9000', 'k', allowed)).toBe('needs-confirmation');
    expect(apiKeyDecision('http://192.168.1.6:8000', 'k', allowed)).toBe('needs-confirmation');
  });

  it('never sends to an unparseable server URL', () => {
    expect(apiKeyDecision('not a url', 'k', ['null'])).toBe('needs-confirmation');
  });
});
