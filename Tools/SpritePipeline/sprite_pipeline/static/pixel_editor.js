import {
  applyRgbaChanges,
  rasterIntegerLine,
  screenToPixel,
} from "/pixel-editor-assets/pixel_editor_core.js?v=1";

const $ = (selector) => document.querySelector(selector);

const elements = {
  viewport: $("#viewport"),
  imageCanvas: $("#imageCanvas"),
  overlayCanvas: $("#overlayCanvas"),
  loading: $("#loading"),
  message: $("#message"),
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
  zoomFit: $("#zoomFit"),
  zoomIn: $("#zoomIn"),
  zoomValue: $("#zoomValue"),
  gridToggle: $("#gridToggle"),
  dirtyIndicator: $("#dirtyIndicator"),
  resetButton: $("#resetButton"),
  saveButton: $("#saveButton"),
  recovery: $("#recovery"),
  restoreDraft: $("#restoreDraft"),
  discardDraft: $("#discardDraft"),
};

const query = new URLSearchParams(window.location.search);
const jobId = query.get("job_id") || "";
const candidateIndex = Number.parseInt(query.get("candidate") || "", 10);
const frameIndex = Number.parseInt(query.get("frame") || "", 10);
const zoomLevels = [1, 2, 4, 8, 12, 16, 24, 32];
const maxHistory = 100;

const sourceCanvas = document.createElement("canvas");
const sourceContext = sourceCanvas.getContext("2d", { alpha: true });
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
  undoStack: [],
  redoStack: [],
  spaceDown: false,
  dirty: false,
  saving: false,
  draftCandidate: null,
  draftTimer: null,
  loaded: false,
};

const sessionUrl = () =>
  `/v1/jobs/${encodeURIComponent(jobId)}/candidates/${candidateIndex}/frames/${frameIndex}/pixel-edit`;
const draftKey = () => `sprite-pixel-draft:${jobId}:${candidateIndex}:${frameIndex}`;

function setMessage(text, kind = "info") {
  elements.message.textContent = text;
  elements.message.className = `message message--${kind}`;
}

