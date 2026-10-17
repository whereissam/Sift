# Free-Tool Landing Pages

Status: **design sketch** (2026-10-17). Nothing here is built yet.

Free single-purpose tools that rank in search and lead to Sift Pro. Pro's
paid job is *following* sources over time (digests, alerts,
[KOL scorecards](kol-scorecard.md)), not one-off downloads.

## Rules for every page

- The hosted tool returns **text** — transcript, summary, key quotes. It
  never stores or serves another creator's media.
- Podcast "download" = the **publisher's own RSS enclosure URL**; the file
  comes from their server. (Apple / Spotify / 小宇宙 episodes already resolve
  to RSS.)
- Real file downloads happen in the **desktop app or browser extension**, on
  the user's machine.
- Prefer existing transcripts (YouTube captions, Spotify Read Along) — free,
  fast, no audio touched.

## Pages

| # | Page · target query | Input | Free output | Pro hook |
|---|---|---|---|---|
| 1 | `/tools/x-spaces-transcript` · "X Spaces transcript / summary" | Spaces link | Transcript + summary + key claims w/ timestamps · MP3 via extension | Follow this host → digest of every Space |
| 2 | `/zh/xiaoyuzhou` · "小宇宙 转文字 / 下载" | 小宇宙 link | 逐字稿 + 摘要 + 金句 · original audio link (RSS) | 订阅节目，每周自动摘要 |
| 3 | `/zh/ximalaya` · "喜马拉雅 转文字" | `/sound/` link (free episodes) | 逐字稿 + 摘要 | Same |
| 4 | `/tools/podcast-transcript` · "podcast to text" | Apple / RSS / Spotify episode | Transcript + summary + chapters · original MP3 link | Follow the show / Ask the episode |
| 5 | `/tools/youtube-summary` · "YouTube transcript / summary" | YouTube link | Existing captions + summary (no download) | Follow the channel |
| 6 | `/kol/<name>` (programmatic) · "<name> predictions" | — | Public scorecard: record, open calls, timestamp links | Track any KOL, alerts, full leaderboard |

Left out on purpose: Spotify music, YouTube video/MP3 download, Instagram,
小红书, Discord — high legal risk, blocked by app stores, or off-story.

Search volumes are unverified; check Keyword Planner / Baidu Index before
building.

## Result page anatomy

```
[Paste link ▸]
🎙  "Episode title" · host · 1h 12m · source ↗
Summary (5 bullets)                       ← free, no signup
Key claims  · [▶ 12:04] "…"               ← free
Transcript  · first 10 min                ← full + TXT/SRT/MD export = email signup
⭐ Follow @host — weekly digest           [Try Pro]
🔌 Same via API / MCP                     [Docs]
```

## Cost control

- Transcribe each episode once and serve it to everyone (`asset_identity`).
- Free: e.g. 3 episodes/day, ≤ 2 h each, queued; Pro skips the queue.
- Public pages show **summaries + short quotes** only; the full transcript
  goes only to the requester.

## Technical

The app frontend is a Vite single-page app, which search engines index poorly.
Build the landing pages as a static site (e.g. Astro) under `/tools/*`,
`/zh/*` and `/kol/*`, with `hreflang` between the English and Chinese pages,
calling the existing API.

## Measure per page

Visits → tool runs → email signups → Pro trials.

## Order

1. #1 X Spaces (matches the crypto test)
2. #6 KOL pages (from the scorecard)
3. #2 / #3 Chinese podcasts
4. #4 / #5 (most crowded)
