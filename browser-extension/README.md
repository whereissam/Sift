# Sift Browser Extension (legacy)

> **Superseded by [`../extension/`](../extension/)** — a WXT (TypeScript + Vite)
> rewrite with a single cross-browser build, a shared platform-detection module,
> configurable remote-server support, and an API-key field. This plain-JS
> version is kept for reference and will be removed once the WXT extension is
> published.

One-click download and transcription from your browser.

## Installation

### Chrome / Edge / Brave

1. Open `chrome://extensions/` (or equivalent)
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select this `browser-extension` folder
5. The Sift icon will appear in your toolbar

### Firefox

1. Rename `manifest.firefox.json` to `manifest.json` (backup the Chrome one first)
2. Open `about:debugging#/runtime/this-firefox`
3. Click "Load Temporary Add-on"
4. Select the `manifest.json` file

## Usage

1. Navigate to a supported page (X Spaces, YouTube, Apple Podcasts, Spotify, 小宇宙)
2. Click the Sift icon in your toolbar
3. Click "Transcribe" or "Download Audio"
4. The job will be queued and the Web UI will open

## Configuration

Click the extension icon and enter your Sift server URL at the bottom:
- Default: `http://localhost:8000`
- For remote servers, use the full URL

## Supported Platforms

- X Spaces (`x.com/i/spaces/...`)
- X/Twitter Videos (`x.com/.../status/...`)
- YouTube (`youtube.com/watch?v=...`)
- Apple Podcasts (`podcasts.apple.com/.../podcast/...`)
- Spotify Episodes (`open.spotify.com/episode/...`)
- 小宇宙 (`xiaoyuzhoufm.com/episode/...`)

## Bookmarklet Alternative

If you prefer not to install an extension, create a bookmarklet:

1. Create a new bookmark
2. Set the URL to:

```javascript
javascript:(function(){var s='http://localhost:8000';window.open(s+'/api/add?url='+encodeURIComponent(window.location.href)+'&action=transcribe')})()
```

3. Replace `http://localhost:8000` with your server URL if different
4. Click the bookmark on any supported page, then confirm in the tab it opens

Sift asks before starting a job that another website's page requested, so a
site cannot start downloads on your machine just by being visited. The
extensions are trusted and skip this step.

### Download-only bookmarklet:

```javascript
javascript:(function(){var s='http://localhost:8000';window.open(s+'/api/add?url='+encodeURIComponent(window.location.href)+'&action=download')})()
```

## Generating Icons

If you need to regenerate the PNG icons from the SVG:

```bash
./generate-icons.sh
```

Requires ImageMagick or librsvg.
