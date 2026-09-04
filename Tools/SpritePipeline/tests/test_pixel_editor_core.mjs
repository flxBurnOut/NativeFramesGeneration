import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.resolve(
  currentDirectory,
  "../sprite_pipeline/static/pixel_editor_core.js",
);
const {
  alphaGeometryRgba,
  applyRgbaChanges,
  clearSelectionRgba,
  diffRgbaSummary,
  floodFillRgba,
  normalizeSelection,
  opaqueBoundsRgba,
  rasterIntegerLine,
  screenToPixel,
  threeWayMergeRgba,
  translateSelectionRgba,
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

for (let x = -4; x <= 4; x += 1) {
  for (let y = -4; y <= 4; y += 1) {
    const forward = rasterIntegerLine({ x: 0, y: 0 }, { x, y });
    const backward = rasterIntegerLine({ x, y }, { x: 0, y: 0 });
    assert.deepEqual(forward, [...backward].reverse(), "line rasterisation must be direction invariant");
    for (let index = 1; index < forward.length; index += 1) {
      assert.ok(Math.abs(forward[index].x - forward[index - 1].x) <= 1);
      assert.ok(Math.abs(forward[index].y - forward[index - 1].y) <= 1);
    }
  }
}

assert.deepEqual(
  normalizeSelection({ x: 4, y: 3 }, { x: 1, y: -2 }, 5, 4),
  { x: 1, y: 0, width: 4, height: 4 },
);

const boundsPixels = new Uint8ClampedArray(4 * 3 * 4);
boundsPixels[(1 * 4 + 2) * 4 + 3] = 255;
boundsPixels[(2 * 4 + 3) * 4 + 3] = 2;
assert.deepEqual(opaqueBoundsRgba(boundsPixels, 4, 3), { x: 2, y: 1, width: 2, height: 2 });
assert.deepEqual(opaqueBoundsRgba(boundsPixels, 4, 3, 3), { x: 2, y: 1, width: 1, height: 1 });
assert.deepEqual(
  alphaGeometryRgba(boundsPixels, 4, 3),
  {
    visible: 2,
    centroid: { x: 2.5, y: 1.5 },
    bbox: { x: 2, y: 1, width: 2, height: 2 },
  },
);

const fillPixels = new Uint8ClampedArray(3 * 3 * 4);
const wall = [12, 34, 56, 255];
for (const [x, y] of [[1, 0], [0, 1], [2, 1], [1, 2]]) {
  fillPixels.set(wall, (y * 3 + x) * 4);
}
const beforeFill = new Uint8ClampedArray(fillPixels);
const fillChanges = floodFillRgba(fillPixels, 3, 3, { x: 1, y: 1 }, [9, 8, 7, 255]);
assert.equal(fillChanges.length, 1, "diagonal pixels must not join a four-connected fill");
assert.deepEqual(Array.from(fillPixels.slice(16, 20)), [9, 8, 7, 255]);
applyRgbaChanges(fillPixels, fillChanges, "undo");
assert.deepEqual(fillPixels, beforeFill);
assert.deepEqual(floodFillRgba(fillPixels, 3, 3, { x: 1, y: 0 }, wall), []);

const selectionPixels = new Uint8ClampedArray(4 * 3 * 4);
selectionPixels.set([200, 10, 20, 255], (1 * 4 + 1) * 4);
selectionPixels.set([20, 30, 220, 255], (2 * 4 + 3) * 4);
const beforeMove = new Uint8ClampedArray(selectionPixels);
const moved = translateSelectionRgba(
  selectionPixels,
  4,
  3,
  { x: 1, y: 1, width: 1, height: 1 },
  1,
  0,
);
assert.equal(moved.blocked, false);
assert.deepEqual(moved.selection, { x: 2, y: 1, width: 1, height: 1 });
assert.deepEqual(Array.from(selectionPixels.slice((1 * 4 + 1) * 4, (1 * 4 + 1) * 4 + 4)), [0, 0, 0, 0]);
assert.deepEqual(Array.from(selectionPixels.slice((1 * 4 + 2) * 4, (1 * 4 + 2) * 4 + 4)), [200, 10, 20, 255]);
assert.deepEqual(Array.from(selectionPixels.slice((2 * 4 + 3) * 4, (2 * 4 + 3) * 4 + 4)), [20, 30, 220, 255]);
applyRgbaChanges(selectionPixels, moved.changes, "undo");
assert.deepEqual(selectionPixels, beforeMove);

const blockedBefore = new Uint8ClampedArray(selectionPixels);
const blocked = translateSelectionRgba(
  selectionPixels,
  4,
  3,
  { x: 0, y: 0, width: 2, height: 2 },
  -1,
  0,
);
assert.equal(blocked.blocked, true);
assert.deepEqual(selectionPixels, blockedBefore, "blocked moves must never crop pixels");

const cleared = clearSelectionRgba(
  selectionPixels,
  4,
  3,
  { x: 1, y: 1, width: 1, height: 1 },
);
assert.equal(cleared.length, 1);
assert.deepEqual(Array.from(selectionPixels.slice((1 * 4 + 1) * 4, (1 * 4 + 1) * 4 + 4)), [0, 0, 0, 0]);
applyRgbaChanges(selectionPixels, cleared, "undo");
assert.deepEqual(selectionPixels, blockedBefore);

selectionPixels.set([1, 2, 3, 4], 0);
selectionPixels.set([5, 6, 7, 8], (2 * 4 + 2) * 4);
assert.deepEqual(
  diffRgbaSummary(selectionPixels, blockedBefore, 4, 3),
  { count: 2, bbox: { x: 0, y: 0, width: 3, height: 3 } },
);

const mergeBase = new Uint8ClampedArray([
  0, 0, 0, 0,
  10, 10, 10, 255,
  20, 20, 20, 255,
  30, 30, 30, 255,
]);
const mergeDraft = new Uint8ClampedArray(mergeBase);
mergeDraft.set([1, 2, 3, 255], 0);
mergeDraft.set([11, 12, 13, 255], 4);
mergeDraft.set([21, 22, 23, 255], 8);
const mergeCurrent = new Uint8ClampedArray(mergeBase);
mergeCurrent.set([31, 32, 33, 255], 4);
mergeCurrent.set([21, 22, 23, 255], 8);
mergeCurrent.set([40, 40, 40, 255], 12);
const merged = threeWayMergeRgba(mergeBase, mergeDraft, mergeCurrent, 4, 1);
assert.equal(merged.userChangeCount, 3);
assert.equal(merged.recoveredCount, 2);
assert.equal(merged.conflictCount, 1);
assert.deepEqual(merged.conflictBbox, { x: 1, y: 0, width: 1, height: 1 });
assert.deepEqual(Array.from(merged.pixels), [
  1, 2, 3, 255,
  31, 32, 33, 255,
  21, 22, 23, 255,
  40, 40, 40, 255,
]);
applyRgbaChanges(merged.pixels, merged.changes, "undo");
assert.deepEqual(merged.pixels, mergeCurrent);
assert.equal(threeWayMergeRgba(new Uint8ClampedArray(3), mergeDraft, mergeCurrent, 4, 1), null);

console.log("pixel-editor-core: ok");
