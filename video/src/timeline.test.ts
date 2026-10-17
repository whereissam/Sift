import { expect, test } from "bun:test";
import { DURATION, FPS, SCENES, sceneStart } from "./timeline";

test("scenes run back to back with no gaps or overlaps", () => {
  let expected = 0;
  for (const scene of SCENES) {
    expect(sceneStart(scene.id)).toBe(expected);
    expected += scene.frames;
  }
  expect(expected).toBe(DURATION);
});

test("the promo is about 30 seconds", () => {
  expect(DURATION / FPS).toBeGreaterThanOrEqual(25);
  expect(DURATION / FPS).toBeLessThanOrEqual(35);
});