function describeApiError(payload, fallback) {
  const message = payload?.error?.message || fallback;
  if (message.includes("repair_requested")) {
    return "这帧当前不在待修补状态。请回到“播放检查”重新标记后再编辑。";
  }
  if (message.includes("stale frame version")) {
    return "这帧已在其他窗口中更新。请刷新修补列表后重新打开，当前草稿仍保存在本机。";
  }
  if (message.includes("does not change any pixels")) {
    return "当前像素与保存前完全相同，不需要建立新版本。";
  }
  return message;
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
  elements.colorPreview.style.backgroundColor = `rgba(${r}, ${g}, ${b}, ${a / 255})`;
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

function crisp(value) {
  return (Math.round(value * state.dpr) + 0.5) / state.dpr;
}

function renderImage() {
  resizeDisplayCanvases();
  imageContext.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  imageContext.clearRect(0, 0, state.cssWidth, state.cssHeight);
  imageContext.imageSmoothingEnabled = false;
  refreshSourceCanvas();
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
  }

  if (state.hoverPixel) {
    const { x, y } = state.hoverPixel;
    const brushSize = state.tool === "eyedropper"
      ? 1
      : Number.parseInt(elements.brushSize.value, 10);
    const brushStart = state.tool === "eyedropper"
      ? 0
      : -Math.floor((brushSize - 1) / 2);
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

function updatePixelInspector(pixel) {
  state.hoverPixel = pixel;
  if (!pixel || !state.loaded) {
    elements.coordinateValue.textContent = "—";
    elements.pixelValue.textContent = "—";
  } else {
    const [r, g, b, a] = getPixel(pixel.x, pixel.y);
    elements.coordinateValue.textContent = `(${pixel.x}, ${pixel.y})`;
    elements.pixelValue.textContent = `${r}, ${g}, ${b}, ${a}`;
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
  setMessage(`已从像素 (${pixel.x}, ${pixel.y}) 读取 RGBA(${r}, ${g}, ${b}, ${a})。`, "ok");
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
  if (changes.length) {
    state.undoStack.push({ changes });
    if (state.undoStack.length > maxHistory) state.undoStack.shift();
    state.redoStack = [];
    updateDirtyState();
  }
}

function applyHistory(command, direction) {
  applyRgbaChanges(state.pixels, command.changes, direction);
  updateDirtyState();
  render();
}

function undo() {
  const command = state.undoStack.pop();
  if (!command) return;
  applyHistory(command, "undo");
  state.redoStack.push(command);
}

function redo() {
  const command = state.redoStack.pop();
  if (!command) return;
  applyHistory(command, "redo");
  state.undoStack.push(command);
}

function scheduleDraftSave() {
  window.clearTimeout(state.draftTimer);
  if (!state.dirty) {
    try {
      window.localStorage.removeItem(draftKey());
    } catch (_) {
      // Draft recovery is best-effort; editing remains fully functional.
    }
    return;
  }
  state.draftTimer = window.setTimeout(() => {
    try {
      window.localStorage.setItem(
        draftKey(),
        JSON.stringify({
          schema_version: 1,
          base_sha256: state.baseSha256,
          width: state.width,
          height: state.height,
          rgba_base64: bytesToBase64(state.pixels),
          saved_at: new Date().toISOString(),
        }),
      );
    } catch (_) {
      setMessage("像素修改仍在当前页面中，但浏览器无法保存恢复草稿。请尽快正式保存。", "error");
    }
  }, 650);
}

function updateDirtyState() {
  state.dirty = !pixelsEqual(state.pixels, state.basePixels);
  elements.undoButton.disabled = state.undoStack.length === 0 || state.saving;
  elements.redoButton.disabled = state.redoStack.length === 0 || state.saving;
  elements.resetButton.disabled = !state.dirty || state.saving;
  elements.saveButton.disabled = !state.dirty || !state.canEdit || state.saving;
  elements.dirtyIndicator.textContent = state.dirty ? "有未保存的像素修改" : "尚未修改";
  elements.dirtyIndicator.classList.toggle("is-dirty", state.dirty);
  scheduleDraftSave();
}

function resetDraft() {
  if (!state.dirty) return;
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
  const restored = base64ToBytes(draft.rgba_base64);
  if (restored.length !== state.pixels.length) {
    discardDraft();
    setMessage("草稿尺寸不正确，已忽略。", "error");
    return;
  }
  const changes = [];
  for (let offset = 0; offset < restored.length; offset += 4) {
    const before = Array.from(state.basePixels.slice(offset, offset + 4));
    const after = Array.from(restored.slice(offset, offset + 4));
    if (!before.every((value, index) => value === after[index])) {
      changes.push({ offset, before, after });
    }
  }
  state.pixels.set(restored);
  state.undoStack = changes.length ? [{ changes }] : [];
  state.redoStack = [];
  elements.recovery.hidden = true;
  updateDirtyState();
  render();
  setMessage(`已恢复草稿，其中包含 ${changes.length} 个与当前版本不同的像素。`, "ok");
}

function discardDraft() {
  state.draftCandidate = null;
  elements.recovery.hidden = true;
  try {
    window.localStorage.removeItem(draftKey());
  } catch (_) {
    // Nothing else is required when storage is unavailable.
  }
}

async function saveVersion() {
  if (!state.dirty || !state.canEdit || state.saving) return;
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
        rgba_base64: bytesToBase64(state.pixels),
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
    state.basePixels = new Uint8ClampedArray(state.pixels);
    state.undoStack = [];
    state.redoStack = [];
    state.canEdit = false;
    discardDraft();
    elements.versionLabel.textContent = `手工版本 v${state.manualVersions}`;
    setMessage(
      "手工修补版本已保存，RGBA 往返校验和序列检查均已完成。请在外层页面点击“刷新”，回到播放检查确认整段动画。",
      "ok",
    );
    window.parent.postMessage(
      {
        type: "sprite-pixel-editor-saved",
        jobId,
        candidateIndex,
        frameIndex,
        manualVersion: state.manualVersions,
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
    const serialized = window.localStorage.getItem(draftKey());
    if (!serialized) return;
    const draft = JSON.parse(serialized);
    if (
      draft.base_sha256 !== state.baseSha256 ||
      draft.width !== state.width ||
      draft.height !== state.height ||
      typeof draft.rgba_base64 !== "string"
    ) {
      window.localStorage.removeItem(draftKey());
      return;
    }
    state.draftCandidate = draft;
    elements.recovery.hidden = false;
  } catch (_) {
    // Corrupt or blocked storage must never block the editor itself.
  }
}

async function loadSession() {
  if (!jobId || !Number.isInteger(candidateIndex) || !Number.isInteger(frameIndex)) {
    elements.loading.hidden = true;
    setMessage("缺少任务、候选或帧编号。请从“逐帧修补”页面打开画布。", "error");
    return;
  }
  try {
    const response = await window.fetch(sessionUrl(), { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(describeApiError(payload, `读取失败（HTTP ${response.status}）`));
    }
    const session = payload.data.session;
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
    state.canEdit = session.can_edit;
    state.loaded = true;
    elements.frameLabel.textContent = `候选 ${candidateIndex} · 第 ${frameIndex + 1} 帧`;
    elements.sizeLabel.textContent = `${state.width}×${state.height} RGBA`;
    elements.versionLabel.textContent = state.manualVersions
      ? `手工版本 v${state.manualVersions}`
      : "原始/外部版本";
    elements.loading.hidden = true;
    fitView();
    updatePaintColor();
    updateDirtyState();
    loadDraftCandidate();
    if (state.canEdit) {
      setMessage("画布已按 PNG 原始像素载入。网格和光标位于独立层，不会写入最终图片。", "ok");
    } else {
      setMessage("当前帧不是待修补状态，可以检查像素，但保存前需要在“播放检查”重新标记。", "info");
    }
  } catch (error) {
    elements.loading.hidden = true;
    setMessage(error instanceof Error ? error.message : "无法加载像素画布。", "error");
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
  if (event.altKey || state.tool === "eyedropper") {
    pickColor(pixel);
    return;
  }
  if (!state.canEdit) {
    setMessage("当前帧不是待修补状态，暂时不能修改。请先在播放检查中标记。", "error");
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
  const pixel = eventPixel(event);
  updatePixelInspector(pixel);
  if (state.pointerMode === "stroke") {
    if (pixel) continueStroke(pixel);
    else state.lastPixel = null;
  }
});

function endPointer(event) {
  if (state.pointerId !== event.pointerId) return;
  if (state.pointerMode === "stroke") finishStroke();
  state.pointerMode = null;
  state.pointerId = null;
  state.panStart = null;
  elements.viewport.classList.remove("is-panning");
  if (elements.overlayCanvas.hasPointerCapture(event.pointerId)) {
    elements.overlayCanvas.releasePointerCapture(event.pointerId);
  }
}

elements.overlayCanvas.addEventListener("pointerup", endPointer);
elements.overlayCanvas.addEventListener("pointercancel", endPointer);
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
elements.resetButton.addEventListener("click", resetDraft);
elements.saveButton.addEventListener("click", saveVersion);
elements.zoomOut.addEventListener("click", () => changeZoom(-1));
elements.zoomIn.addEventListener("click", () => changeZoom(1));
elements.zoomFit.addEventListener("click", fitView);
elements.gridToggle.addEventListener("change", renderOverlay);
elements.restoreDraft.addEventListener("click", restoreDraft);
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
window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

const resizeObserver = new ResizeObserver(() => {
  if (state.loaded && !state.pointerMode) fitView();
});
resizeObserver.observe(elements.viewport);

selectTool("pencil");
updatePaintColor();
loadSession();
