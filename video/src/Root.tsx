import { Composition } from "remotion";
import { SiftPromo } from "./SiftPromo";
import { DURATION, FPS } from "./timeline";

export const Root: React.FC = () => (
  <Composition
    id="SiftPromo"
    component={SiftPromo}
    durationInFrames={DURATION}
    fps={FPS}
    width={1920}
    height={1080}
  />
);
