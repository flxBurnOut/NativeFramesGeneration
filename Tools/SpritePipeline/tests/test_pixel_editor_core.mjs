import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const modulePath = path.resolve(
  import.meta.dirname,
  "../sprite_pipeline/static/pixel_editor_core.js",
);
const {
  applyRgbaChanges,
  rasterIntegerLine,
  screenToPixel,
} = await import(pathToFileURL(modulePath));

for (const zoom of [1, 2, 4, 8, 12, 16, 24, 32]) {
  assert.deepEqual(
    screenToPixel({
      screenX: 10 + zoom * 7 + zoom * 0.999,
      screenY: 20 + zoom * 9 + zoom * 0.001,
      originX: 10,
      originY: 20,
      zoom,
      width: 128,
      height: 128,
    }),
    { x: 7, y: 9 },
  );
}
assert.equal(
  screenToPixel({
    screenX: 9.999,
    screenY: 20,
    originX: 10,
    originY: 20,
    zoom: 8,
    width: 128,
    height: 128,
  }),
  null,
);
assert.deepEqual(
  screenToPixel({
    screenX: 18,
    screenY: 28,
    originX: 10,
    originY: 20,
    zoom: 8,
    width: 128,
    height: 128,
  }),
  { x: 1, y: 1 },
);

const line = rasterIntegerLine({ x: 2, y: 3 }, { x: 17, y: 11 });
assert.deepEqual(line[0], { x: 2, y: 3 });
assert.deepEqual(line.at(-1), { x: 17, y: 11 });
for (let index = 1; index < line.length; index += 1) {
  assert.ok(Math.abs(line[index].x - line[index - 1].x) <= 1);
  assert.ok(Math.abs(line[index].y - line[index - 1].y) <= 1);
}
assert.equal(new Set(line.map(({ x, y }) => `${x},${y}`)).size, line.length);

const rgba = new Uint8ClampedArray([0, 0, 0, 0, 10, 20, 30, 255]);
const changes = [
  { offset: 0, before: [0, 0, 0, 0], after: [1, 2, 3, 255] },
  { offset: 4, before: [10, 20, 30, 255], after: [40, 50, 60, 128] },
];
applyRgbaChanges(rgba, changes, "redo");
assert.deepEqual(Array.from(rgba), [1, 2, 3, 255, 40, 50, 60, 128]);
applyRgbaChanges(rgba, changes, "undo");
assert.deepEqual(Array.from(rgba), [0, 0, 0, 0, 10, 20, 30, 255]);

console.log("pixel-editor-core: ok");
