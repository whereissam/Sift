import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadNotoSC } from "@remotion/google-fonts/NotoSansSC";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

// Colors follow frontend/src/index.css (light theme), converted from oklch.
export const colors = {
  background: "#F8F6F2",
  card: "#FFFFFF",
  foreground: "#1F1B18",
  muted: "#6B645D",
  border: "#E7E2DA",
  primary: "#C4532E",
  primarySoft: "#F6E3DA",
  success: "#2F7D4F",
};

const inter = loadInter("normal", { weights: ["400", "600", "800"], subsets: ["latin"] });
// The Chinese platform names; system fonts on a Linux renderer have no CJK.
const notoSC = loadNotoSC("normal", { weights: ["600"], subsets: ["chinese-simplified"] });
const mono = loadMono("normal", { weights: ["400"], subsets: ["latin"] });

export const fonts = {
  sans: `${inter.fontFamily}, ${notoSC.fontFamily}, sans-serif`,
  mono: `${mono.fontFamily}, monospace`,
};
