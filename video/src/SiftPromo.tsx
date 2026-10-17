import { AbsoluteFill, Sequence } from "remotion";
import { colors, fonts } from "./theme";
import { SCENES, sceneStart } from "./timeline";
import { Intro } from "./scenes/Intro";
import { Platforms } from "./scenes/Platforms";
import { DownloadDemo } from "./scenes/DownloadDemo";
import { Understand } from "./scenes/Understand";
import { Outro } from "./scenes/Outro";

const COMPONENTS = {
  intro: Intro,
  platforms: Platforms,
  download: DownloadDemo,
  understand: Understand,
  outro: Outro,
};

export const SiftPromo: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: colors.background, fontFamily: fonts.sans }}>
    {SCENES.map(({ id, frames }) => {
      const Scene = COMPONENTS[id];
      return (
        <Sequence key={id} from={sceneStart(id)} durationInFrames={frames} name={id}>
          <Scene />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
