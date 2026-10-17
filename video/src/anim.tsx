import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 → 1 over [start, end] frames, clamped. */
export function progress(frame: number, start: number, end: number): number {
  return interpolate(frame, [start, end], [0, 1], clamp);
}

/** A spring that starts at `delay` frames. */
export function usePop(delay = 0, damping = 14): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping } });
}

/** Fades the whole scene in at its start and out at its end. */
export const SceneFade: React.FC<{ children: React.ReactNode; fade?: number }> = ({
  children,
  fade = 12,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const opacity = Math.min(
    progress(frame, 0, fade),
    1 - progress(frame, durationInFrames - fade, durationInFrames),
  );
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};
