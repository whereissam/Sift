export const FPS = 30;

// Scene lengths in frames. Each scene starts where the previous one ends.
export const SCENES = [
  { id: "intro", frames: 90 },
  { id: "platforms", frames: 180 },
  { id: "download", frames: 300 },
  { id: "understand", frames: 240 },
  { id: "outro", frames: 120 },
] as const;

export type SceneId = (typeof SCENES)[number]["id"];

export const DURATION = SCENES.reduce((sum, s) => sum + s.frames, 0);

export function sceneStart(id: SceneId): number {
  let start = 0;
  for (const scene of SCENES) {
    if (scene.id === id) return start;
    start += scene.frames;
  }
  throw new Error(`unknown scene: ${id}`);
}
