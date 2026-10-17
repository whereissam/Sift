import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { SceneFade, progress, usePop } from "../anim";
import { colors, fonts } from "../theme";

const URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw";

// Frame marks within the scene (30 fps).
const T = {
  typeStart: 15,
  typeEnd: 75,
  detected: 82,
  mp3Download: [100, 150],
  mp3Done: 155,
  switchToVideo: 185,
  mp4Download: [200, 250],
  mp4Done: 255,
} as const;

const Toggle: React.FC<{ label: string; active: boolean }> = ({ label, active }) => (
  <div
    style={{
      padding: "18px 40px",
      borderRadius: 18,
      fontSize: 34,
      fontWeight: 600,
      color: active ? colors.card : colors.muted,
      background: active ? colors.primary : "transparent",
    }}
  >
    {label}
  </div>
);

const ProgressBar: React.FC<{ value: number }> = ({ value }) => (
  <div style={{ height: 14, borderRadius: 999, background: colors.border, overflow: "hidden" }}>
    <div
      style={{
        width: `${value * 100}%`,
        height: "100%",
        borderRadius: 999,
        background: colors.primary,
      }}
    />
  </div>
);

const FileRow: React.FC<{ name: string; detail: string; delay: number }> = ({
  name,
  detail,
  delay,
}) => {
  const pop = usePop(delay);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 24,
        padding: "22px 30px",
        borderRadius: 20,
        border: `2px solid ${colors.border}`,
        opacity: pop,
        transform: `translateX(${interpolate(pop, [0, 1], [-40, 0])}px)`,
      }}
    >
      <div
        style={{
          width: 52,
          height: 52,
          borderRadius: 999,
          background: colors.success,
          color: colors.card,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 32,
          fontWeight: 800,
        }}
      >
        ✓
      </div>
      <span style={{ fontSize: 36, fontWeight: 600, color: colors.foreground }}>{name}</span>
      <span style={{ fontSize: 30, color: colors.muted, marginLeft: "auto" }}>{detail}</span>
    </div>
  );
};

export const DownloadDemo: React.FC = () => {
  const frame = useCurrentFrame();
  const card = usePop(0, 16);
  const typed = Math.round(progress(frame, T.typeStart, T.typeEnd) * URL.length);
  const caretOn = typed < URL.length && Math.floor(frame / 8) % 2 === 0;
  const detected = usePop(T.detected);
  const video = frame >= T.switchToVideo;
  const mp3 = progress(frame, ...T.mp3Download);
  const mp4 = progress(frame, ...T.mp4Download);
  const downloading = (frame >= T.mp3Download[0] && frame < T.mp3Done) ||
    (frame >= T.mp4Download[0] && frame < T.mp4Done);

  return (
    <SceneFade>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div
          style={{
            width: 1400,
            padding: 64,
            borderRadius: 40,
            background: colors.card,
            boxShadow: "0 30px 80px rgba(31, 27, 24, 0.12)",
            display: "flex",
            flexDirection: "column",
            gap: 36,
            opacity: card,
            transform: `scale(${interpolate(card, [0, 1], [0.94, 1])})`,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 20,
              padding: "26px 32px",
              borderRadius: 20,
              border: `3px solid ${typed > 0 ? colors.primary : colors.border}`,
              fontFamily: fonts.mono,
              fontSize: 36,
              color: colors.foreground,
            }}
          >
            <span>
              {URL.slice(0, typed) || <span style={{ color: colors.muted }}>Paste a link…</span>}
              <span style={{ opacity: caretOn ? 1 : 0, color: colors.primary }}>|</span>
            </span>
            <span
              style={{
                marginLeft: "auto",
                fontFamily: fonts.sans,
                fontSize: 28,
                fontWeight: 600,
                color: colors.primary,
                background: colors.primarySoft,
                padding: "8px 20px",
                borderRadius: 999,
                opacity: detected,
              }}
            >
              YouTube
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
            <div
              style={{
                display: "flex",
                padding: 8,
                borderRadius: 24,
                background: colors.background,
              }}
            >
              <Toggle label="MP3 audio" active={!video} />
              <Toggle label="MP4 video" active={video} />
            </div>
            <div
              style={{
                marginLeft: "auto",
                padding: "20px 48px",
                borderRadius: 18,
                fontSize: 34,
                fontWeight: 600,
                color: colors.card,
                background: colors.foreground,
                transform: `scale(${downloading ? 0.97 : 1})`,
              }}
            >
              {downloading ? "Downloading…" : "Download"}
            </div>
          </div>

          <ProgressBar value={video ? mp4 : mp3} />

          <div style={{ display: "flex", flexDirection: "column", gap: 18, minHeight: 220 }}>
            {frame >= T.mp3Done && (
              <FileRow name="Me at the zoo.mp3" detail="audio · 0:19" delay={T.mp3Done} />
            )}
            {frame >= T.mp4Done && (
              <FileRow name="Me at the zoo.mp4" detail="720p · 0:19" delay={T.mp4Done} />
            )}
          </div>
        </div>
      </AbsoluteFill>
    </SceneFade>
  );
};
