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
  // Canonicalise the direction before sampling. A traditional Bresenham
  // tie-break can choose a different middle pixel when the same stroke is
  // drawn backwards; a precision editor should paint the same set either way.
  const backwards = from.x > to.x || (from.x === to.x && from.y > to.y);
  const start = backwards ? to : from;
  const end = backwards ? from : to;
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const steps = Math.max(Math.abs(dx), Math.abs(dy));
  if (steps === 0) return [{ x: start.x, y: start.y }];

  const points = [];
  for (let step = 0; step <= steps; step += 1) {
    const x = Math.round(start.x + (dx * step) / steps);
    const y = Math.round(start.y + (dy * step) / steps);
    const previous = points.at(-1);
    if (!previous || previous.x !== x || previous.y !== y) points.push({ x, y });
  }
  return backwards ? points.reverse() : points;
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

export function stampSquareRgba(buffer, width, height, center, size, rgba) {
  if (
    !validRgbaBuffer(buffer, width, height) ||
    !center ||
    !Number.isFinite(center.x) ||
    !Number.isFinite(center.y) ||
    !Number.isInteger(size) ||
    size < 1 ||
    !rgba ||
    rgba.length !== 4
  ) {
    return [];
  }
  const centerX = Math.floor(center.x);
  const centerY = Math.floor(center.y);
  if (centerX < 0 || centerY < 0 || centerX >= width || centerY >= height) return [];

  const replacement = Array.from(new Uint8ClampedArray(rgba));
  const start = -Math.floor((size - 1) / 2);
  const changes = [];
  for (let offsetY = start; offsetY < start + size; offsetY += 1) {
    for (let offsetX = start; offsetX < start + size; offsetX += 1) {
      const targetX = centerX + offsetX;
      const targetY = centerY + offsetY;
      if (targetX < 0 || targetY < 0 || targetX >= width || targetY >= height) continue;
      const offset = (targetY * width + targetX) * 4;
      if (rgbaEquals(buffer, offset, replacement)) continue;
      const before = Array.from(buffer.slice(offset, offset + 4));
      changes.push({ offset, before, after: replacement });
      buffer.set(replacement, offset);
    }
  }
  return changes;
}

function rgbaEquals(left, leftOffset, right, rightOffset = 0) {
  return (
    left[leftOffset] === right[rightOffset] &&
    left[leftOffset + 1] === right[rightOffset + 1] &&
    left[leftOffset + 2] === right[rightOffset + 2] &&
    left[leftOffset + 3] === right[rightOffset + 3]
  );
}

function validRgbaBuffer(buffer, width, height) {
  return (
    buffer &&
    Number.isInteger(width) &&
    Number.isInteger(height) &&
    width > 0 &&
    height > 0 &&
    buffer.length === width * height * 4
  );
}

export function normalizeSelection(from, to, width, height) {
  if (!from || !to || width <= 0 || height <= 0) return null;
  const fromX = Math.max(0, Math.min(width - 1, Math.floor(from.x)));
  const fromY = Math.max(0, Math.min(height - 1, Math.floor(from.y)));
  const toX = Math.max(0, Math.min(width - 1, Math.floor(to.x)));
  const toY = Math.max(0, Math.min(height - 1, Math.floor(to.y)));
  const x = Math.min(fromX, toX);
  const y = Math.min(fromY, toY);
  return {
    x,
    y,
    width: Math.abs(toX - fromX) + 1,
    height: Math.abs(toY - fromY) + 1,
  };
}

export function opaqueBoundsRgba(buffer, width, height, alphaThreshold = 1) {
  if (!validRgbaBuffer(buffer, width, height)) return null;
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const alpha = buffer[(y * width + x) * 4 + 3];
      if (alpha < alphaThreshold) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (maxX < minX || maxY < minY) return null;
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
}

export function alphaGeometryRgba(buffer, width, height, alphaThreshold = 1) {
  if (!validRgbaBuffer(buffer, width, height)) return null;
  let visible = 0;
  let weightedX = 0;
  let weightedY = 0;
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const alpha = buffer[(y * width + x) * 4 + 3];
      if (alpha < alphaThreshold) continue;
      visible += 1;
      weightedX += x;
      weightedY += y;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (!visible) return null;
  return {
    visible,
    centroid: { x: weightedX / visible, y: weightedY / visible },
    bbox: { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 },
  };
}

export function floodFillRgba(buffer, width, height, start, replacement) {
  if (
    !validRgbaBuffer(buffer, width, height) ||
    !start ||
    start.x < 0 ||
    start.y < 0 ||
    start.x >= width ||
    start.y >= height ||
    !replacement ||
    replacement.length !== 4
  ) {
    return [];
  }

  const startIndex = Math.floor(start.y) * width + Math.floor(start.x);
  const startOffset = startIndex * 4;
  const target = Array.from(buffer.slice(startOffset, startOffset + 4));
  if (rgbaEquals(target, 0, replacement)) return [];

  const changes = [];
  const visited = new Uint8Array(width * height);
  const queue = [startIndex];
  visited[startIndex] = 1;
  for (let head = 0; head < queue.length; head += 1) {
    const index = queue[head];
    const offset = index * 4;
    if (!rgbaEquals(buffer, offset, target)) continue;
    const before = Array.from(buffer.slice(offset, offset + 4));
    const after = Array.from(replacement);
    changes.push({ offset, before, after });
    buffer.set(replacement, offset);

    const x = index % width;
    const y = Math.floor(index / width);
    const neighbours = [];
    if (x > 0) neighbours.push(index - 1);
    if (x + 1 < width) neighbours.push(index + 1);
    if (y > 0) neighbours.push(index - width);
    if (y + 1 < height) neighbours.push(index + width);
    for (const neighbour of neighbours) {
      if (!visited[neighbour]) {
        visited[neighbour] = 1;
        queue.push(neighbour);
      }
    }
  }
  return changes;
}

