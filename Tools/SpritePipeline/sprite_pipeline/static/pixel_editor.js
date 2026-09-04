import {
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
} from "/pixel-editor-assets/pixel_editor_core.js?v=5";

const $ = (selector) => document.querySelector(selector);

const elements = {
  viewport: $("#viewport"),
  imageCanvas: $("#imageCanvas"),
  overlayCanvas: $("#overlayCanvas"),
  loading: $("#loading"),
  message: $("#message"),
  messageText: $("#messageText"),
  retryLoadButton: $("#retryLoadButton"),
  frameLabel: $("#frameLabel"),
  sizeLabel: $("#sizeLabel"),
  versionLabel: $("#versionLabel"),
  coordinateValue: $("#coordinateValue"),
  pixelValue: $("#pixelValue"),
  paintValue: $("#paintValue"),
  colorPreview: $("#colorPreview"),
  colorPicker: $("#colorPicker"),
  alphaInput: $("#alphaInput"),
  brushSize: $("#brushSize"),
  undoButton: $("#undoButton"),
  redoButton: $("#redoButton"),
  zoomOut: $("#zoomOut"),
  zoomOne: $("#zoomOne"),
  zoomFit: $("#zoomFit"),
  zoomIn: $("#zoomIn"),
  zoomValue: $("#zoomValue"),
  gridToggle: $("#gridToggle"),
  previousToggle: $("#previousToggle"),
  nextToggle: $("#nextToggle"),
  onionOpacity: $("#onionOpacity"),
  onionOpacityValue: $("#onionOpacityValue"),
  selectOpaque: $("#selectOpaque"),
  nudgeLeft: $("#nudgeLeft"),
  nudgeUp: $("#nudgeUp"),
  nudgeDown: $("#nudgeDown"),
  nudgeRight: $("#nudgeRight"),
  clearSelectionPixels: $("#clearSelectionPixels"),
  cancelSelection: $("#cancelSelection"),
  changedPixelValue: $("#changedPixelValue"),
  changedBoundsValue: $("#changedBoundsValue"),
  selectionValue: $("#selectionValue"),
  currentBoundsValue: $("#currentBoundsValue"),
  previousDeltaValue: $("#previousDeltaValue"),
  nextDeltaValue: $("#nextDeltaValue"),
  dirtyIndicator: $("#dirtyIndicator"),
  resetButton: $("#resetButton"),
  saveButton: $("#saveButton"),
  recovery: $("#recovery"),
  restoreDraft: $("#restoreDraft"),
  downloadDraft: $("#downloadDraft"),
  discardDraft: $("#discardDraft"),
  recoveryText: $("#recoveryText"),
};

window.__spritePixelEditorBoot?.markStarted?.();

const query = new URLSearchParams(window.location.search);
const jobId = query.get("job_id") || "";
const candidateIndex = Number.parseInt(query.get("candidate") || "", 10);
const frameIndex = Number.parseInt(query.get("frame") || "", 10);
const zoomLevels = [1, 2, 4, 8, 12, 16, 24, 32];
const maxHistory = 100;
const maxHistoryChangedPixels = 65_536;
const maxStoredDrafts = 12;
const maxStoredDraftCharacters = 3_000_000;
const draftPrefix = "sprite-pixel-draft:";
const sessionLoadTimeoutMs = 8_000;
const maxSessionLoadAttempts = 2;

function randomDraftId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
}

function initialDraftTabId() {
  try {
    const existing = window.sessionStorage.getItem("sprite-pixel-draft-tab-id");
    if (existing) return existing;
    const created = randomDraftId();
    window.sessionStorage.setItem("sprite-pixel-draft-tab-id", created);
    return created;
  } catch (_) {
    return randomDraftId();
  }
}

let draftTabId = initialDraftTabId();
const draftPageId = randomDraftId();
let draftChannel = null;

const sourceCanvas = document.createElement("canvas");
const sourceContext = sourceCanvas.getContext("2d", { alpha: true });
const previousCanvas = document.createElement("canvas");
const previousContext = previousCanvas.getContext("2d", { alpha: true });
const nextCanvas = document.createElement("canvas");
const nextContext = nextCanvas.getContext("2d", { alpha: true });
const imageContext = elements.imageCanvas.getContext("2d", { alpha: true });
const overlayContext = elements.overlayCanvas.getContext("2d", { alpha: true });

const state = {
  width: 0,
  height: 0,
  pixels: null,
  basePixels: null,
  baseSha256: "",
  manualVersions: 0,
  externalAttempts: 0,
  frameCount: 0,
  loop: false,
  alphaVisibleThreshold: 1,
  neighbors: { previous: null, next: null },
  neighborWarnings: {},
  canEdit: false,
  tool: "pencil",
  zoom: 4,
  originX: 0,
  originY: 0,
  cssWidth: 0,
  cssHeight: 0,
  dpr: 1,
  hoverPixel: null,
  pointerMode: null,
  pointerId: null,
  lastPixel: null,
  strokeBefore: null,
  panStart: null,
  selection: null,
  selectionAnchor: null,
  undoStack: [],
  redoStack: [],
  spaceDown: false,
  dirty: false,
  saving: false,
  draftCandidate: null,
  draftStorageKey: null,
  draftIsForeign: false,
  draftSavedAt: null,
  draftTimer: null,
  loaded: false,
  loadingSession: false,
};

const sessionUrl = () =>
  `/v1/jobs/${encodeURIComponent(jobId)}/candidates/${candidateIndex}/frames/${frameIndex}/pixel-edit`;
const legacyDraftKey = () => `sprite-pixel-draft:${jobId}:${candidateIndex}:${frameIndex}`;
// Every page load owns a unique key. sessionStorage can be cloned when a tab is
// duplicated, so draftTabId is useful metadata but is not safe as the key.
const draftKey = () => `${legacyDraftKey()}:${draftPageId}`;

async function claimDraftTabIdentity() {
  if (!("BroadcastChannel" in window)) return;
  let collision = false;
  draftChannel = new BroadcastChannel("sprite-pixel-draft-tabs");
  draftChannel.addEventListener("message", (event) => {
    const data = event.data || {};
    if (data.type === "probe" && data.tabId === draftTabId && data.pageId !== draftPageId) {
      draftChannel.postMessage({ type: "claimed", tabId: draftTabId, targetPageId: data.pageId });
    } else if (
      data.type === "claimed" &&
      data.tabId === draftTabId &&
      data.targetPageId === draftPageId
    ) {
      collision = true;
    }
  });
  draftChannel.postMessage({ type: "probe", tabId: draftTabId, pageId: draftPageId });
  await new Promise((resolve) => window.setTimeout(resolve, 80));
  if (!collision) return;
  draftTabId = randomDraftId();
  try {
    window.sessionStorage.setItem("sprite-pixel-draft-tab-id", draftTabId);
  } catch (_) {
    // The in-memory id still prevents this live page from sharing a draft key.
  }
}

function setMessage(text, kind = "info") {
  elements.messageText.textContent = text;
  elements.message.className = `message message--${kind}`;
}

function describeApiError(payload, fallback) {
  const message = payload?.error?.message || fallback;
  const reason = payload?.error?.details?.reason || "";
  if (reason === "frame_not_marked_for_repair" || message.includes("repair_requested")) {
    return "这帧当前不在待修补状态。请回到“播放检查”重新标记后再编辑。";
  }
  if (reason === "stale_frame_version" || message.includes("stale frame version")) {
    return "这帧已在其他窗口中更新。请刷新修补列表后重新打开，当前草稿仍保存在本机。";
  }
  if (reason === "no_pixel_changes" || message.includes("does not change any pixels")) {
    return "当前像素与保存前完全相同，不需要建立新版本。";
  }
  if (reason === "active_frame_integrity_mismatch") {
    return "当前帧文件与任务记录不一致。为防止覆盖，编辑器已经停止保存，请从外层页面重新载入。";
  }
  return message;
}

