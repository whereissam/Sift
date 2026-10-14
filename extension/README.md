# Sift Browser Extension (WXT)

One-click capture from your browser to your Sift server. Built with
[WXT](https://wxt.dev) (TypeScript + Vite), producing Chrome (MV3) and Firefox
builds from a single config.

> Supersedes the legacy plain-JS extension in `../browser-extension/`.

## Develop

```bash
bun install          # installs deps + runs `wxt prepare`
bun run dev          # Chrome, with HMR
bun run dev:firefox  # Firefox
bun test             # Vitest unit tests (pure logic)
```

`bun run dev` launches a browser with the extension loaded and hot-reloads on
change.

## Build

```bash
bun run build            # → .output/chrome-mv3/
bun run build:firefox    # → .output/firefox-mv2/
bun run zip              # distributable zip
```

Load unpacked: `chrome://extensions` → Developer mode → **Load unpacked** →
select `.output/chrome-mv3/`.

## Configuration

Open the popup and set your **Server** URL (default `http://localhost:8000`).
Pointing at a remote/LAN server triggers a one-time host-permission prompt so
the extension may reach it. If your server sets an `API_KEY`, enter it in the
**API key** field. The key is only sent automatically over `https://` or to a
loopback `http://` server (`localhost`, `127.0.0.1`, `[::1]`). For a remote
plain-`http://` server the popup warns that the key would travel unencrypted
and refuses to send it until you tick the per-server confirmation checkbox.

## Supported platforms

Detection lives in one place — [`utils/platforms.ts`](utils/platforms.ts),
kept in sync with the server's `DownloaderFactory`: X Spaces, X/Twitter video,
YouTube (+ Shorts/Music), Apple Podcasts, Spotify, 小宇宙, 喜马拉雅 (single
episodes), 小红书, Instagram.

## Layout

```
wxt.config.ts            generated-manifest config (Chrome + Firefox)
entrypoints/
  background.ts          toolbar badge + install defaults
  content.ts             per-page detection (cheap SPA-nav polling)
  popup/                 popup UI (index.html / main.ts / style.css)
utils/
  platforms.ts           single source of truth for URL detection + matches
  server.ts              server URL / quick-add URL / origin helpers
  *.test.ts              Vitest unit tests
```
