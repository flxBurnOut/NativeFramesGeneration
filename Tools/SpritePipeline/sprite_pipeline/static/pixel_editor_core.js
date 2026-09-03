export function screenToPixel({
  screenX,
  screenY,
  originX,
  originY,
  zoom,
  width,
  height,
}) {
  if (!Number.isFinite(zoom) || zoom <= 0) return null;
  const x = Math.floor((screenX - originX) / zoom);
  const y = Math.floor((screenY - originY) / zoom);
  if (x < 0 || y < 0 || x >= width || y >= height) return null;
  return { x, y };
}

export function rasterIntegerLine(from, to) {
  const points = [];
  let x0 = from.x;
  let y0 = from.y;
  const x1 = to.x;
  const y1 = to.y;
  const dx = Math.abs(x1 - x0);
  const sx = x0 < x1 ? 1 : -1;
  const dy = -Math.abs(y1 - y0);
  const sy = y0 < y1 ? 1 : -1;
  let error = dx + dy;
  while (true) {
    points.push({ x: x0, y: y0 });
    if (x0 === x1 && y0 === y1) break;
    const doubled = 2 * error;
    if (doubled >= dy) {
      error += dy;
      x0 += sx;
    }
    if (doubled <= dx) {
      error += dx;
      y0 += sy;
    }
  }
  return points;
}

export function applyRgbaChanges(buffer, changes, direction) {
  const key = direction === "undo" ? "before" : "after";
  for (const change of changes) {
    const rgba = change[key];
    buffer[change.offset] = rgba[0];
    buffer[change.offset + 1] = rgba[1];
    buffer[change.offset + 2] = rgba[2];
    buffer[change.offset + 3] = rgba[3];
  }
}