export function clearSelectionRgba(buffer, width, height, selection) {
  if (!validRgbaBuffer(buffer, width, height) || !selection) return [];
  const normalized = normalizeSelection(
    { x: selection.x, y: selection.y },
    { x: selection.x + selection.width - 1, y: selection.y + selection.height - 1 },
    width,
    height,
  );
  if (!normalized) return [];
  const changes = [];
  const transparent = [0, 0, 0, 0];
  for (let y = normalized.y; y < normalized.y + normalized.height; y += 1) {
    for (let x = normalized.x; x < normalized.x + normalized.width; x += 1) {
      const offset = (y * width + x) * 4;
      if (rgbaEquals(buffer, offset, transparent)) continue;
      const before = Array.from(buffer.slice(offset, offset + 4));
      changes.push({ offset, before, after: transparent });
      buffer.set(transparent, offset);
    }
  }
  return changes;
}

export function translateSelectionRgba(buffer, width, height, selection, dx, dy) {
  if (
    !validRgbaBuffer(buffer, width, height) ||
    !selection ||
    !Number.isInteger(dx) ||
    !Number.isInteger(dy) ||
    (dx === 0 && dy === 0)
  ) {
    return { changes: [], selection, blocked: false };
  }
  const normalized = normalizeSelection(
    { x: selection.x, y: selection.y },
    { x: selection.x + selection.width - 1, y: selection.y + selection.height - 1 },
    width,
    height,
  );
  if (!normalized) return { changes: [], selection, blocked: false };
  const destination = { ...normalized, x: normalized.x + dx, y: normalized.y + dy };
  if (
    destination.x < 0 ||
    destination.y < 0 ||
    destination.x + destination.width > width ||
    destination.y + destination.height > height
  ) {
    return { changes: [], selection: normalized, blocked: true };
  }

  const beforeBuffer = new Uint8ClampedArray(buffer);
  const afterBuffer = new Uint8ClampedArray(buffer);
  const transparent = [0, 0, 0, 0];
  for (let y = 0; y < normalized.height; y += 1) {
    for (let x = 0; x < normalized.width; x += 1) {
      const sourceOffset = ((normalized.y + y) * width + normalized.x + x) * 4;
      afterBuffer.set(transparent, sourceOffset);
    }
  }
  for (let y = 0; y < normalized.height; y += 1) {
    for (let x = 0; x < normalized.width; x += 1) {
      const sourceOffset = ((normalized.y + y) * width + normalized.x + x) * 4;
      const destinationOffset = ((destination.y + y) * width + destination.x + x) * 4;
      afterBuffer.set(beforeBuffer.slice(sourceOffset, sourceOffset + 4), destinationOffset);
    }
  }

  const changes = [];
  for (let offset = 0; offset < beforeBuffer.length; offset += 4) {
    if (rgbaEquals(beforeBuffer, offset, afterBuffer, offset)) continue;
    const before = Array.from(beforeBuffer.slice(offset, offset + 4));
    const after = Array.from(afterBuffer.slice(offset, offset + 4));
    changes.push({ offset, before, after });
    buffer.set(after, offset);
  }
  return { changes, selection: destination, blocked: false };
}

export function diffRgbaSummary(buffer, baseBuffer, width, height) {
  if (
    !validRgbaBuffer(buffer, width, height) ||
    !validRgbaBuffer(baseBuffer, width, height)
  ) {
    return { count: 0, bbox: null };
  }
  let count = 0;
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let index = 0; index < width * height; index += 1) {
    const offset = index * 4;
    if (rgbaEquals(buffer, offset, baseBuffer, offset)) continue;
    const x = index % width;
    const y = Math.floor(index / width);
    count += 1;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return {
    count,
    bbox: count
      ? { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 }
      : null,
  };
}

export function threeWayMergeRgba(baseBuffer, draftBuffer, currentBuffer, width, height) {
  if (
    !validRgbaBuffer(baseBuffer, width, height) ||
    !validRgbaBuffer(draftBuffer, width, height) ||
    !validRgbaBuffer(currentBuffer, width, height)
  ) {
    return null;
  }

  const pixels = new Uint8ClampedArray(currentBuffer);
  const changes = [];
  let userChangeCount = 0;
  let recoveredCount = 0;
  let conflictCount = 0;
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;

  for (let index = 0; index < width * height; index += 1) {
    const offset = index * 4;
    if (rgbaEquals(draftBuffer, offset, baseBuffer, offset)) continue;
    userChangeCount += 1;

    if (
      rgbaEquals(currentBuffer, offset, baseBuffer, offset) ||
      rgbaEquals(currentBuffer, offset, draftBuffer, offset)
    ) {
      recoveredCount += 1;
      if (!rgbaEquals(currentBuffer, offset, draftBuffer, offset)) {
        const before = Array.from(currentBuffer.slice(offset, offset + 4));
        const after = Array.from(draftBuffer.slice(offset, offset + 4));
        pixels.set(after, offset);
        changes.push({ offset, before, after });
      }
      continue;
    }

    const x = index % width;
    const y = Math.floor(index / width);
    conflictCount += 1;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }

  return {
    pixels,
    changes,
    userChangeCount,
    recoveredCount,
    conflictCount,
    conflictBbox: conflictCount
      ? { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 }
      : null,
  };
}
