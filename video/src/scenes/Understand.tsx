import { AbsoluteFill, interpolate } from "remotion";
import { SceneFade, usePop } from "../anim";
import { colors, fonts } from "../theme";

const TRANSCRIPT = [
  ["0:00", "All right, so here we are in front of the elephants."],
  ["0:05", "The cool thing about these guys is that they have"],
  ["0:09", "really, really, really long trunks."],
  ["0:14", "And that's cool."],
];

const FEATURES = [
  "Transcribe · 99 languages",
  "Summaries & chapters",
  "Semantic search",
  "Ask your audio",
  "Translate",
  "Social clips",
];

const Line: React.FC<{ time: string; text: string; delay: number }> = ({ time, text, delay }) => {
  const pop = usePop(delay);
  return (
    <div
      style={{
        display: "flex",
        gap: 28,
        fontSize: 36,
        opacity: pop,
        transform: `translateY(${interpolate(pop, [0, 1], [20, 0])}px)`,
      }}
    >
      <span style={{ fontFamily: fonts.mono, color: colors.primary }}>{time}</span>
      <span style={{ color: colors.foreground }}>{text}</span>
    </div>
  );
};

const Feature: React.FC<{ label: string; delay: number }> = ({ label, delay }) => {
  const pop = usePop(delay);
  return (
    <div
      style={{
        padding: "22px 32px",
        borderRadius: 20,
        fontSize: 36,
        fontWeight: 600,
        color: colors.foreground,
        background: colors.card,
        border: `2px solid ${colors.border}`,
        opacity: pop,
        transform: `scale(${interpolate(pop, [0, 1], [0.85, 1])})`,
      }}
    >
      {label}
    </div>
  );
};

export const Understand: React.FC = () => {
  const heading = usePop(0);
  return (
    <SceneFade>
      <AbsoluteFill style={{ padding: "110px 140px", gap: 70 }}>
        <div
          style={{
            fontSize: 84,
            fontWeight: 800,
            letterSpacing: -2,
            color: colors.foreground,
            opacity: heading,
          }}
        >
          Then make it <span style={{ color: colors.primary }}>useful.</span>
        </div>
        <div style={{ display: "flex", gap: 80, flex: 1 }}>
          <div
            style={{
              flex: 1.3,
              padding: 52,
              borderRadius: 32,
              background: colors.card,
              boxShadow: "0 20px 60px rgba(31, 27, 24, 0.08)",
              display: "flex",
              flexDirection: "column",
              gap: 30,
            }}
          >
            <div style={{ fontSize: 28, fontWeight: 600, color: colors.muted }}>TRANSCRIPT</div>
            {TRANSCRIPT.map(([time, text], i) => (
              <Line key={time} time={time} text={text} delay={15 + i * 18} />
            ))}
          </div>
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: 22,
              justifyContent: "center",
            }}
          >
            {FEATURES.map((label, i) => (
              <Feature key={label} label={label} delay={60 + i * 10} />
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </SceneFade>
  );
};
