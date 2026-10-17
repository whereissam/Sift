import { AbsoluteFill, interpolate } from "remotion";
import { SceneFade, usePop } from "../anim";
import { colors } from "../theme";

// The platforms sift-core has adapters for (sift_core/platforms/__init__.py).
const PLATFORMS: { name: string; kind: "audio" | "video" | "both" }[] = [
  { name: "YouTube", kind: "both" },
  { name: "X / Twitter", kind: "video" },
  { name: "X Spaces", kind: "audio" },
  { name: "Apple Podcasts", kind: "audio" },
  { name: "Spotify", kind: "audio" },
  { name: "Instagram", kind: "video" },
  { name: "Discord", kind: "audio" },
  { name: "小红书", kind: "video" },
  { name: "小宇宙", kind: "audio" },
  { name: "喜马拉雅", kind: "audio" },
];

const KIND_LABEL = { audio: "MP3", video: "MP4", both: "MP3 · MP4" };

const Chip: React.FC<{ name: string; kind: keyof typeof KIND_LABEL; delay: number }> = ({
  name,
  kind,
  delay,
}) => {
  const pop = usePop(delay);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 24,
        width: 520,
        padding: "26px 34px",
        borderRadius: 24,
        background: colors.card,
        border: `2px solid ${colors.border}`,
        boxShadow: "0 8px 24px rgba(31, 27, 24, 0.06)",
        opacity: pop,
        transform: `translateY(${interpolate(pop, [0, 1], [40, 0])}px) scale(${interpolate(pop, [0, 1], [0.9, 1])})`,
      }}
    >
      <span style={{ fontSize: 40, fontWeight: 600, color: colors.foreground }}>{name}</span>
      <span
        style={{
          fontSize: 26,
          fontWeight: 600,
          color: colors.primary,
          background: colors.primarySoft,
          padding: "6px 16px",
          borderRadius: 999,
        }}
      >
        {KIND_LABEL[kind]}
      </span>
    </div>
  );
};

export const Platforms: React.FC = () => {
  const heading = usePop(0);
  return (
    <SceneFade>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 60 }}>
        <div
          style={{
            fontSize: 84,
            fontWeight: 800,
            letterSpacing: -2,
            color: colors.foreground,
            opacity: heading,
          }}
        >
          One box. <span style={{ color: colors.primary }}>Ten platforms.</span>
        </div>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            width: 520 * 3 + 28 * 2,
            gap: 28,
            justifyContent: "center",
          }}
        >
          {PLATFORMS.map((p, i) => (
            <Chip key={p.name} name={p.name} kind={p.kind} delay={12 + i * 6} />
          ))}
        </div>
      </AbsoluteFill>
    </SceneFade>
  );
};
