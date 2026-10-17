# Sift promo video

A ~30 s 1080p promo built with [Remotion](https://www.remotion.dev): logo →
supported platforms → paste a link and get MP3 / MP4 → transcript and
knowledge features → outro.

```bash
cd video
bun install
bun run studio      # live preview / scrub in the browser
bun run render      # -> out/sift-promo.mp4
bun run still       # -> out/poster.png (thumbnail)
bun test && bun run typecheck
```

- Scene order and lengths: `src/timeline.ts`
- Colors and fonts (match `frontend/src/index.css`): `src/theme.ts`
- Scenes: `src/scenes/*.tsx`
- The logo comes from `frontend/public/logo.png` (see `remotion.config.ts`), so
  a new app logo shows up in the next render.
