import { AbsoluteFill, Img, staticFile } from "remotion";
import { SceneFade, usePop } from "../anim";
import { colors, fonts } from "../theme";

export const Outro: React.FC = () => {
  const logo = usePop(0, 12);
  const words = usePop(10);
  const link = usePop(24);
  return (
    <SceneFade>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 36 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 36 }}>
          <Img
            src={staticFile("logo.png")}
            style={{ width: 140, height: 140, borderRadius: 32, transform: `scale(${logo})` }}
          />
          <span style={{ fontSize: 120, fontWeight: 800, letterSpacing: -4, color: colors.foreground }}>
            Sift
          </span>
        </div>
        <div style={{ fontSize: 52, color: colors.muted, opacity: words }}>
          Download <span style={{ color: colors.primary }}>·</span> Transcribe{" "}
          <span style={{ color: colors.primary }}>·</span> Understand
        </div>
        <div
          style={{
            fontFamily: fonts.mono,
            fontSize: 36,
            color: colors.foreground,
            padding: "16px 32px",
            borderRadius: 16,
            background: colors.primarySoft,
            opacity: link,
          }}
        >
          github.com/whereissam/Sift
        </div>
      </AbsoluteFill>
    </SceneFade>
  );
};
