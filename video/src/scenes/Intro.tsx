import { AbsoluteFill, Img, interpolate, staticFile } from "remotion";
import { SceneFade, usePop } from "../anim";
import { colors } from "../theme";

export const Intro: React.FC = () => {
  const logo = usePop(0, 12);
  const title = usePop(10);
  const tagline = usePop(24);

  return (
    <SceneFade>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 28 }}>
        <Img
          src={staticFile("logo.png")}
          style={{ width: 220, height: 220, borderRadius: 48, transform: `scale(${logo})` }}
        />
        <div
          style={{
            fontSize: 140,
            fontWeight: 800,
            letterSpacing: -4,
            color: colors.foreground,
            opacity: title,
            transform: `translateY(${interpolate(title, [0, 1], [30, 0])}px)`,
          }}
        >
          Sift
        </div>
        <div
          style={{
            fontSize: 48,
            color: colors.muted,
            opacity: tagline,
            transform: `translateY(${interpolate(tagline, [0, 1], [20, 0])}px)`,
          }}
        >
          Paste a link. Get the <b style={{ color: colors.primary }}>MP3</b> or{" "}
          <b style={{ color: colors.primary }}>MP4</b>.
        </div>
      </AbsoluteFill>
    </SceneFade>
  );
};