function waitMilliseconds(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function sessionLoadError(message, retryable = false) {
  const error = new Error(message);
  error.retryable = retryable;
  return error;
}

async function fetchPixelSession() {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), sessionLoadTimeoutMs);
  try {
    const response = await window.fetch(sessionUrl(), {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw sessionLoadError("服务器没有返回可读取的像素数据。", response.status >= 500);
    }
    if (!response.ok || !payload.ok) {
      throw sessionLoadError(
        describeApiError(payload, `读取失败（HTTP ${response.status}）`),
        response.status >= 500,
      );
    }
    return payload.data.session;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw sessionLoadError("读取像素超过 8 秒，已停止等待。", true);
    }
    if (error instanceof TypeError) {
      throw sessionLoadError("无法连接本地像素接口。", true);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function base64ToBytes(encoded) {
  const binary = window.atob(encoded);
  const bytes = new Uint8ClampedArray(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x4000;
  for (let start = 0; start < bytes.length; start += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(start, start + chunkSize));
  }
  return window.btoa(binary);
}

function pixelsEqual(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

function pixelOffset(x, y) {
  return (y * state.width + x) * 4;
}

function getPixel(x, y) {
  const offset = pixelOffset(x, y);
  return [
    state.pixels[offset],
    state.pixels[offset + 1],
    state.pixels[offset + 2],
    state.pixels[offset + 3],
  ];
}

function setPixelAtOffset(offset, rgba) {
  state.pixels[offset] = rgba[0];
  state.pixels[offset + 1] = rgba[1];
  state.pixels[offset + 2] = rgba[2];
  state.pixels[offset + 3] = rgba[3];
}

function hexToRgb(hex) {
  const normalized = hex.replace("#", "");
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16),
  ];
}

function rgbToHex(r, g, b) {
  return `#${[r, g, b].map((value) => value.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

function paintColor() {
  const [r, g, b] = hexToRgb(elements.colorPicker.value);
  const alpha = Math.max(0, Math.min(255, Number.parseInt(elements.alphaInput.value || "255", 10)));
  return [r, g, b, alpha];
}

function updatePaintColor() {
  const [r, g, b, a] = paintColor();
  elements.alphaInput.value = String(a);
  elements.paintValue.textContent = `${rgbToHex(r, g, b)} · A ${a}`;
  elements.colorPreview.style.setProperty(
    "--paint-color",
    `rgba(${r}, ${g}, ${b}, ${a / 255})`,
  );
}

function resizeDisplayCanvases() {
  // Use the actual overlay content box for both rendering and pointer math.
  // Reading the bordered parent would introduce a subtle scale mismatch at
  // the right/bottom edge and can select the neighbouring source pixel.
  const rect = elements.overlayCanvas.getBoundingClientRect();
  state.cssWidth = Math.max(1, rect.width);
  state.cssHeight = Math.max(1, rect.height);
  state.dpr = Math.max(1, window.devicePixelRatio || 1);
  const backingWidth = Math.max(1, Math.round(state.cssWidth * state.dpr));
  const backingHeight = Math.max(1, Math.round(state.cssHeight * state.dpr));
  for (const canvas of [elements.imageCanvas, elements.overlayCanvas]) {
    if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
      canvas.width = backingWidth;
      canvas.height = backingHeight;
    }
  }
}

function fitView() {
  if (!state.loaded) return;
  resizeDisplayCanvases();
  const availableWidth = Math.max(1, state.cssWidth - 30);
  const availableHeight = Math.max(1, state.cssHeight - 30);
  const fit = zoomLevels.filter(
    (level) => state.width * level <= availableWidth && state.height * level <= availableHeight,
  );
  state.zoom = fit.length ? fit[fit.length - 1] : 1;
  state.originX = Math.round((state.cssWidth - state.width * state.zoom) / 2);
  state.originY = Math.round((state.cssHeight - state.height * state.zoom) / 2);
  render();
}

function refreshSourceCanvas() {
  if (!state.loaded) return;
  if (sourceCanvas.width !== state.width || sourceCanvas.height !== state.height) {
    sourceCanvas.width = state.width;
    sourceCanvas.height = state.height;
  }
  sourceContext.putImageData(
    new ImageData(new Uint8ClampedArray(state.pixels), state.width, state.height),
    0,
    0,
  );
}

function refreshOnionCanvas(canvas, context, pixels, tint) {
  if (!pixels) {
    canvas.width = 0;
    canvas.height = 0;
    return;
  }
  if (canvas.width !== state.width || canvas.height !== state.height) {
    canvas.width = state.width;
    canvas.height = state.height;
  }
  const tinted = new Uint8ClampedArray(pixels.length);
  for (let offset = 0; offset < pixels.length; offset += 4) {
    tinted[offset] = tint[0];
    tinted[offset + 1] = tint[1];
    tinted[offset + 2] = tint[2];
    tinted[offset + 3] = pixels[offset + 3];
  }
  context.putImageData(new ImageData(tinted, state.width, state.height), 0, 0);
}

function refreshOnionCanvases() {
  refreshOnionCanvas(
    previousCanvas,
    previousContext,
    state.neighbors.previous?.pixels || null,
    [255, 76, 163],
  );
  refreshOnionCanvas(
    nextCanvas,
    nextContext,
    state.neighbors.next?.pixels || null,
    [63, 220, 255],
  );
}

function crisp(value) {
  return (Math.round(value * state.dpr) + 0.5) / state.dpr;
}

function renderImage() {
  resizeDisplayCanvases();
  imageContext.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  imageContext.clearRect(0, 0, state.cssWidth, state.cssHeight);
  imageContext.imageSmoothingEnabled = false;
  refreshSourceCanvas();
  const opacity = Number.parseInt(elements.onionOpacity.value, 10) / 100;
  imageContext.globalAlpha = opacity;
  if (elements.previousToggle.checked && state.neighbors.previous) {
    imageContext.drawImage(
      previousCanvas,
      state.originX,
      state.originY,
      state.width * state.zoom,
      state.height * state.zoom,
    );
  }
  if (elements.nextToggle.checked && state.neighbors.next) {
    imageContext.drawImage(
      nextCanvas,
      state.originX,
      state.originY,
      state.width * state.zoom,
      state.height * state.zoom,
    );
  }
  imageContext.globalAlpha = 1;
  imageContext.drawImage(
    sourceCanvas,
    state.originX,
    state.originY,
    state.width * state.zoom,
    state.height * state.zoom,
  );
}

function renderOverlay() {
  resizeDisplayCanvases();
  overlayContext.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  overlayContext.clearRect(0, 0, state.cssWidth, state.cssHeight);

  const left = state.originX;
  const top = state.originY;
  const right = left + state.width * state.zoom;
  const bottom = top + state.height * state.zoom;
  overlayContext.lineWidth = 1 / state.dpr;
  overlayContext.strokeStyle = "rgba(225, 218, 255, 0.72)";
  overlayContext.strokeRect(crisp(left), crisp(top), right - left, bottom - top);

  if (elements.gridToggle.checked && state.zoom >= 8) {
    overlayContext.beginPath();
    for (let x = 0; x <= state.width; x += 1) {
      const lineX = crisp(left + x * state.zoom);
      overlayContext.moveTo(lineX, top);
      overlayContext.lineTo(lineX, bottom);
    }
    for (let y = 0; y <= state.height; y += 1) {
      const lineY = crisp(top + y * state.zoom);
      overlayContext.moveTo(left, lineY);
      overlayContext.lineTo(right, lineY);
    }
    overlayContext.strokeStyle = "rgba(177, 166, 214, 0.25)";
    overlayContext.stroke();

    overlayContext.beginPath();
    for (let x = 0; x <= state.width; x += 8) {
      const lineX = crisp(left + x * state.zoom);
      overlayContext.moveTo(lineX, top);
      overlayContext.lineTo(lineX, bottom);
    }
    for (let y = 0; y <= state.height; y += 8) {
      const lineY = crisp(top + y * state.zoom);
      overlayContext.moveTo(left, lineY);
      overlayContext.lineTo(right, lineY);
    }
    overlayContext.lineWidth = Math.max(1 / state.dpr, 1.5 / state.dpr);
    overlayContext.strokeStyle = "rgba(207, 196, 255, 0.48)";
    overlayContext.stroke();
  }

  if (state.hoverPixel && state.tool !== "select") {
    const { x, y } = state.hoverPixel;
    const usesBrush = state.tool === "pencil" || state.tool === "eraser";
    const brushSize = usesBrush ? Number.parseInt(elements.brushSize.value, 10) : 1;
    const brushStart = usesBrush ? -Math.floor((brushSize - 1) / 2) : 0;
    const startX = Math.max(0, x + brushStart);
    const startY = Math.max(0, y + brushStart);
    const endX = Math.min(state.width, x + brushStart + brushSize);
    const endY = Math.min(state.height, y + brushStart + brushSize);
    const hoverX = left + startX * state.zoom;
    const hoverY = top + startY * state.zoom;
    const hoverWidth = (endX - startX) * state.zoom;
    const hoverHeight = (endY - startY) * state.zoom;
    overlayContext.fillStyle = "rgba(99, 223, 201, 0.19)";
    overlayContext.fillRect(hoverX, hoverY, hoverWidth, hoverHeight);
    overlayContext.lineWidth = Math.max(1 / state.dpr, 2 / state.dpr);
    overlayContext.strokeStyle = "rgba(99, 223, 201, 0.95)";
    overlayContext.strokeRect(
      crisp(hoverX),
      crisp(hoverY),
      hoverWidth,
      hoverHeight,
    );
  }

  if (state.selection) {
    const selectionX = left + state.selection.x * state.zoom;
    const selectionY = top + state.selection.y * state.zoom;
    const selectionWidth = state.selection.width * state.zoom;
    const selectionHeight = state.selection.height * state.zoom;
    overlayContext.save();
    overlayContext.fillStyle = "rgba(255, 214, 107, 0.08)";
    overlayContext.fillRect(selectionX, selectionY, selectionWidth, selectionHeight);
    overlayContext.setLineDash([6, 4]);
    overlayContext.lineDashOffset = -0.5;
    overlayContext.lineWidth = Math.max(1 / state.dpr, 2 / state.dpr);
    overlayContext.strokeStyle = "rgba(255, 214, 107, 0.98)";
    overlayContext.strokeRect(
      crisp(selectionX),
      crisp(selectionY),
      selectionWidth,
      selectionHeight,
    );
    overlayContext.restore();
  }
}

function render() {
  if (!state.loaded) return;
  renderImage();
  renderOverlay();
  elements.zoomValue.textContent = `${state.zoom}×${state.zoom < 8 && elements.gridToggle.checked ? " · 8×显示网格" : ""}`;
}

function eventPosition(event) {
  const rect = elements.overlayCanvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function eventPixel(event) {
  const position = eventPosition(event);
  return screenToPixel({
    screenX: position.x,
    screenY: position.y,
    originX: state.originX,
    originY: state.originY,
    zoom: state.zoom,
    width: state.width,
    height: state.height,
  });
}

function clampedEventPixel(event) {
  const position = eventPosition(event);
  const x = Math.floor((position.x - state.originX) / state.zoom);
  const y = Math.floor((position.y - state.originY) / state.zoom);
  return {
    x: Math.max(0, Math.min(state.width - 1, x)),
    y: Math.max(0, Math.min(state.height - 1, y)),
  };
}

function updatePixelInspector(pixel) {
  state.hoverPixel = pixel;
  if (!pixel || !state.loaded) {
    elements.coordinateValue.textContent = "—";
    elements.pixelValue.textContent = "—";
  } else {
    const [r, g, b, a] = getPixel(pixel.x, pixel.y);
    elements.coordinateValue.textContent = `(${pixel.x}, ${pixel.y})`;
    elements.pixelValue.textContent = a === 0
      ? "透明 · " + r + ", " + g + ", " + b + ", 0"
      : r + ", " + g + ", " + b + ", " + a;
  }
  renderOverlay();
}

function activeRgba() {
  return state.tool === "eraser" ? [0, 0, 0, 0] : paintColor();
}

function recordBefore(offset) {
  if (!state.strokeBefore.has(offset)) {
    state.strokeBefore.set(offset, Array.from(state.pixels.slice(offset, offset + 4)));
  }
}

function stampPixel(x, y) {
  const size = Number.parseInt(elements.brushSize.value, 10);
  const start = -Math.floor((size - 1) / 2);
  const rgba = activeRgba();
  for (let offsetY = start; offsetY < start + size; offsetY += 1) {
    for (let offsetX = start; offsetX < start + size; offsetX += 1) {
      const targetX = x + offsetX;
      const targetY = y + offsetY;
      if (targetX < 0 || targetY < 0 || targetX >= state.width || targetY >= state.height) continue;
      const offset = pixelOffset(targetX, targetY);
      const current = state.pixels.slice(offset, offset + 4);
      if (current.every((value, index) => value === rgba[index])) continue;
      recordBefore(offset);
      setPixelAtOffset(offset, rgba);
    }
  }
}

function drawIntegerLine(from, to) {
  for (const point of rasterIntegerLine(from, to)) {
    stampPixel(point.x, point.y);
  }
}

function pickColor(pixel) {
  const [r, g, b, a] = getPixel(pixel.x, pixel.y);
  elements.colorPicker.value = rgbToHex(r, g, b);
  elements.alphaInput.value = String(a);
  updatePaintColor();
  setMessage(
    "已从像素 (" + pixel.x + ", " + pixel.y + ") 读取 " +
      (a === 0 ? "透明像素" : "RGBA(" + r + ", " + g + ", " + b + ", " + a + ")") +
      "。",
    "ok",
  );
}

function beginStroke(pixel) {
  state.strokeBefore = new Map();
  state.lastPixel = pixel;
  stampPixel(pixel.x, pixel.y);
  render();
}

function continueStroke(pixel) {
  if (!state.lastPixel) {
    state.lastPixel = pixel;
    stampPixel(pixel.x, pixel.y);
  } else if (pixel.x !== state.lastPixel.x || pixel.y !== state.lastPixel.y) {
    drawIntegerLine(state.lastPixel, pixel);
    state.lastPixel = pixel;
  }
  render();
}

function finishStroke() {
  if (!state.strokeBefore) return;
  const changes = [];
  for (const [offset, before] of state.strokeBefore.entries()) {
    const after = Array.from(state.pixels.slice(offset, offset + 4));
    if (!before.every((value, index) => value === after[index])) {
      changes.push({ offset, before, after });
    }
  }
  state.strokeBefore = null;
  state.lastPixel = null;
  if (changes.length) pushHistory({ changes, label: "笔画" });
}

function copySelection(selection) {
  return selection ? { ...selection } : null;
}

function pushHistory(command) {
  if (!command.changes.length) return;
  state.undoStack.push(command);
  let changedPixels = state.undoStack.reduce((total, item) => total + item.changes.length, 0);
  while (
    state.undoStack.length > 1 &&
    (state.undoStack.length > maxHistory || changedPixels > maxHistoryChangedPixels)
  ) {
    changedPixels -= state.undoStack[0].changes.length;
    state.undoStack.shift();
  }
  state.redoStack = [];
  updateDirtyState();
  render();
}

function applyHistory(command, direction) {
  applyRgbaChanges(state.pixels, command.changes, direction);
  if (direction === "undo" && Object.hasOwn(command, "selectionBefore")) {
    state.selection = copySelection(command.selectionBefore);
  } else if (direction === "redo" && Object.hasOwn(command, "selectionAfter")) {
    state.selection = copySelection(command.selectionAfter);
  }
  updateDirtyState();
  render();
}

function undo() {
  if (state.saving) return;
  const command = state.undoStack.pop();
  if (!command) return;
  applyHistory(command, "undo");
  state.redoStack.push(command);
  updateDirtyState();
}

function redo() {
  if (state.saving) return;
  const command = state.redoStack.pop();
  if (!command) return;
  applyHistory(command, "redo");
  state.undoStack.push(command);
  let changedPixels = state.undoStack.reduce((total, item) => total + item.changes.length, 0);
  while (
    state.undoStack.length > 1 &&
    (state.undoStack.length > maxHistory || changedPixels > maxHistoryChangedPixels)
  ) {
    changedPixels -= state.undoStack[0].changes.length;
    state.undoStack.shift();
  }
  updateDirtyState();
}

function updateSelectionControls() {
  const selection = state.selection;
  const editable = Boolean(
    selection && state.canEdit && !state.saving && !state.draftCandidate
  );
  elements.selectOpaque.disabled = !state.loaded || state.saving;
  elements.cancelSelection.disabled = !selection || state.saving;
  elements.clearSelectionPixels.disabled = !editable;
  elements.nudgeLeft.disabled = !editable || selection.x <= 0;
  elements.nudgeUp.disabled = !editable || selection.y <= 0;
  elements.nudgeRight.disabled = !editable || selection.x + selection.width >= state.width;
  elements.nudgeDown.disabled = !editable || selection.y + selection.height >= state.height;
  elements.selectionValue.textContent = selection
    ? "(" + selection.x + ", " + selection.y + ") · " + selection.width + "×" + selection.height
    : "—";
}

function selectVisiblePixels() {
  if (!state.loaded || state.saving) return;
  const selection = opaqueBoundsRgba(
    state.pixels,
    state.width,
    state.height,
    state.alphaVisibleThreshold,
  );
  if (!selection) {
    setMessage("当前帧没有可见像素，无法建立角色范围。", "error");
    return;
  }
  state.selection = selection;
  selectTool("select");
  updateSelectionControls();
  renderOverlay();
  setMessage(
    "已框选可见角色范围 " + selection.width + "×" + selection.height + "。可用方向键逐像素调整位置。",
    "info",
  );
}

function cancelSelection() {
  if (state.saving) return;
  state.selection = null;
  state.selectionAnchor = null;
  updateSelectionControls();
  renderOverlay();
}

function moveSelection(dx, dy) {
  if (!state.selection || !state.canEdit || state.saving || state.draftCandidate) return;
  const beforeSelection = copySelection(state.selection);
  const result = translateSelectionRgba(
    state.pixels,
    state.width,
    state.height,
    state.selection,
    dx,
    dy,
  );
  if (result.blocked) {
    setMessage("这次移动会越过固定帧外框，已停止；没有任何像素被裁掉。", "error");
    return;
  }
  state.selection = copySelection(result.selection);
  if (result.changes.length) {
    pushHistory({
      changes: result.changes,
      label: "移动选区",
      selectionBefore: beforeSelection,
      selectionAfter: copySelection(state.selection),
    });
    setMessage("选区已移动 (" + dx + ", " + dy + ") 像素。", "info");
  } else {
    updateSelectionControls();
    renderOverlay();
  }
}

function clearSelectedPixels() {
  if (!state.selection || !state.canEdit || state.saving || state.draftCandidate) return;
  const changes = clearSelectionRgba(
    state.pixels,
    state.width,
    state.height,
    state.selection,
  );
  if (!changes.length) {
    setMessage("选区内已经完全透明，没有需要清除的像素。", "info");
    return;
  }
  pushHistory({ changes, label: "清空选区" });
  setMessage("已把选区内 " + changes.length + " 个像素清为透明黑色，可撤销。", "info");
}

function fillPixel(pixel) {
  if (!state.canEdit || state.saving) return;
  const changes = floodFillRgba(
    state.pixels,
    state.width,
    state.height,
    pixel,
    activeRgba(),
  );
  if (!changes.length) {
    setMessage("目标连通区域已经是当前 RGBA 颜色，没有发生修改。", "info");
    return;
  }
  pushHistory({ changes, label: "精确填充" });
  setMessage("已精确填充 " + changes.length + " 个四向连通像素，可撤销。", "info");
}

function signed(value) {
  const rounded = Math.abs(value) < 0.05 ? 0 : value;
  return (rounded > 0 ? "+" : "") + rounded.toFixed(1);
}

function movementLabel(from, to) {
  if (!from || !to) return "—";
  return "dx " + signed(to.centroid.x - from.centroid.x) +
    " · dy " + signed(to.centroid.y - from.centroid.y);
}

function updateContinuityStats() {
  const current = alphaGeometryRgba(
    state.pixels,
    state.width,
    state.height,
    state.alphaVisibleThreshold,
  );
  const previous = state.neighbors.previous
    ? alphaGeometryRgba(
      state.neighbors.previous.pixels,
      state.width,
      state.height,
      state.alphaVisibleThreshold,
    )
    : null;
  const next = state.neighbors.next
    ? alphaGeometryRgba(
      state.neighbors.next.pixels,
      state.width,
      state.height,
      state.alphaVisibleThreshold,
    )
    : null;
  elements.currentBoundsValue.textContent = current
    ? "(" + current.bbox.x + ", " + current.bbox.y + ") · " +
      current.bbox.width + "×" + current.bbox.height
    : "无可见像素";
  elements.previousDeltaValue.textContent = movementLabel(previous, current);
  elements.nextDeltaValue.textContent = movementLabel(current, next);
}

function pruneStoredDrafts(currentKey = "", reservedCharacters = 0) {
  const drafts = [];
  const keys = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    keys.push(window.localStorage.key(index));
  }
  for (const key of keys) {
    if (!key || !key.startsWith(draftPrefix)) continue;
    const serialized = window.localStorage.getItem(key);
    if (!serialized) continue;
    let savedAt = 0;
    try {
      savedAt = Date.parse(JSON.parse(serialized).saved_at || "") || 0;
    } catch (_) {
      window.localStorage.removeItem(key);
      continue;
    }
    drafts.push({ key, serialized, savedAt });
  }
  drafts.sort((left, right) => {
    if (left.key === currentKey) return -1;
    if (right.key === currentKey) return 1;
    return right.savedAt - left.savedAt;
  });
  let kept = currentKey ? 1 : 0;
  let characters = reservedCharacters;
  for (const draft of drafts) {
    const isCurrent = draft.key === currentKey;
    if (isCurrent) continue;
    const fits = kept < maxStoredDrafts && characters + draft.serialized.length <= maxStoredDraftCharacters;
    if (fits) {
      kept += 1;
      characters += draft.serialized.length;
    } else {
      window.localStorage.removeItem(draft.key);
    }
  }
}

function storeDraftWithPruning(key, serialized) {
  pruneStoredDrafts(key, serialized.length);
  try {
    window.localStorage.setItem(key, serialized);
    pruneStoredDrafts();
    return;
  } catch (firstError) {
    const older = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const candidateKey = window.localStorage.key(index);
      if (!candidateKey || candidateKey === key || !candidateKey.startsWith(draftPrefix)) continue;
      let savedAt = 0;
      try {
        savedAt = Date.parse(JSON.parse(window.localStorage.getItem(candidateKey) || "{}").saved_at || "") || 0;
      } catch (_) {
        savedAt = 0;
      }
      older.push({ key: candidateKey, savedAt });
    }
    older.sort((left, right) => left.savedAt - right.savedAt);
    for (const draft of older) {
      window.localStorage.removeItem(draft.key);
      try {
        window.localStorage.setItem(key, serialized);
        return;
      } catch (_) {
        // Continue freeing only this editor's oldest drafts.
      }
    }
    throw firstError;
  }
}

function scheduleDraftSave() {
  window.clearTimeout(state.draftTimer);
  if (state.draftCandidate) return;
  if (!state.dirty) {
    try {
      window.localStorage.removeItem(draftKey());
    } catch (_) {
      // Draft recovery is best-effort; editing remains fully functional.
    }
    return;
  }
  state.draftTimer = window.setTimeout(persistDraftNow, 650);
}

function persistDraftNow() {
  if (!state.loaded || !state.dirty || state.draftCandidate) return false;
  try {
    const key = draftKey();
    state.draftStorageKey = key;
    const serialized = JSON.stringify({
      schema_version: 2,
      base_sha256: state.baseSha256,
      tab_id: draftTabId,
      width: state.width,
      height: state.height,
      base_rgba_base64: bytesToBase64(state.basePixels),
      rgba_base64: bytesToBase64(state.pixels),
      saved_at: new Date().toISOString(),
    });
    storeDraftWithPruning(key, serialized);
    return true;
  } catch (_) {
    setMessage("像素修改仍在当前页面中，但浏览器无法保存恢复草稿。请尽快正式保存。", "error");
    return false;
  }
}

function updateDirtyState() {
  const summary = diffRgbaSummary(
    state.pixels,
    state.basePixels,
    state.width,
    state.height,
  );
  state.dirty = summary.count > 0;
  elements.undoButton.disabled = state.undoStack.length === 0 || state.saving;
  elements.redoButton.disabled = state.redoStack.length === 0 || state.saving;
  elements.resetButton.disabled = !state.dirty || state.saving;
  elements.saveButton.disabled = !state.dirty || !state.canEdit || state.saving || Boolean(state.draftCandidate);
  elements.dirtyIndicator.textContent = state.dirty
    ? "有 " + summary.count + " 个未保存像素修改"
    : "尚未修改";
  elements.dirtyIndicator.classList.toggle("is-dirty", state.dirty);
  elements.changedPixelValue.textContent = String(summary.count);
  elements.changedBoundsValue.textContent = summary.bbox
    ? "(" + summary.bbox.x + ", " + summary.bbox.y + ") · " + summary.bbox.width + "×" + summary.bbox.height
    : "—";
  elements.viewport.setAttribute("aria-busy", state.saving ? "true" : "false");
  for (const button of document.querySelectorAll("[data-tool]")) {
    const modifying = ["pencil", "eraser", "fill"].includes(button.dataset.tool);
    button.disabled = modifying && (!state.canEdit || state.saving || Boolean(state.draftCandidate));
  }
  elements.brushSize.disabled = !state.canEdit || state.saving;
  elements.colorPicker.disabled = !state.canEdit || state.saving;
  elements.alphaInput.disabled = !state.canEdit || state.saving;
  updateContinuityStats();
  updateSelectionControls();
  scheduleDraftSave();
}

function resetDraft() {
  if (!state.dirty || state.saving) return;
  if (!window.confirm("放弃当前所有未保存像素修改，并恢复到打开时的版本？")) return;
  state.pixels.set(state.basePixels);
  state.undoStack = [];
  state.redoStack = [];
  updateDirtyState();
  render();
  setMessage("本次未保存修改已放弃，当前画布恢复到打开时的版本。", "info");
}

function selectTool(tool) {
  state.tool = tool;
  for (const button of document.querySelectorAll("[data-tool]")) {
    const selected = button.dataset.tool === tool;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }
  elements.viewport.classList.toggle("is-eyedropper", tool === "eyedropper");
  elements.viewport.classList.toggle("is-fill", tool === "fill");
  elements.viewport.classList.toggle("is-selection", tool === "select");
  if (state.loaded) renderOverlay();
}

function setZoom(nextZoom, anchor = null) {
  if (!state.loaded || nextZoom === state.zoom) return;
  const point = anchor || { x: state.cssWidth / 2, y: state.cssHeight / 2 };
  const worldX = (point.x - state.originX) / state.zoom;
  const worldY = (point.y - state.originY) / state.zoom;
  state.zoom = nextZoom;
  state.originX = Math.round(point.x - worldX * state.zoom);
  state.originY = Math.round(point.y - worldY * state.zoom);
  render();
}

function changeZoom(direction, anchor = null) {
  const currentIndex = zoomLevels.indexOf(state.zoom);
  const index = Math.max(0, Math.min(zoomLevels.length - 1, currentIndex + direction));
  setZoom(zoomLevels[index], anchor);
}

function restoreDraft() {
  const draft = state.draftCandidate;
  if (!draft) return;
  let restored = base64ToBytes(draft.rgba_base64);
  if (restored.length !== state.pixels.length) {
    discardDraft();
    setMessage("草稿尺寸不正确，已忽略。", "error");
    return;
  }
  let changes = [];
  let recoveryMessage = "";
  if (draft.stale && draft.merge) {
    if (draft.merge.conflictCount > 0) downloadDraft();
    restored = draft.merge.pixels;
    changes = draft.merge.changes;
    recoveryMessage =
      "已安全合并 " + draft.merge.recoveredCount + " 个草稿像素；" +
      draft.merge.conflictCount + " 个与新版本冲突的像素保留服务器内容。" +
      (draft.merge.conflictCount > 0 ? "系统已发起完整旧草稿的精确备份下载。" : "");
  } else if (draft.stale) {
    if (!window.confirm(
      "这是旧格式草稿，无法逐像素判断双窗口冲突。继续只会把它载入画布预览，不会自动保存；确定继续吗？",
    )) return;
    downloadDraft();
    recoveryMessage = "旧草稿已载入画布，并已发起精确备份下载；请逐像素检查后再决定是否保存。";
  }
  if (!(draft.stale && draft.merge)) {
    for (let offset = 0; offset < restored.length; offset += 4) {
      const before = Array.from(state.pixels.slice(offset, offset + 4));
      const after = Array.from(restored.slice(offset, offset + 4));
      if (!before.every((value, index) => value === after[index])) {
        changes.push({ offset, before, after });
      }
    }
  }
  state.pixels.set(restored);
  state.undoStack = changes.length ? [{ changes, label: "恢复草稿" }] : [];
  state.redoStack = [];
  const recoveredKey = state.draftStorageKey;
  const recoveredForeign = state.draftIsForeign;
  const recoveredSavedAt = state.draftSavedAt;
  state.draftCandidate = null;
  state.draftStorageKey = null;
  state.draftIsForeign = false;
  state.draftSavedAt = null;
  elements.recovery.hidden = true;
  if (recoveredKey && !recoveredForeign) {
    try {
      window.localStorage.removeItem(recoveredKey);
    } catch (_) {
      // The restored pixels remain in memory and can still be formally saved.
    }
  }
  if (recoveredKey && recoveredForeign) ignoreForeignDraft(recoveredKey, recoveredSavedAt);
  updateDirtyState();
  render();
  setMessage(
    recoveryMessage || "已恢复草稿，其中包含 " + changes.length + " 个与当前版本不同的像素。",
    draft.stale && draft.merge?.conflictCount ? "info" : "ok",
  );
}

function downloadDraft() {
  const draft = state.draftCandidate;
  if (!draft) return;
  const backup = {
    schema_version: draft.schema_version || 1,
    kind: "sprite-pipeline-rgba-draft",
    job_id: jobId,
    candidate_index: candidateIndex,
    frame_index: frameIndex,
    base_sha256: draft.base_sha256,
    width: draft.width,
    height: draft.height,
    base_rgba_base64: draft.base_rgba_base64 || null,
    rgba_base64: draft.rgba_base64,
    saved_at: draft.saved_at || null,
    exported_at: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "sprite-draft-" + jobId + "-c" + candidateIndex + "-f" + frameIndex + ".rgba.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function discardDraft() {
  const key = state.draftStorageKey || draftKey();
  const preserveForeignDraft = state.draftIsForeign;
  const savedAt = state.draftSavedAt;
  state.draftCandidate = null;
  state.draftStorageKey = null;
  state.draftIsForeign = false;
  state.draftSavedAt = null;
  elements.recovery.hidden = true;
  try {
    if (!preserveForeignDraft) window.localStorage.removeItem(key);
  } catch (_) {
    // Nothing else is required when storage is unavailable.
  }
  if (preserveForeignDraft) ignoreForeignDraft(key, savedAt);
  if (state.loaded) updateDirtyState();
}

function ignoredForeignDraftSignatures() {
  try {
    const parsed = JSON.parse(
      window.sessionStorage.getItem("sprite-pixel-ignored-foreign-drafts") || "[]",
    );
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch (_) {
    return new Set();
  }
}

function foreignDraftSignature(key, savedAt) {
  return key + "|" + (savedAt || "");
}

function ignoreForeignDraft(key, savedAt) {
  if (!key) return;
  try {
    const signatures = Array.from(ignoredForeignDraftSignatures());
    signatures.push(foreignDraftSignature(key, savedAt));
    window.sessionStorage.setItem(
      "sprite-pixel-ignored-foreign-drafts",
      JSON.stringify(signatures.slice(-50)),
    );
  } catch (_) {
    // Ignoring is a convenience only; the foreign recovery data stays safe.
  }
}

async function saveVersion() {
  if (!state.dirty || !state.canEdit || state.saving) return;
  if (state.pointerMode === "stroke" && state.strokeBefore) finishStroke();
  if (state.pointerMode === "stroke") {
    const activePointerId = state.pointerId;
    state.pointerMode = null;
    state.pointerId = null;
    state.lastPixel = null;
    if (
      activePointerId !== null &&
      elements.overlayCanvas.hasPointerCapture(activePointerId)
    ) {
      elements.overlayCanvas.releasePointerCapture(activePointerId);
    }
  }
  const submittedPixels = new Uint8ClampedArray(state.pixels);
  state.saving = true;
  updateDirtyState();
  setMessage("正在无损编码并核对每一个 RGBA 像素，随后会重新运行序列检查……", "info");
  try {
    const response = await window.fetch(sessionUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        width: state.width,
        height: state.height,
        rgba_base64: bytesToBase64(submittedPixels),
        base_sha256: state.baseSha256,
        reviewer: "web_pixel_editor",
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(describeApiError(payload, `保存失败（HTTP ${response.status}）`));
    }
    const edit = payload.data.edit;
    state.baseSha256 = edit.sha256;
    state.manualVersions = edit.manual_edit_versions;
    state.basePixels = submittedPixels;
    state.undoStack = [];
    state.redoStack = [];
    state.canEdit = false;
    discardDraft();
    elements.versionLabel.textContent = `手工版本 v${state.manualVersions}`;
    const qa = edit.qa || {};
    if (qa.ok === false) {
      setMessage(
        "手工修补版本已安全保存，但自动复查没有完成。外层页面会刷新并保留该版本，可在那里重新运行检查。",
        "error",
      );
    } else if ((qa.hard_failure_count || 0) > 0 || (qa.warning_count || 0) > 0) {
      setMessage(
        "手工修补版本已安全保存。自动复查仍发现 " +
          (qa.hard_failure_count || 0) +
          " 个阻止问题和 " +
          (qa.warning_count || 0) +
          " 个提醒；请回到播放检查继续确认。",
        "info",
      );
    } else {
      setMessage(
        "手工修补版本已安全保存，RGBA 往返校验和自动复查均已完成。外层页面正在刷新。",
        "ok",
      );
    }
    window.parent.postMessage(
      {
        type: "sprite-pixel-editor-saved",
        jobId,
        candidateIndex,
        frameIndex,
        manualVersion: state.manualVersions,
        qa,
      },
      window.location.origin,
    );
  } catch (error) {
    setMessage(error instanceof Error ? error.message : "保存像素版本失败。", "error");
  } finally {
    state.saving = false;
    updateDirtyState();
  }
}

function loadDraftCandidate() {
  try {
    let key = draftKey();
    let serialized = window.localStorage.getItem(key);
    let foreign = false;
    if (!serialized) {
      key = legacyDraftKey();
      serialized = window.localStorage.getItem(key);
    }
    if (!serialized) {
      const framePrefix = legacyDraftKey() + ":";
      const matches = [];
      const ignored = ignoredForeignDraftSignatures();
      for (let index = 0; index < window.localStorage.length; index += 1) {
        const candidateKey = window.localStorage.key(index);
        if (!candidateKey || candidateKey === draftKey() || !candidateKey.startsWith(framePrefix)) continue;
        const candidateSerialized = window.localStorage.getItem(candidateKey);
        if (!candidateSerialized) continue;
        let savedAt = 0;
        try {
          savedAt = Date.parse(JSON.parse(candidateSerialized).saved_at || "") || 0;
        } catch (_) {
          continue;
        }
        const draftSavedAt = JSON.parse(candidateSerialized).saved_at || "";
        if (ignored.has(foreignDraftSignature(candidateKey, draftSavedAt))) continue;
        matches.push({ key: candidateKey, serialized: candidateSerialized, savedAt });
      }
      matches.sort((left, right) => right.savedAt - left.savedAt);
      if (matches.length) {
        key = matches[0].key;
        serialized = matches[0].serialized;
        foreign = true;
      }
    }
    if (!serialized) return;
    const draft = JSON.parse(serialized);
    if (
      draft.width !== state.width ||
      draft.height !== state.height ||
      typeof draft.rgba_base64 !== "string"
    ) {
      window.localStorage.removeItem(key);
      return;
    }
    const restored = base64ToBytes(draft.rgba_base64);
    if (restored.length !== state.pixels.length) {
      window.localStorage.removeItem(key);
      return;
    }
    state.draftStorageKey = key;
    state.draftIsForeign = foreign;
    state.draftSavedAt = draft.saved_at || null;
    if (draft.base_sha256 !== state.baseSha256) {
      let merge = null;
      if (typeof draft.base_rgba_base64 === "string") {
        const oldBase = base64ToBytes(draft.base_rgba_base64);
        merge = threeWayMergeRgba(
          oldBase,
          restored,
          state.basePixels,
          state.width,
          state.height,
        );
      }
      state.draftCandidate = { ...draft, stale: true, merge };
      if (merge) {
        elements.recoveryText.textContent =
          (foreign ? "发现另一标签页或上次会话的草稿。" : "") +
          "服务器已有更新：可安全恢复 " + merge.recoveredCount + " 个草稿像素，" +
          merge.conflictCount + " 个冲突像素将保留服务器内容。";
        elements.restoreDraft.textContent = "安全合并草稿";
      } else {
        elements.recoveryText.textContent =
          (foreign ? "发现另一标签页或上次会话的草稿。" : "") +
          "发现旧格式草稿，但服务器版本已经变化。可先下载精确备份，再明确载入画布检查。";
        elements.restoreDraft.textContent = "载入旧草稿";
      }
    } else {
      state.draftCandidate = { ...draft, stale: false, merge: null };
      elements.recoveryText.textContent = foreign
        ? "发现另一标签页或上次会话中与当前版本匹配的未保存草稿。"
        : "发现与当前版本匹配的未保存草稿。";
      elements.restoreDraft.textContent = "恢复草稿";
    }
    elements.discardDraft.textContent = foreign ? "暂时忽略" : "放弃草稿";
    elements.recovery.hidden = false;
  } catch (_) {
    // Corrupt or blocked storage must never block the editor itself.
  }
}

function decodeNeighbor(neighbor, expectedLength) {
  if (!neighbor) return null;
  const pixels = base64ToBytes(neighbor.rgba_base64);
  if (pixels.length !== expectedLength) {
    throw new Error("服务器返回的相邻帧 RGBA 长度不正确。");
  }
  return {
    frameIndex: neighbor.frame_index,
    sha256: neighbor.sha256,
    pixels,
  };
}

async function loadSession() {
  if (state.loadingSession) return;
  if (!jobId || !Number.isInteger(candidateIndex) || !Number.isInteger(frameIndex)) {
    elements.loading.hidden = true;
    setMessage("缺少任务、候选或帧编号。请从“逐帧修补”页面打开画布。", "error");
    window.__spritePixelEditorBoot?.markFailed?.();
    return;
  }
  state.loadingSession = true;
  state.loaded = false;
  elements.retryLoadButton.hidden = true;
  elements.loading.hidden = false;
  window.__spritePixelEditorBoot?.markStarted?.();
  try {
    let session = null;
    let lastError = null;
    for (let attempt = 1; attempt <= maxSessionLoadAttempts; attempt += 1) {
      elements.loading.textContent = attempt === 1
        ? "正在读取原始 RGBA 像素……"
        : "首次读取未完成，正在自动重试……";
      setMessage(
        attempt === 1 ? "正在连接本地像素接口……" : "首次读取失败，正在自动重试一次……",
        "info",
      );
      try {
        session = await fetchPixelSession();
        break;
      } catch (error) {
        lastError = error;
        if (!error?.retryable || attempt === maxSessionLoadAttempts) throw error;
        await waitMilliseconds(350);
      }
    }
    if (!session) throw lastError || sessionLoadError("无法读取像素会话。");
    const pixels = base64ToBytes(session.rgba_base64);
    const expectedLength = session.width * session.height * 4;
    if (pixels.length !== expectedLength) {
      throw new Error(`服务器返回的 RGBA 长度不正确：${pixels.length}，应为 ${expectedLength}。`);
    }
    state.width = session.width;
    state.height = session.height;
    state.pixels = pixels;
    state.basePixels = new Uint8ClampedArray(pixels);
    state.baseSha256 = session.base_sha256;
    state.manualVersions = session.manual_edit_versions;
    state.externalAttempts = session.external_repair_attempts;
    state.frameCount = session.frame_count;
    state.loop = Boolean(session.loop);
    state.alphaVisibleThreshold = Math.max(1, Number(session.alpha_visible_threshold) || 1);
    state.neighbors = {
      previous: decodeNeighbor(session.neighbors?.previous, expectedLength),
      next: decodeNeighbor(session.neighbors?.next, expectedLength),
    };
    state.neighborWarnings = session.neighbor_warnings || {};
    state.canEdit = session.can_edit;
    state.loaded = true;
    refreshOnionCanvases();
    const duplicateLoopNeighbor = Boolean(
      state.neighbors.previous &&
      state.neighbors.next &&
      state.neighbors.previous.frameIndex === state.neighbors.next.frameIndex &&
      state.neighbors.previous.sha256 === state.neighbors.next.sha256
    );
    elements.previousToggle.disabled = !state.neighbors.previous;
    elements.nextToggle.checked = !duplicateLoopNeighbor && Boolean(state.neighbors.next);
    elements.nextToggle.disabled = !state.neighbors.next || duplicateLoopNeighbor;
    elements.previousToggle.parentElement.title = state.neighbors.previous
      ? (duplicateLoopNeighbor ? "前后都是第 " : "洋红色：第 ") +
        (state.neighbors.previous.frameIndex + 1) +
        (duplicateLoopNeighbor ? " 帧，已合并为一层" : " 帧")
      : "当前帧没有前一帧";
    elements.nextToggle.parentElement.title = state.neighbors.next
      ? (duplicateLoopNeighbor
        ? "与前一帧相同，避免重复叠色"
        : "青色：第 " + (state.neighbors.next.frameIndex + 1) + " 帧")
      : "当前帧没有后一帧";
    elements.frameLabel.textContent =
      "候选 " + candidateIndex + " · 第 " + (frameIndex + 1) + "/" + state.frameCount + " 帧";
    elements.sizeLabel.textContent = `${state.width}×${state.height} RGBA`;
    elements.versionLabel.textContent = state.manualVersions
      ? `手工版本 v${state.manualVersions}`
      : "原始/外部版本";
    elements.loading.hidden = true;
    fitView();
    updatePaintColor();
    loadDraftCandidate();
    updateDirtyState();
    const missingReferences = Object.keys(state.neighborWarnings).length;
    if (state.canEdit) {
      setMessage(
        "画布已按 PNG 原始像素载入。洋红色是前一帧，青色是后一帧；所有参考层都不会写入最终图片。" +
          (missingReferences ? "有 " + missingReferences + " 张相邻参考帧暂时不可用，但不影响修补当前帧。" : ""),
        missingReferences ? "info" : "ok",
      );
    } else {
      setMessage("当前帧不是待修补状态，可以检查像素，但保存前需要在“播放检查”重新标记。", "info");
    }
    window.__spritePixelEditorBoot?.markReady?.();
  } catch (error) {
    elements.loading.hidden = true;
    setMessage(error instanceof Error ? error.message : "无法加载像素画布。", "error");
    elements.retryLoadButton.hidden = false;
    window.__spritePixelEditorBoot?.markFailed?.();
  } finally {
    state.loadingSession = false;
  }
}

elements.overlayCanvas.addEventListener("pointerdown", (event) => {
  if (!state.loaded) return;
  elements.viewport.focus({ preventScroll: true });
  event.preventDefault();
  state.pointerId = event.pointerId;
  elements.overlayCanvas.setPointerCapture(event.pointerId);
  const position = eventPosition(event);
  if (event.button === 1 || state.spaceDown) {
    state.pointerMode = "pan";
    state.panStart = {
      pointerX: position.x,
      pointerY: position.y,
      originX: state.originX,
      originY: state.originY,
    };
    elements.viewport.classList.add("is-panning");
    return;
  }
  const pixel = eventPixel(event);
  updatePixelInspector(pixel);
  if (!pixel || event.button !== 0) return;
  if (state.tool === "select") {
    state.pointerMode = "selection";
    state.selectionAnchor = pixel;
    state.selection = normalizeSelection(
      state.selectionAnchor,
      pixel,
      state.width,
      state.height,
    );
    updateSelectionControls();
    renderOverlay();
    return;
  }
  if (event.altKey || state.tool === "eyedropper") {
    pickColor(pixel);
    return;
  }
  if (state.draftCandidate) {
    setMessage("请先恢复、下载或放弃上次草稿，再开始新的像素修改。", "info");
    return;
  }
  if (state.saving) {
    setMessage("版本正在保存，像素修改已暂时锁定，完成后再继续。", "info");
    return;
  }
  if (!state.canEdit) {
    setMessage("当前帧不是待修补状态，暂时不能修改。请先在播放检查中标记。", "error");
    return;
  }
  if (state.tool === "fill") {
    fillPixel(pixel);
    return;
  }
  state.pointerMode = "stroke";
  beginStroke(pixel);
});

elements.overlayCanvas.addEventListener("pointermove", (event) => {
  if (!state.loaded) return;
  const position = eventPosition(event);
  if (state.pointerMode === "pan" && state.panStart) {
    state.originX = Math.round(state.panStart.originX + position.x - state.panStart.pointerX);
    state.originY = Math.round(state.panStart.originY + position.y - state.panStart.pointerY);
    render();
    return;
  }
  if (state.pointerMode === "selection" && state.selectionAnchor) {
    const selectionPixel = eventPixel(event) || clampedEventPixel(event);
    state.selection = normalizeSelection(
      state.selectionAnchor,
      selectionPixel,
      state.width,
      state.height,
    );
    updatePixelInspector(selectionPixel);
    updateSelectionControls();
    renderOverlay();
    return;
  }
  const pixel = eventPixel(event);
  updatePixelInspector(pixel);
  if (state.pointerMode === "stroke" && !state.saving) {
    if (pixel) continueStroke(pixel);
    else state.lastPixel = null;
  }
});

function endPointer(event) {
  if (state.pointerId !== event.pointerId) return;
  if (state.pointerMode === "stroke") finishStroke();
  if (state.pointerMode === "selection" && state.selection) {
    setMessage(
      "已框选 " + state.selection.width + "×" + state.selection.height +
        " 像素。方向键每次移动 1 像素。",
      "info",
    );
  }
  state.pointerMode = null;
  state.pointerId = null;
  state.panStart = null;
  state.selectionAnchor = null;
  elements.viewport.classList.remove("is-panning");
  if (elements.overlayCanvas.hasPointerCapture(event.pointerId)) {
    elements.overlayCanvas.releasePointerCapture(event.pointerId);
  }
}

elements.overlayCanvas.addEventListener("pointerup", endPointer);
elements.overlayCanvas.addEventListener("pointercancel", endPointer);
elements.overlayCanvas.addEventListener("lostpointercapture", (event) => {
  if (state.pointerId !== event.pointerId) return;
  if (state.pointerMode === "stroke" && state.strokeBefore) finishStroke();
  state.pointerMode = null;
  state.pointerId = null;
  state.panStart = null;
  state.selectionAnchor = null;
  state.lastPixel = null;
  elements.viewport.classList.remove("is-panning");
});
elements.overlayCanvas.addEventListener("pointerleave", (event) => {
  if (!state.pointerMode) updatePixelInspector(null);
  if (state.pointerMode === "stroke" && !eventPixel(event)) state.lastPixel = null;
});
elements.overlayCanvas.addEventListener("contextmenu", (event) => event.preventDefault());
elements.overlayCanvas.addEventListener(
  "wheel",
  (event) => {
    if (!state.loaded) return;
    event.preventDefault();
    changeZoom(event.deltaY < 0 ? 1 : -1, eventPosition(event));
  },
  { passive: false },
);

for (const button of document.querySelectorAll("[data-tool]")) {
  button.addEventListener("click", () => selectTool(button.dataset.tool));
}
elements.colorPicker.addEventListener("input", updatePaintColor);
elements.alphaInput.addEventListener("change", updatePaintColor);
elements.brushSize.addEventListener("change", renderOverlay);
elements.undoButton.addEventListener("click", undo);
elements.redoButton.addEventListener("click", redo);
elements.selectOpaque.addEventListener("click", selectVisiblePixels);
elements.nudgeLeft.addEventListener("click", () => moveSelection(-1, 0));
elements.nudgeUp.addEventListener("click", () => moveSelection(0, -1));
elements.nudgeDown.addEventListener("click", () => moveSelection(0, 1));
elements.nudgeRight.addEventListener("click", () => moveSelection(1, 0));
elements.clearSelectionPixels.addEventListener("click", clearSelectedPixels);
elements.cancelSelection.addEventListener("click", cancelSelection);
elements.resetButton.addEventListener("click", resetDraft);
elements.saveButton.addEventListener("click", saveVersion);
elements.zoomOut.addEventListener("click", () => changeZoom(-1));
elements.zoomOne.addEventListener("click", () => setZoom(1));
elements.zoomIn.addEventListener("click", () => changeZoom(1));
elements.zoomFit.addEventListener("click", fitView);
elements.gridToggle.addEventListener("change", renderOverlay);
elements.previousToggle.addEventListener("change", renderImage);
elements.nextToggle.addEventListener("change", renderImage);
elements.onionOpacity.addEventListener("input", () => {
  elements.onionOpacityValue.textContent = elements.onionOpacity.value + "%";
  renderImage();
});
elements.restoreDraft.addEventListener("click", restoreDraft);
elements.downloadDraft.addEventListener("click", downloadDraft);
elements.discardDraft.addEventListener("click", discardDraft);

window.addEventListener("keydown", (event) => {
  const target = event.target;
  const isField = target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement;
  if (event.code === "Space" && !isField) {
    state.spaceDown = true;
    event.preventDefault();
  }
  if (isField) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo();
    else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redo();
    return;
  }
  const key = event.key.toLowerCase();
  if (key === "b" || key === "p") selectTool("pencil");
  else if (key === "e") selectTool("eraser");
  else if (key === "i") selectTool("eyedropper");
  else if (key === "f") selectTool("fill");
  else if (key === "m") selectTool("select");
  else if (key === "escape") cancelSelection();
  else if ((key === "delete" || key === "backspace") && state.selection) {
    event.preventDefault();
    clearSelectedPixels();
  } else if (state.selection && ["arrowleft", "arrowright", "arrowup", "arrowdown"].includes(key)) {
    event.preventDefault();
    const step = event.shiftKey ? 8 : 1;
    if (key === "arrowleft") moveSelection(-step, 0);
    else if (key === "arrowright") moveSelection(step, 0);
    else if (key === "arrowup") moveSelection(0, -step);
    else moveSelection(0, step);
  }
  else if (key === "g") {
    elements.gridToggle.checked = !elements.gridToggle.checked;
    renderOverlay();
  } else if (key === "+" || key === "=") changeZoom(1);
  else if (key === "-" || key === "_") changeZoom(-1);
});

window.addEventListener("keyup", (event) => {
  if (event.code === "Space") state.spaceDown = false;
});
window.addEventListener("blur", () => {
  state.spaceDown = false;
});
function flushDraftBeforeExit() {
  if (!state.loaded || !state.pixels || !state.basePixels) return false;
  if (state.pointerMode === "stroke" && state.strokeBefore) finishStroke();
  const summary = diffRgbaSummary(state.pixels, state.basePixels, state.width, state.height);
  state.dirty = summary.count > 0;
  persistDraftNow();
  return state.dirty;
}

window.addEventListener("beforeunload", (event) => {
  if (!flushDraftBeforeExit()) return;
  event.preventDefault();
  event.returnValue = "";
});
window.addEventListener("pagehide", flushDraftBeforeExit);

if ("ResizeObserver" in window) {
  const resizeObserver = new ResizeObserver(() => {
    if (state.loaded && !state.pointerMode) fitView();
  });
  resizeObserver.observe(elements.viewport);
} else {
  window.addEventListener("resize", () => {
    if (state.loaded && !state.pointerMode) fitView();
  });
}

selectTool("pencil");
updatePaintColor();
window.__spritePixelEditorRetry = () => void loadSession();

async function startEditor() {
  try {
    await claimDraftTabIdentity();
  } catch (_) {
    // Draft tab coordination is optional and must never block the canvas.
  }
  await loadSession();
}

void startEditor();
