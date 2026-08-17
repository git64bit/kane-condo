import {
  PackageValidationError,
  validateLocalConfig,
  validateLocalPackage,
} from "./package-validator.js";

const OVERVIEW_FORMAT = "kane-condo-county-overview";
const OVERVIEW_VERSION = 1;
const OVERVIEW_SRS_ID = 4326;
const EXPECTED_COUNTY = {
  county_key: "kane-county-il",
  fips_code: "17089",
  name: "Kane County",
  state_code: "IL",
};

const NAVIGATION_MIN_ZOOM = 0.25;
const NAVIGATION_MAX_ZOOM = 4096;
const WHEEL_SENSITIVITY = 0.0015;

const ROAD_MAGIC = "KCRD028\n";
const ROAD_FORMAT = "kane-condo-road-lod";
const ROAD_VERSION = 1;
const ROAD_SRS_ID = 4326;
const ROAD_LEVEL_KEYS = ["orientation", "context", "detail"];
const ROAD_CONTEXT_ZOOM = 4;
const ROAD_DETAIL_ZOOM = 16;

const WATER_MAGIC = "KCRW029\n";
const WATER_FORMAT = "kane-condo-water-lod";
const WATER_VERSION = 1;
const WATER_SRS_ID = 4326;
const WATER_LEVEL_KEYS = ["overview", "context", "detail"];
const WATER_CREEK_FRACTIONS = [0, 0.60, 1];
const WATER_CONTEXT_ZOOM = 4;
const WATER_DETAIL_ZOOM = 16;

const BUILDING_MAGIC = "KCBD030\n";
const BUILDING_FORMAT = "kane-condo-building-lod";
const BUILDING_VERSION = 1;
const BUILDING_SRS_ID = 4326;
const BUILDING_LEVEL_KEYS = ["context", "neighborhood", "editing"];
const BUILDING_AREA_FRACTIONS = [0.35, 1, 1];
const BUILDING_NEIGHBORHOOD_ZOOM = 8;
const BUILDING_EDITING_ZOOM = 32;

const CLASSIFICATION_FORMAT = "kane-condo-classification-snapshot";
const CLASSIFICATION_VERSION = 1;
const CLASSIFICATION_VALUES = ["unclassified", "other", "condominium", "apartments"];
const EXPLICIT_CLASSIFICATIONS = ["other", "condominium", "apartments"];
const BUILDING_KEY_PATTERN = /^kcb-[0-9a-f]{64}$/;

function fail(code, message, detail = null) {
  throw new PackageValidationError(code, message, detail);
}

function overviewFail(message, detail = null) {
  fail("OVERVIEW_INCOMPATIBLE", message, detail);
}

function roadFail(message, detail = null) {
  fail("ROAD_INCOMPATIBLE", message, detail);
}

function waterFail(message, detail = null) {
  fail("WATER_INCOMPATIBLE", message, detail);
}

function buildingFail(message, detail = null) {
  fail("BUILDING_INCOMPATIBLE", message, detail);
}

function classificationFail(message, detail = null) {
  fail("CLASSIFICATION_INCOMPATIBLE", message, detail);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected, label, failure = overviewFail) {
  if (!isPlainObject(value)) {
    failure(`${label} is not an object.`);
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    failure(`${label} fields are incompatible.`, `Expected: ${wanted.join(", ")}\nFound: ${actual.join(", ")}`);
  }
  return value;
}

function finiteNumber(value, label, failure = overviewFail) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    failure(`${label} is not a finite number.`);
  }
  return value;
}

function almostEqual(left, right, tolerance = 1e-12) {
  return Math.abs(left - right) <= tolerance * Math.max(1, Math.abs(left), Math.abs(right));
}

function canonicalize(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalize).join(",")}]`;
  }
  if (isPlainObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Bytes(bytes) {
  if (!globalThis.crypto?.subtle) {
    fail("CRYPTO_UNAVAILABLE", "This browser does not provide Web Crypto SHA-256 support.");
  }
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", view);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export function validateCountyOverview(document, manifest) {
  const overview = exactKeys(document, ["county", "fit", "format", "outline", "source", "srs_id", "version"], "County overview");
  if (overview.format !== OVERVIEW_FORMAT || overview.version !== OVERVIEW_VERSION) {
    overviewFail(`Unsupported county overview ${String(overview.format)} version ${String(overview.version)}.`, `Expected ${OVERVIEW_FORMAT} version ${OVERVIEW_VERSION}.`);
  }
  if (overview.srs_id !== OVERVIEW_SRS_ID) overviewFail(`County overview SRS ${String(overview.srs_id)} is unsupported.`);

  const county = exactKeys(overview.county, ["county_key", "fips_code", "name", "state_code"], "County overview county");
  const manifestCounty = manifest?.database?.county;
  if (!isPlainObject(manifestCounty)) overviewFail("Validated package manifest does not expose county identity.");
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (county[key] !== EXPECTED_COUNTY[key] || county[key] !== manifestCounty[key]) {
      overviewFail(`County overview ${key} does not match the validated Kane County package.`);
    }
  }

  const source = exactKeys(overview.source, ["dataset_key", "geometry_sha256", "geometry_type", "release_content_sha256", "release_key", "source_feature_id"], "County overview source");
  if (source.dataset_key !== "county-boundary") overviewFail("County overview does not identify the county-boundary dataset.");
  if (source.geometry_type !== "Polygon" && source.geometry_type !== "MultiPolygon") overviewFail(`County overview geometry type ${String(source.geometry_type)} is unsupported.`);
  const acceptedBoundary = manifest?.database?.accepted_releases?.["county-boundary"];
  if (!isPlainObject(acceptedBoundary) || source.release_key !== acceptedBoundary.release_key || source.release_content_sha256 !== acceptedBoundary.release_content_sha256) {
    overviewFail("County overview boundary release does not match the validated package manifest.");
  }

  const fit = exactKeys(overview.fit, ["bounds", "center", "height", "width"], "County overview fit");
  if (!Array.isArray(fit.bounds) || fit.bounds.length !== 4) overviewFail("County overview fit bounds are invalid.");
  const [minX, minY, maxX, maxY] = fit.bounds.map((value, index) => finiteNumber(value, `County overview bound ${index}`));
  if (!(maxX > minX) || !(maxY > minY)) overviewFail("County overview fit bounds do not describe a positive extent.");
  if (!Array.isArray(fit.center) || fit.center.length !== 2) overviewFail("County overview fit center is invalid.");
  const centerX = finiteNumber(fit.center[0], "County overview center longitude");
  const centerY = finiteNumber(fit.center[1], "County overview center latitude");
  const width = finiteNumber(fit.width, "County overview fit width");
  const height = finiteNumber(fit.height, "County overview fit height");
  if (!almostEqual(width, maxX - minX) || !almostEqual(height, maxY - minY) || !almostEqual(centerX, (minX + maxX) / 2) || !almostEqual(centerY, (minY + maxY) / 2)) {
    overviewFail("County overview fit metadata is inconsistent with its exact bounds.");
  }

  const outline = exactKeys(overview.outline, ["kind", "ring_count", "rings", "simplification_tolerance_degrees", "source_interior_ring_count", "source_vertex_count", "vertex_count"], "County overview outline");
  if (outline.kind !== "exterior-rings" || !Array.isArray(outline.rings)) overviewFail("County overview outline is not an exterior-ring collection.");
  if (!Number.isSafeInteger(outline.ring_count) || outline.ring_count < 1 || outline.ring_count !== outline.rings.length) overviewFail("County overview ring count is invalid.");
  for (let ringIndex = 0; ringIndex < outline.rings.length; ringIndex += 1) {
    const ring = outline.rings[ringIndex];
    if (!Array.isArray(ring) || ring.length < 4) overviewFail(`County overview ring ${ringIndex} is too short.`);
    for (let pointIndex = 0; pointIndex < ring.length; pointIndex += 1) {
      const point = ring[pointIndex];
      if (!Array.isArray(point) || point.length !== 2) overviewFail(`County overview ring ${ringIndex} point ${pointIndex} is invalid.`);
      const x = finiteNumber(point[0], `County overview ring ${ringIndex} longitude`);
      const y = finiteNumber(point[1], `County overview ring ${ringIndex} latitude`);
      if (x < minX - 1e-12 || x > maxX + 1e-12 || y < minY - 1e-12 || y > maxY + 1e-12) overviewFail(`County overview ring ${ringIndex} extends outside the exact source bounds.`);
    }
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) overviewFail(`County overview ring ${ringIndex} is not closed.`);
  }
  return overview;
}

export function overviewViewBox(bounds, paddingFraction = 0.04) {
  if (!Array.isArray(bounds) || bounds.length !== 4) throw new TypeError("bounds must contain four numbers");
  const [minX, minY, maxX, maxY] = bounds;
  const width = maxX - minX;
  const height = maxY - minY;
  if (!(width > 0) || !(height > 0) || !(paddingFraction >= 0)) throw new RangeError("bounds and padding must describe a positive extent");
  const padX = width * paddingFraction;
  const padY = height * paddingFraction;
  return [minX - padX, -(maxY + padY), width + (2 * padX), height + (2 * padY)];
}

function formatCoordinate(value) { return Number(value).toString(); }

export function overviewPathData(rings) {
  return rings.map((ring) => {
    const points = ring.slice(0, -1);
    if (points.length < 3) throw new RangeError("overview ring must contain at least three distinct vertices");
    const [first, ...rest] = points;
    const commands = [`M ${formatCoordinate(first[0])} ${formatCoordinate(-first[1])}`];
    for (const point of rest) commands.push(`L ${formatCoordinate(point[0])} ${formatCoordinate(-point[1])}`);
    commands.push("Z");
    return commands.join(" ");
  }).join(" ");
}

// Batch 036 navigation: pure viewport state only.
function validateViewBox(viewBox) {
  if (!Array.isArray(viewBox) || viewBox.length !== 4 || viewBox.some((value) => typeof value !== "number" || !Number.isFinite(value))) throw new TypeError("viewBox must contain four finite numbers");
  if (!(viewBox[2] > 0) || !(viewBox[3] > 0)) throw new RangeError("viewBox width and height must be positive");
  return viewBox;
}

export function viewportMetrics(viewBox, pixelWidth, pixelHeight) {
  validateViewBox(viewBox);
  if (!(pixelWidth > 0) || !(pixelHeight > 0)) throw new RangeError("viewport pixel dimensions must be positive");
  const scale = Math.min(pixelWidth / viewBox[2], pixelHeight / viewBox[3]);
  const renderedWidth = viewBox[2] * scale;
  const renderedHeight = viewBox[3] * scale;
  return { scale, offsetX: (pixelWidth - renderedWidth) / 2, offsetY: (pixelHeight - renderedHeight) / 2 };
}

export function clientPointToWorld(viewBox, pixelWidth, pixelHeight, pixelX, pixelY) {
  const metrics = viewportMetrics(viewBox, pixelWidth, pixelHeight);
  return [viewBox[0] + ((pixelX - metrics.offsetX) / metrics.scale), viewBox[1] + ((pixelY - metrics.offsetY) / metrics.scale)];
}

export function panViewBoxByPixels(viewBox, pixelWidth, pixelHeight, deltaX, deltaY) {
  const metrics = viewportMetrics(viewBox, pixelWidth, pixelHeight);
  return [viewBox[0] - (deltaX / metrics.scale), viewBox[1] - (deltaY / metrics.scale), viewBox[2], viewBox[3]];
}

export function zoomViewBoxAt(viewBox, homeViewBox, anchorX, anchorY, requestedSizeScale) {
  validateViewBox(viewBox); validateViewBox(homeViewBox);
  if (![anchorX, anchorY, requestedSizeScale].every((value) => typeof value === "number" && Number.isFinite(value))) throw new TypeError("zoom anchor and scale must be finite numbers");
  if (!(requestedSizeScale > 0)) throw new RangeError("zoom scale must be positive");
  const currentZoom = homeViewBox[2] / viewBox[2];
  const requestedZoom = currentZoom / requestedSizeScale;
  const targetZoom = Math.min(NAVIGATION_MAX_ZOOM, Math.max(NAVIGATION_MIN_ZOOM, requestedZoom));
  const actualSizeScale = currentZoom / targetZoom;
  return [
    anchorX - ((anchorX - viewBox[0]) * actualSizeScale),
    anchorY - ((anchorY - viewBox[1]) * actualSizeScale),
    viewBox[2] * actualSizeScale,
    viewBox[3] * actualSizeScale,
  ];
}

export function wheelSizeScale(deltaY) {
  if (typeof deltaY !== "number" || !Number.isFinite(deltaY)) throw new TypeError("wheel delta must be finite");
  return Math.exp(Math.max(-240, Math.min(240, deltaY)) * WHEEL_SENSITIVITY);
}

export function resetViewBox(homeViewBox) { validateViewBox(homeViewBox); return [...homeViewBox]; }
function applyViewBox(canvas, viewBox) { canvas.setAttribute("viewBox", validateViewBox(viewBox).join(" ")); }

function installMapNavigation(ui, homeViewBox, onViewChange = () => {}) {
  const canvas = ui.mapCanvas;
  let currentViewBox = resetViewBox(homeViewBox);
  let drag = null;
  const update = (viewBox) => {
    currentViewBox = validateViewBox(viewBox);
    applyViewBox(canvas, currentViewBox);
    onViewChange([...currentViewBox]);
  };
  const reset = () => update(resetViewBox(homeViewBox));
  ui.resetView.disabled = false;
  ui.resetView.addEventListener("click", reset);
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    canvas.classList.add("is-panning");
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const rect = canvas.getBoundingClientRect();
    const deltaX = event.clientX - drag.x;
    const deltaY = event.clientY - drag.y;
    if (deltaX !== 0 || deltaY !== 0) {
      update(panViewBoxByPixels(currentViewBox, rect.width, rect.height, deltaX, deltaY));
      drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    }
  });
  const finishDrag = (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    drag = null;
    canvas.classList.remove("is-panning");
  };
  canvas.addEventListener("pointerup", finishDrag);
  canvas.addEventListener("pointercancel", finishDrag);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const [anchorX, anchorY] = clientPointToWorld(currentViewBox, rect.width, rect.height, event.clientX - rect.left, event.clientY - rect.top);
    update(zoomViewBoxAt(currentViewBox, homeViewBox, anchorX, anchorY, wheelSizeScale(event.deltaY)));
  }, { passive: false });
  return { getViewBox: () => [...currentViewBox], reset };
}
// End Batch 036 navigation.

// Batch 037 roads: validated local KRF bytes, decoded only in browser memory.
function readUint64BigEndian(view, offset, failure = roadFail, label = "Road KRF") {
  const high = view.getUint32(offset, false);
  const low = view.getUint32(offset + 4, false);
  const value = (high * 4294967296) + low;
  if (!Number.isSafeInteger(value)) failure(`${label} index length exceeds browser-safe integer range.`);
  return value;
}

function requireRoadBounds(bounds, label) {
  if (!Array.isArray(bounds) || bounds.length !== 4) roadFail(`${label} bounds are invalid.`);
  const values = bounds.map((value, index) => finiteNumber(value, `${label} bound ${index}`, roadFail));
  if (values[2] < values[0] || values[3] < values[1]) roadFail(`${label} bounds are inverted.`);
  return values;
}

function validateRoadIndex(index, manifest, payloadLength) {
  exactKeys(index, ["chunk_feature_limit", "format", "levels", "road_bounds", "selection", "source", "srs_id", "version"], "Road KRF index", roadFail);
  if (index.format !== ROAD_FORMAT || index.version !== ROAD_VERSION) roadFail(`Unsupported road KRF ${String(index.format)} version ${String(index.version)}.`);
  if (index.srs_id !== ROAD_SRS_ID) roadFail(`Road KRF SRS ${String(index.srs_id)} is unsupported.`);
  if (!Number.isSafeInteger(index.chunk_feature_limit) || index.chunk_feature_limit < 1) roadFail("Road KRF chunk feature limit is invalid.");
  requireRoadBounds(index.road_bounds, "Road KRF");

  const source = exactKeys(index.source, ["county", "dataset_key", "feature_count", "release_content_sha256", "release_key"], "Road KRF source", roadFail);
  if (source.dataset_key !== "roads") roadFail("Road KRF source dataset is not roads.");
  if (!Number.isSafeInteger(source.feature_count) || source.feature_count < 1) roadFail("Road KRF source feature count is invalid.");
  const county = exactKeys(source.county, ["county_key", "fips_code", "name", "state_code"], "Road KRF county", roadFail);
  const manifestCounty = manifest?.database?.county;
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (county[key] !== EXPECTED_COUNTY[key] || county[key] !== manifestCounty?.[key]) roadFail(`Road KRF county ${key} does not match the validated package.`);
  }
  const acceptedRoads = manifest?.database?.accepted_releases?.roads;
  if (!isPlainObject(acceptedRoads) || source.release_key !== acceptedRoads.release_key || source.release_content_sha256 !== acceptedRoads.release_content_sha256 || source.feature_count !== acceptedRoads.feature_count) {
    roadFail("Road KRF release does not match the validated package manifest.");
  }

  if (!Array.isArray(index.levels) || index.levels.length !== ROAD_LEVEL_KEYS.length) roadFail("Road KRF must contain exactly three LOD levels.");
  let expectedOffset = 0;
  let previousCount = 0;
  for (let levelIndex = 0; levelIndex < ROAD_LEVEL_KEYS.length; levelIndex += 1) {
    const level = exactKeys(index.levels[levelIndex], ["chunks", "cumulative_length_fraction", "feature_count", "key", "purpose", "rank", "simplification_tolerance_degrees", "source_vertex_count", "vertex_count"], `Road KRF level ${levelIndex}`, roadFail);
    if (level.key !== ROAD_LEVEL_KEYS[levelIndex] || level.rank !== levelIndex) roadFail("Road KRF LOD order/rank is incompatible.");
    if (!Number.isSafeInteger(level.feature_count) || level.feature_count < 1 || level.feature_count < previousCount) roadFail(`Road KRF level ${level.key} feature count is invalid or non-monotonic.`);
    previousCount = level.feature_count;
    if (!Array.isArray(level.chunks) || level.chunks.length < 1) roadFail(`Road KRF level ${level.key} has no chunks.`);
    let chunkFeatures = 0;
    for (const chunk of level.chunks) {
      exactKeys(chunk, ["bounds", "feature_count", "length", "offset", "payload_sha256", "records_sha256", "uncompressed_length"], `Road KRF ${level.key} chunk`, roadFail);
      requireRoadBounds(chunk.bounds, `Road KRF ${level.key} chunk`);
      if (![chunk.feature_count, chunk.length, chunk.offset, chunk.uncompressed_length].every(Number.isSafeInteger)) roadFail(`Road KRF ${level.key} chunk integer fields are invalid.`);
      if (chunk.feature_count < 1 || chunk.feature_count > index.chunk_feature_limit || chunk.length < 1 || chunk.uncompressed_length < 1 || chunk.offset !== expectedOffset) roadFail(`Road KRF ${level.key} chunk framing is invalid.`);
      if (!/^[0-9a-f]{64}$/.test(chunk.payload_sha256) || !/^[0-9a-f]{64}$/.test(chunk.records_sha256)) roadFail(`Road KRF ${level.key} chunk hashes are invalid.`);
      expectedOffset += chunk.length;
      chunkFeatures += chunk.feature_count;
    }
    if (chunkFeatures !== level.feature_count) roadFail(`Road KRF level ${level.key} chunk feature count does not match its level count.`);
  }
  if (index.levels[2].feature_count !== source.feature_count) roadFail("Road KRF detail level is not the complete accepted road network.");
  if (expectedOffset !== payloadLength) roadFail("Road KRF payload length does not match the chunk inventory.");
  return index;
}

export function parseRoadContainer(bytes, manifest) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (data.byteLength < ROAD_MAGIC.length + 8) roadFail("Road KRF is truncated before its index.");
  const magic = new TextDecoder("ascii", { fatal: true }).decode(data.slice(0, ROAD_MAGIC.length));
  if (magic !== ROAD_MAGIC) roadFail("Road KRF magic header is invalid.");
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const indexLength = readUint64BigEndian(view, ROAD_MAGIC.length);
  const indexStart = ROAD_MAGIC.length + 8;
  const indexEnd = indexStart + indexLength;
  if (indexEnd > data.byteLength) roadFail("Road KRF index is truncated.");
  let indexText;
  let index;
  try {
    indexText = new TextDecoder("utf-8", { fatal: true }).decode(data.slice(indexStart, indexEnd));
    index = JSON.parse(indexText);
  } catch (error) {
    roadFail("Road KRF index is not valid UTF-8 JSON.", String(error));
  }
  if (indexText !== canonicalize(index)) roadFail("Road KRF index is not canonical JSON.");
  const payload = data.slice(indexEnd);
  validateRoadIndex(index, manifest, payload.byteLength);
  return { index, payload };
}

async function inflateZlib(compressed) {
  if (typeof DecompressionStream !== "function") fail("ROAD_DECOMPRESSION_UNAVAILABLE", "This browser does not provide deflate decompression required by the road package.");
  try {
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch (error) {
    fail("ROAD_DECOMPRESSION_FAILED", "A road KRF chunk could not be decompressed.", String(error));
  }
}

function validateRoadRecord(record, label) {
  exactKeys(record, ["bounds", "coordinates", "geometry_type", "source_feature_id"], label, roadFail);
  requireRoadBounds(record.bounds, label);
  if (typeof record.source_feature_id !== "string" || record.source_feature_id.length === 0) roadFail(`${label} source identity is invalid.`);
  if (record.geometry_type !== "LineString" && record.geometry_type !== "MultiLineString") roadFail(`${label} geometry type is unsupported.`);
  const lines = record.geometry_type === "LineString" ? [record.coordinates] : record.coordinates;
  if (!Array.isArray(lines) || lines.length < 1) roadFail(`${label} contains no line coordinates.`);
  for (const line of lines) {
    if (!Array.isArray(line) || line.length < 2) roadFail(`${label} contains a line with fewer than two points.`);
    for (const point of line) {
      if (!Array.isArray(point) || point.length !== 2 || point.some((value) => typeof value !== "number" || !Number.isFinite(value))) roadFail(`${label} contains an invalid coordinate.`);
    }
  }
  return record;
}

export async function decodeRoadLevel(container, levelKey) {
  if (!ROAD_LEVEL_KEYS.includes(levelKey)) roadFail(`Unknown road LOD level ${String(levelKey)}.`);
  const level = container.index.levels.find((candidate) => candidate.key === levelKey);
  if (!level) roadFail(`Road KRF does not contain level ${levelKey}.`);
  const records = [];
  for (const [chunkIndex, chunk] of level.chunks.entries()) {
    const compressed = container.payload.slice(chunk.offset, chunk.offset + chunk.length);
    if (await sha256Bytes(compressed) !== chunk.payload_sha256) roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} compressed hash is invalid.`);
    const raw = await inflateZlib(compressed);
    if (raw.byteLength !== chunk.uncompressed_length) roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} decompressed length is invalid.`);
    if (await sha256Bytes(raw) !== chunk.records_sha256) roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} record hash is invalid.`);
    let text;
    let chunkRecords;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
      chunkRecords = JSON.parse(text);
    } catch (error) {
      roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} records are invalid JSON.`, String(error));
    }
    if (text !== canonicalize(chunkRecords)) roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} records are not canonical JSON.`);
    if (!Array.isArray(chunkRecords) || chunkRecords.length !== chunk.feature_count) roadFail(`Road KRF ${levelKey} chunk ${chunkIndex} feature count is invalid.`);
    for (let recordIndex = 0; recordIndex < chunkRecords.length; recordIndex += 1) validateRoadRecord(chunkRecords[recordIndex], `Road ${levelKey} record ${records.length + recordIndex}`);
    records.push(...chunkRecords);
  }
  if (records.length !== level.feature_count) roadFail(`Road KRF level ${levelKey} decoded feature count is invalid.`);
  return records;
}

function linePathData(line) {
  const [first, ...rest] = line;
  const commands = [`M ${formatCoordinate(first[0])} ${formatCoordinate(-first[1])}`];
  for (const point of rest) commands.push(`L ${formatCoordinate(point[0])} ${formatCoordinate(-point[1])}`);
  return commands.join(" ");
}

export function roadPathData(records) {
  const paths = [];
  for (const record of records) {
    const lines = record.geometry_type === "LineString" ? [record.coordinates] : record.coordinates;
    for (const line of lines) paths.push(linePathData(line));
  }
  return paths.join(" ");
}

export function roadLevelForViewBox(viewBox, homeViewBox) {
  validateViewBox(viewBox); validateViewBox(homeViewBox);
  const zoom = homeViewBox[2] / viewBox[2];
  if (zoom >= ROAD_DETAIL_ZOOM) return "detail";
  if (zoom >= ROAD_CONTEXT_ZOOM) return "context";
  return "orientation";
}

function createRoadLayerController(ui, container, homeViewBox, onLevelChange = () => {}) {
  const cache = new Map();
  const pending = new Map();
  let visibleLevel = null;
  let wantedLevel = null;
  let requestSerial = 0;

  const loadPath = (levelKey) => {
    if (cache.has(levelKey)) return Promise.resolve(cache.get(levelKey));
    if (pending.has(levelKey)) return pending.get(levelKey);
    const work = decodeRoadLevel(container, levelKey).then((records) => {
      const pathData = roadPathData(records);
      cache.set(levelKey, pathData);
      pending.delete(levelKey);
      return pathData;
    }, (error) => {
      pending.delete(levelKey);
      throw error;
    });
    pending.set(levelKey, work);
    return work;
  };

  const request = async (viewBox) => {
    const levelKey = roadLevelForViewBox(viewBox, homeViewBox);
    wantedLevel = levelKey;
    if (visibleLevel === levelKey) return;
    const serial = ++requestSerial;
    const pathData = await loadPath(levelKey);
    if (serial !== requestSerial || wantedLevel !== levelKey) return;
    ui.roadPath.setAttribute("d", pathData);
    ui.roadPath.dataset.level = levelKey;
    visibleLevel = levelKey;
    onLevelChange(levelKey);
  };
  return { request, getVisibleLevel: () => visibleLevel };
}
// End Batch 037 roads.


// Batch 038 water: validated local KRF bytes, decoded only in browser memory.
function requireWaterBounds(bounds, label) {
  if (!Array.isArray(bounds) || bounds.length !== 4) waterFail(`${label} bounds are invalid.`);
  const values = bounds.map((value, index) => finiteNumber(value, `${label} bound ${index}`, waterFail));
  if (values[2] < values[0] || values[3] < values[1]) waterFail(`${label} bounds are inverted.`);
  return values;
}

function validateWaterDatasetSource(dataset, expectedDatasetKey, manifestRelease, label) {
  const source = exactKeys(dataset, ["dataset_key", "feature_count", "release_content_sha256", "release_key"], label, waterFail);
  if (source.dataset_key !== expectedDatasetKey) waterFail(`${label} dataset key is invalid.`);
  if (!Number.isSafeInteger(source.feature_count) || source.feature_count < 1) waterFail(`${label} feature count is invalid.`);
  if (!isPlainObject(manifestRelease) || source.release_key !== manifestRelease.release_key || source.release_content_sha256 !== manifestRelease.release_content_sha256 || source.feature_count !== manifestRelease.feature_count) {
    waterFail(`${label} release does not match the validated package manifest.`);
  }
  return source;
}

function validateWaterIndex(index, manifest, payloadLength) {
  exactKeys(index, ["chunk_feature_limit", "format", "levels", "selection", "source", "srs_id", "version", "water_bounds"], "Water KRF index", waterFail);
  if (index.format !== WATER_FORMAT || index.version !== WATER_VERSION) waterFail(`Unsupported water KRF ${String(index.format)} version ${String(index.version)}.`);
  if (index.srs_id !== WATER_SRS_ID) waterFail(`Water KRF SRS ${String(index.srs_id)} is unsupported.`);
  if (!Number.isSafeInteger(index.chunk_feature_limit) || index.chunk_feature_limit < 1) waterFail("Water KRF chunk feature limit is invalid.");
  requireWaterBounds(index.water_bounds, "Water KRF");

  const selection = exactKeys(index.selection, ["coordinate_score_scale", "creek_basis", "fox_river_rule", "note"], "Water KRF selection", waterFail);
  if (selection.creek_basis !== "deterministic-coordinate-length-score") waterFail("Water KRF creek selection basis is incompatible.");
  if (selection.fox_river_rule !== "all-accepted-features-in-every-level") waterFail("Water KRF Fox River selection rule is incompatible.");
  if (!Number.isSafeInteger(selection.coordinate_score_scale) || selection.coordinate_score_scale < 1) waterFail("Water KRF coordinate score scale is invalid.");
  if (typeof selection.note !== "string") waterFail("Water KRF selection note is invalid.");

  const source = exactKeys(index.source, ["county", "datasets"], "Water KRF source", waterFail);
  const county = exactKeys(source.county, ["county_key", "fips_code", "name", "state_code"], "Water KRF county", waterFail);
  const manifestCounty = manifest?.database?.county;
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (county[key] !== EXPECTED_COUNTY[key] || county[key] !== manifestCounty?.[key]) waterFail(`Water KRF county ${key} does not match the validated package.`);
  }
  const datasets = exactKeys(source.datasets, ["creeks", "fox_river"], "Water KRF datasets", waterFail);
  const accepted = manifest?.database?.accepted_releases;
  const fox = validateWaterDatasetSource(datasets.fox_river, "water-fox-river", accepted?.["water-fox-river"], "Water KRF Fox River source");
  const creeks = validateWaterDatasetSource(datasets.creeks, "water-creeks", accepted?.["water-creeks"], "Water KRF creek source");

  if (!Array.isArray(index.levels) || index.levels.length !== WATER_LEVEL_KEYS.length) waterFail("Water KRF must contain exactly three LOD levels.");
  let expectedOffset = 0;
  let previousCreekCount = -1;
  for (let levelIndex = 0; levelIndex < WATER_LEVEL_KEYS.length; levelIndex += 1) {
    const level = exactKeys(index.levels[levelIndex], ["chunks", "creek_feature_count", "creek_length_fraction", "feature_count", "fox_river_feature_count", "key", "purpose", "rank", "simplification_tolerance_degrees", "source_vertex_count", "vertex_count"], `Water KRF level ${levelIndex}`, waterFail);
    if (level.key !== WATER_LEVEL_KEYS[levelIndex] || level.rank !== levelIndex) waterFail("Water KRF LOD order/rank is incompatible.");
    if (level.creek_length_fraction !== WATER_CREEK_FRACTIONS[levelIndex]) waterFail(`Water KRF level ${level.key} creek fraction is incompatible.`);
    if (!Number.isSafeInteger(level.fox_river_feature_count) || level.fox_river_feature_count !== fox.feature_count) waterFail(`Water KRF level ${level.key} does not contain every Fox River feature.`);
    if (!Number.isSafeInteger(level.creek_feature_count) || level.creek_feature_count < 0 || level.creek_feature_count < previousCreekCount || level.creek_feature_count > creeks.feature_count) waterFail(`Water KRF level ${level.key} creek count is invalid or non-monotonic.`);
    previousCreekCount = level.creek_feature_count;
    if (!Number.isSafeInteger(level.feature_count) || level.feature_count !== level.fox_river_feature_count + level.creek_feature_count) waterFail(`Water KRF level ${level.key} feature count is inconsistent.`);
    if (!Array.isArray(level.chunks) || level.chunks.length < 1) waterFail(`Water KRF level ${level.key} has no chunks.`);
    let chunkFeatures = 0;
    for (const chunk of level.chunks) {
      exactKeys(chunk, ["bounds", "feature_count", "length", "offset", "payload_sha256", "records_sha256", "uncompressed_length"], `Water KRF ${level.key} chunk`, waterFail);
      requireWaterBounds(chunk.bounds, `Water KRF ${level.key} chunk`);
      if (![chunk.feature_count, chunk.length, chunk.offset, chunk.uncompressed_length].every(Number.isSafeInteger)) waterFail(`Water KRF ${level.key} chunk integer fields are invalid.`);
      if (chunk.feature_count < 1 || chunk.feature_count > index.chunk_feature_limit || chunk.length < 1 || chunk.uncompressed_length < 1 || chunk.offset !== expectedOffset) waterFail(`Water KRF ${level.key} chunk framing is invalid.`);
      if (!/^[0-9a-f]{64}$/.test(chunk.payload_sha256) || !/^[0-9a-f]{64}$/.test(chunk.records_sha256)) waterFail(`Water KRF ${level.key} chunk hashes are invalid.`);
      expectedOffset += chunk.length;
      chunkFeatures += chunk.feature_count;
    }
    if (chunkFeatures !== level.feature_count) waterFail(`Water KRF level ${level.key} chunk feature count does not match its level count.`);
  }
  if (index.levels[0].creek_feature_count !== 0) waterFail("Water KRF overview level unexpectedly contains creek features.");
  if (index.levels[2].creek_feature_count !== creeks.feature_count || index.levels[2].feature_count !== fox.feature_count + creeks.feature_count) waterFail("Water KRF detail level is not the complete accepted water context.");
  if (expectedOffset !== payloadLength) waterFail("Water KRF payload length does not match the chunk inventory.");
  return index;
}

export function parseWaterContainer(bytes, manifest) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (data.byteLength < WATER_MAGIC.length + 8) waterFail("Water KRF is truncated before its index.");
  const magic = new TextDecoder("ascii", { fatal: true }).decode(data.slice(0, WATER_MAGIC.length));
  if (magic !== WATER_MAGIC) waterFail("Water KRF magic header is invalid.");
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const indexLength = readUint64BigEndian(view, WATER_MAGIC.length, waterFail, "Water KRF");
  const indexStart = WATER_MAGIC.length + 8;
  const indexEnd = indexStart + indexLength;
  if (indexEnd > data.byteLength) waterFail("Water KRF index is truncated.");
  let indexText;
  let index;
  try {
    indexText = new TextDecoder("utf-8", { fatal: true }).decode(data.slice(indexStart, indexEnd));
    index = JSON.parse(indexText);
  } catch (error) {
    waterFail("Water KRF index is not valid UTF-8 JSON.", String(error));
  }
  if (indexText !== canonicalize(index)) waterFail("Water KRF index is not canonical JSON.");
  const payload = data.slice(indexEnd);
  validateWaterIndex(index, manifest, payload.byteLength);
  return { index, payload };
}

async function inflateWaterZlib(compressed) {
  if (typeof DecompressionStream !== "function") fail("WATER_DECOMPRESSION_UNAVAILABLE", "This browser does not provide deflate decompression required by the water package.");
  try {
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch (error) {
    fail("WATER_DECOMPRESSION_FAILED", "A water KRF chunk could not be decompressed.", String(error));
  }
}

function validatePosition(point, label) {
  if (!Array.isArray(point) || point.length !== 2 || point.some((value) => typeof value !== "number" || !Number.isFinite(value))) waterFail(`${label} contains an invalid coordinate.`);
}

function validateWaterLine(line, label) {
  if (!Array.isArray(line) || line.length < 2) waterFail(`${label} contains a line with fewer than two points.`);
  for (const point of line) validatePosition(point, label);
}

function validateWaterRing(ring, label) {
  if (!Array.isArray(ring) || ring.length < 4) waterFail(`${label} contains a polygon ring with fewer than four points.`);
  for (const point of ring) validatePosition(point, label);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) waterFail(`${label} contains an open polygon ring.`);
}

function validateWaterRecord(record, label) {
  exactKeys(record, ["bounds", "coordinates", "dataset_key", "geometry_type", "source_feature_id"], label, waterFail);
  requireWaterBounds(record.bounds, label);
  if (typeof record.source_feature_id !== "string" || record.source_feature_id.length === 0) waterFail(`${label} source identity is invalid.`);
  if (record.dataset_key === "water-fox-river") {
    if (record.geometry_type !== "Polygon" && record.geometry_type !== "MultiPolygon") waterFail(`${label} Fox River geometry type is unsupported.`);
    const polygons = record.geometry_type === "Polygon" ? [record.coordinates] : record.coordinates;
    if (!Array.isArray(polygons) || polygons.length < 1) waterFail(`${label} contains no polygon coordinates.`);
    for (const polygon of polygons) {
      if (!Array.isArray(polygon) || polygon.length < 1) waterFail(`${label} contains an empty polygon.`);
      for (const ring of polygon) validateWaterRing(ring, label);
    }
  } else if (record.dataset_key === "water-creeks") {
    if (record.geometry_type !== "LineString" && record.geometry_type !== "MultiLineString") waterFail(`${label} creek geometry type is unsupported.`);
    const lines = record.geometry_type === "LineString" ? [record.coordinates] : record.coordinates;
    if (!Array.isArray(lines) || lines.length < 1) waterFail(`${label} contains no line coordinates.`);
    for (const line of lines) validateWaterLine(line, label);
  } else {
    waterFail(`${label} dataset key is unsupported.`);
  }
  return record;
}

export async function decodeWaterLevel(container, levelKey) {
  if (!WATER_LEVEL_KEYS.includes(levelKey)) waterFail(`Unknown water LOD level ${String(levelKey)}.`);
  const level = container.index.levels.find((candidate) => candidate.key === levelKey);
  if (!level) waterFail(`Water KRF does not contain level ${levelKey}.`);
  const records = [];
  let foxCount = 0;
  let creekCount = 0;
  for (const [chunkIndex, chunk] of level.chunks.entries()) {
    const compressed = container.payload.slice(chunk.offset, chunk.offset + chunk.length);
    if (await sha256Bytes(compressed) !== chunk.payload_sha256) waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} compressed hash is invalid.`);
    const raw = await inflateWaterZlib(compressed);
    if (raw.byteLength !== chunk.uncompressed_length) waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} decompressed length is invalid.`);
    if (await sha256Bytes(raw) !== chunk.records_sha256) waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} record hash is invalid.`);
    let text;
    let chunkRecords;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
      chunkRecords = JSON.parse(text);
    } catch (error) {
      waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} records are invalid JSON.`, String(error));
    }
    if (text !== canonicalize(chunkRecords)) waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} records are not canonical JSON.`);
    if (!Array.isArray(chunkRecords) || chunkRecords.length !== chunk.feature_count) waterFail(`Water KRF ${levelKey} chunk ${chunkIndex} feature count is invalid.`);
    for (let recordIndex = 0; recordIndex < chunkRecords.length; recordIndex += 1) {
      const record = validateWaterRecord(chunkRecords[recordIndex], `Water ${levelKey} record ${records.length + recordIndex}`);
      if (record.dataset_key === "water-fox-river") foxCount += 1;
      else creekCount += 1;
    }
    records.push(...chunkRecords);
  }
  if (records.length !== level.feature_count || foxCount !== level.fox_river_feature_count || creekCount !== level.creek_feature_count) waterFail(`Water KRF level ${levelKey} decoded feature counts are invalid.`);
  return records;
}

function ringPathData(ring) {
  const points = ring.slice(0, -1);
  const commands = [linePathData(points), "Z"];
  return commands.join(" ");
}

export function waterPathData(records) {
  const polygonPaths = [];
  const linePaths = [];
  for (const record of records) {
    if (record.dataset_key === "water-fox-river") {
      const polygons = record.geometry_type === "Polygon" ? [record.coordinates] : record.coordinates;
      for (const polygon of polygons) for (const ring of polygon) polygonPaths.push(ringPathData(ring));
    } else {
      const lines = record.geometry_type === "LineString" ? [record.coordinates] : record.coordinates;
      for (const line of lines) linePaths.push(linePathData(line));
    }
  }
  return { polygonPath: polygonPaths.join(" "), linePath: linePaths.join(" ") };
}

export function waterLevelForViewBox(viewBox, homeViewBox) {
  validateViewBox(viewBox); validateViewBox(homeViewBox);
  const zoom = homeViewBox[2] / viewBox[2];
  if (zoom >= WATER_DETAIL_ZOOM) return "detail";
  if (zoom >= WATER_CONTEXT_ZOOM) return "context";
  return "overview";
}

function createWaterLayerController(ui, container, homeViewBox, onLevelChange = () => {}) {
  const cache = new Map();
  const pending = new Map();
  let visibleLevel = null;
  let wantedLevel = null;
  let requestSerial = 0;

  const loadPaths = (levelKey) => {
    if (cache.has(levelKey)) return Promise.resolve(cache.get(levelKey));
    if (pending.has(levelKey)) return pending.get(levelKey);
    const work = decodeWaterLevel(container, levelKey).then((records) => {
      const paths = waterPathData(records);
      cache.set(levelKey, paths);
      pending.delete(levelKey);
      return paths;
    }, (error) => {
      pending.delete(levelKey);
      throw error;
    });
    pending.set(levelKey, work);
    return work;
  };

  const request = async (viewBox) => {
    const levelKey = waterLevelForViewBox(viewBox, homeViewBox);
    wantedLevel = levelKey;
    if (visibleLevel === levelKey) return;
    const serial = ++requestSerial;
    const paths = await loadPaths(levelKey);
    if (serial !== requestSerial || wantedLevel !== levelKey) return;
    ui.waterPolygons.setAttribute("d", paths.polygonPath);
    ui.waterLines.setAttribute("d", paths.linePath);
    ui.waterPolygons.dataset.level = levelKey;
    ui.waterLines.dataset.level = levelKey;
    visibleLevel = levelKey;
    onLevelChange(levelKey);
  };
  return { request, getVisibleLevel: () => visibleLevel };
}
// End Batch 038 water.


// Batch 039 buildings: project-identity KRF records, neutral rendering, browser memory only.
function requireBuildingBounds(bounds, label) {
  if (!Array.isArray(bounds) || bounds.length !== 4) buildingFail(`${label} bounds are invalid.`);
  const values = bounds.map((value, index) => finiteNumber(value, `${label} bound ${index}`, buildingFail));
  if (values[2] < values[0] || values[3] < values[1]) buildingFail(`${label} bounds are inverted.`);
  return values;
}

function validateBuildingIndex(index, manifest, payloadLength) {
  exactKeys(index, ["building_bounds", "chunk_feature_limit", "format", "identity", "levels", "selection", "source", "srs_id", "version"], "Building KRF index", buildingFail);
  if (index.format !== BUILDING_FORMAT || index.version !== BUILDING_VERSION) buildingFail(`Unsupported building KRF ${String(index.format)} version ${String(index.version)}.`);
  if (index.srs_id !== BUILDING_SRS_ID) buildingFail(`Building KRF SRS ${String(index.srs_id)} is unsupported.`);
  if (!Number.isSafeInteger(index.chunk_feature_limit) || index.chunk_feature_limit < 1) buildingFail("Building KRF chunk feature limit is invalid.");
  requireBuildingBounds(index.building_bounds, "Building KRF");

  const identity = exactKeys(index.identity, ["field", "kind", "note"], "Building KRF identity", buildingFail);
  if (identity.field !== "building_key" || identity.kind !== "kane-condo-project-building" || typeof identity.note !== "string") buildingFail("Building KRF project identity contract is incompatible.");
  const selection = exactKeys(index.selection, ["basis", "coordinate_score_scale", "note"], "Building KRF selection", buildingFail);
  if (selection.basis !== "deterministic-footprint-coordinate-area-score") buildingFail("Building KRF selection basis is incompatible.");
  if (!Number.isSafeInteger(selection.coordinate_score_scale) || selection.coordinate_score_scale < 1 || typeof selection.note !== "string") buildingFail("Building KRF selection metadata is invalid.");

  const source = exactKeys(index.source, ["county", "dataset_key", "feature_count", "release_content_sha256", "release_key"], "Building KRF source", buildingFail);
  if (source.dataset_key !== "buildings") buildingFail("Building KRF source dataset is not buildings.");
  if (!Number.isSafeInteger(source.feature_count) || source.feature_count < 1) buildingFail("Building KRF source feature count is invalid.");
  const county = exactKeys(source.county, ["county_key", "fips_code", "name", "state_code"], "Building KRF county", buildingFail);
  const manifestCounty = manifest?.database?.county;
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (county[key] !== EXPECTED_COUNTY[key] || county[key] !== manifestCounty?.[key]) buildingFail(`Building KRF county ${key} does not match the validated package.`);
  }
  const accepted = manifest?.database?.accepted_releases?.buildings;
  if (!isPlainObject(accepted) || source.release_key !== accepted.release_key || source.release_content_sha256 !== accepted.release_content_sha256 || source.feature_count !== accepted.feature_count) buildingFail("Building KRF release does not match the validated package manifest.");

  if (!Array.isArray(index.levels) || index.levels.length !== BUILDING_LEVEL_KEYS.length) buildingFail("Building KRF must contain exactly three LOD levels.");
  let expectedOffset = 0;
  let previousCount = 0;
  for (let levelIndex = 0; levelIndex < BUILDING_LEVEL_KEYS.length; levelIndex += 1) {
    const level = exactKeys(index.levels[levelIndex], ["chunks", "cumulative_area_fraction", "feature_count", "key", "purpose", "rank", "simplification_tolerance_degrees", "source_vertex_count", "vertex_count"], `Building KRF level ${levelIndex}`, buildingFail);
    if (level.key !== BUILDING_LEVEL_KEYS[levelIndex] || level.rank !== levelIndex) buildingFail("Building KRF LOD order/rank is incompatible.");
    if (level.cumulative_area_fraction !== BUILDING_AREA_FRACTIONS[levelIndex]) buildingFail(`Building KRF level ${level.key} area fraction is incompatible.`);
    if (!Number.isSafeInteger(level.feature_count) || level.feature_count < 1 || level.feature_count < previousCount || level.feature_count > source.feature_count) buildingFail(`Building KRF level ${level.key} feature count is invalid or non-monotonic.`);
    previousCount = level.feature_count;
    if (!Number.isSafeInteger(level.source_vertex_count) || !Number.isSafeInteger(level.vertex_count) || level.source_vertex_count < level.feature_count || level.vertex_count < level.feature_count || level.vertex_count > level.source_vertex_count) buildingFail(`Building KRF level ${level.key} vertex counts are invalid.`);
    const tolerance = finiteNumber(level.simplification_tolerance_degrees, `Building KRF level ${level.key} simplification tolerance`, buildingFail);
    if (tolerance < 0 || (levelIndex < 2 && !(tolerance > 0)) || (levelIndex === 2 && tolerance !== 0)) buildingFail(`Building KRF level ${level.key} simplification tolerance is incompatible.`);
    if (levelIndex === 2 && level.vertex_count !== level.source_vertex_count) buildingFail("Building KRF editing level does not preserve exact source vertex count.");
    if (!Array.isArray(level.chunks) || level.chunks.length < 1) buildingFail(`Building KRF level ${level.key} has no chunks.`);
    let chunkFeatures = 0;
    for (const chunk of level.chunks) {
      exactKeys(chunk, ["bounds", "feature_count", "length", "offset", "payload_sha256", "records_sha256", "uncompressed_length"], `Building KRF ${level.key} chunk`, buildingFail);
      requireBuildingBounds(chunk.bounds, `Building KRF ${level.key} chunk`);
      if (![chunk.feature_count, chunk.length, chunk.offset, chunk.uncompressed_length].every(Number.isSafeInteger)) buildingFail(`Building KRF ${level.key} chunk integer fields are invalid.`);
      if (chunk.feature_count < 1 || chunk.feature_count > index.chunk_feature_limit || chunk.length < 1 || chunk.uncompressed_length < 1 || chunk.offset !== expectedOffset) buildingFail(`Building KRF ${level.key} chunk framing is invalid.`);
      if (!/^[0-9a-f]{64}$/.test(chunk.payload_sha256) || !/^[0-9a-f]{64}$/.test(chunk.records_sha256)) buildingFail(`Building KRF ${level.key} chunk hashes are invalid.`);
      expectedOffset += chunk.length;
      chunkFeatures += chunk.feature_count;
    }
    if (chunkFeatures !== level.feature_count) buildingFail(`Building KRF level ${level.key} chunk feature count does not match its level count.`);
  }
  if (index.levels[1].feature_count !== source.feature_count) buildingFail("Building KRF neighborhood level is not the complete accepted building set.");
  if (index.levels[2].feature_count !== source.feature_count) buildingFail("Building KRF editing level is not the complete accepted building set.");
  if (expectedOffset !== payloadLength) buildingFail("Building KRF payload length does not match the chunk inventory.");
  return index;
}

export function parseBuildingContainer(bytes, manifest) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (data.byteLength < BUILDING_MAGIC.length + 8) buildingFail("Building KRF is truncated before its index.");
  const magic = new TextDecoder("ascii", { fatal: true }).decode(data.slice(0, BUILDING_MAGIC.length));
  if (magic !== BUILDING_MAGIC) buildingFail("Building KRF magic header is invalid.");
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const indexLength = readUint64BigEndian(view, BUILDING_MAGIC.length, buildingFail, "Building KRF");
  const indexStart = BUILDING_MAGIC.length + 8;
  const indexEnd = indexStart + indexLength;
  if (indexEnd > data.byteLength) buildingFail("Building KRF index is truncated.");
  let indexText;
  let index;
  try {
    indexText = new TextDecoder("utf-8", { fatal: true }).decode(data.slice(indexStart, indexEnd));
    index = JSON.parse(indexText);
  } catch (error) {
    buildingFail("Building KRF index is not valid UTF-8 JSON.", String(error));
  }
  if (indexText !== canonicalize(index)) buildingFail("Building KRF index is not canonical JSON.");
  const payload = data.slice(indexEnd);
  validateBuildingIndex(index, manifest, payload.byteLength);
  return { index, payload };
}

async function inflateBuildingZlib(compressed) {
  if (typeof DecompressionStream !== "function") fail("BUILDING_DECOMPRESSION_UNAVAILABLE", "This browser does not provide deflate decompression required by the building package.");
  try {
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch (error) {
    fail("BUILDING_DECOMPRESSION_FAILED", "A building KRF chunk could not be decompressed.", String(error));
  }
}

function validateBuildingPosition(point, label) {
  if (!Array.isArray(point) || point.length !== 2 || point.some((value) => typeof value !== "number" || !Number.isFinite(value))) buildingFail(`${label} contains an invalid coordinate.`);
}

function validateBuildingRing(ring, label) {
  if (!Array.isArray(ring) || ring.length < 4) buildingFail(`${label} contains a polygon ring with fewer than four points.`);
  for (const point of ring) validateBuildingPosition(point, label);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) buildingFail(`${label} contains an open polygon ring.`);
  const distinct = new Set(ring.slice(0, -1).map((point) => `${point[0]}\u0000${point[1]}`));
  if (distinct.size < 3) buildingFail(`${label} contains a polygon ring with fewer than three distinct vertices.`);
}

function validateBuildingRecord(record, label) {
  exactKeys(record, ["bounds", "building_key", "coordinates", "geometry_type", "source_feature_id"], label, buildingFail);
  requireBuildingBounds(record.bounds, label);
  if (typeof record.building_key !== "string" || record.building_key.length === 0) buildingFail(`${label} project building identity is invalid.`);
  if (typeof record.source_feature_id !== "string" || record.source_feature_id.length === 0) buildingFail(`${label} source identity is invalid.`);
  if (record.geometry_type !== "Polygon" && record.geometry_type !== "MultiPolygon") buildingFail(`${label} geometry type is unsupported.`);
  const polygons = record.geometry_type === "Polygon" ? [record.coordinates] : record.coordinates;
  if (!Array.isArray(polygons) || polygons.length < 1) buildingFail(`${label} contains no polygon coordinates.`);
  for (const polygon of polygons) {
    if (!Array.isArray(polygon) || polygon.length < 1) buildingFail(`${label} contains an empty polygon.`);
    for (const ring of polygon) validateBuildingRing(ring, label);
  }
  return record;
}

export async function decodeBuildingLevel(container, levelKey) {
  if (!BUILDING_LEVEL_KEYS.includes(levelKey)) buildingFail(`Unknown building LOD level ${String(levelKey)}.`);
  const level = container.index.levels.find((candidate) => candidate.key === levelKey);
  if (!level) buildingFail(`Building KRF does not contain level ${levelKey}.`);
  const records = [];
  const buildingKeys = new Set();
  const sourceIds = new Set();
  for (const [chunkIndex, chunk] of level.chunks.entries()) {
    const compressed = container.payload.slice(chunk.offset, chunk.offset + chunk.length);
    if (await sha256Bytes(compressed) !== chunk.payload_sha256) buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} compressed hash is invalid.`);
    const raw = await inflateBuildingZlib(compressed);
    if (raw.byteLength !== chunk.uncompressed_length) buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} decompressed length is invalid.`);
    if (await sha256Bytes(raw) !== chunk.records_sha256) buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} record hash is invalid.`);
    let text;
    let chunkRecords;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
      chunkRecords = JSON.parse(text);
    } catch (error) {
      buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} records are invalid JSON.`, String(error));
    }
    if (text !== canonicalize(chunkRecords)) buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} records are not canonical JSON.`);
    if (!Array.isArray(chunkRecords) || chunkRecords.length !== chunk.feature_count) buildingFail(`Building KRF ${levelKey} chunk ${chunkIndex} feature count is invalid.`);
    for (let recordIndex = 0; recordIndex < chunkRecords.length; recordIndex += 1) {
      const record = validateBuildingRecord(chunkRecords[recordIndex], `Building ${levelKey} record ${records.length + recordIndex}`);
      if (buildingKeys.has(record.building_key)) buildingFail(`Building KRF level ${levelKey} contains duplicate building_key ${record.building_key}.`);
      if (sourceIds.has(record.source_feature_id)) buildingFail(`Building KRF level ${levelKey} contains duplicate source identity ${record.source_feature_id}.`);
      buildingKeys.add(record.building_key);
      sourceIds.add(record.source_feature_id);
    }
    records.push(...chunkRecords);
  }
  if (records.length !== level.feature_count) buildingFail(`Building KRF level ${levelKey} decoded feature count is invalid.`);
  return records;
}

export function buildingPathData(records) {
  const paths = [];
  for (const record of records) {
    const polygons = record.geometry_type === "Polygon" ? [record.coordinates] : record.coordinates;
    for (const polygon of polygons) for (const ring of polygon) paths.push(ringPathData(ring));
  }
  return paths.join(" ");
}

export function buildingLevelForViewBox(viewBox, homeViewBox) {
  validateViewBox(viewBox); validateViewBox(homeViewBox);
  const zoom = homeViewBox[2] / viewBox[2];
  if (zoom >= BUILDING_EDITING_ZOOM) return "editing";
  if (zoom >= BUILDING_NEIGHBORHOOD_ZOOM) return "neighborhood";
  return "context";
}

// Batch 040 classification colors: sparse validated snapshot joined by project building_key.
export async function parseClassificationSnapshot(bytes, manifest, buildingIndex) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let text;
  let document;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(data);
    document = JSON.parse(text);
  } catch (error) {
    classificationFail("Classification snapshot is not valid UTF-8 JSON.", String(error));
  }
  if (text !== canonicalize(document)) classificationFail("Classification snapshot is not canonical JSON.");
  const snapshot = exactKeys(document, ["classifications", "default_classification", "explicit", "format", "identity", "source", "version"], "Classification snapshot", classificationFail);
  if (snapshot.format !== CLASSIFICATION_FORMAT || snapshot.version !== CLASSIFICATION_VERSION) classificationFail(`Unsupported classification snapshot ${String(snapshot.format)} version ${String(snapshot.version)}.`);
  if (!Array.isArray(snapshot.classifications) || snapshot.classifications.length !== CLASSIFICATION_VALUES.length || snapshot.classifications.some((value, index) => value !== CLASSIFICATION_VALUES[index])) classificationFail("Classification snapshot class contract is incompatible.");
  if (snapshot.default_classification !== "unclassified") classificationFail("Classification snapshot default classification is not unclassified.");

  const identity = exactKeys(snapshot.identity, ["field", "kind", "render_building_count", "render_identity_sha256"], "Classification snapshot identity", classificationFail);
  if (identity.field !== "building_key" || identity.kind !== "kane-condo-project-building") classificationFail("Classification snapshot project identity contract is incompatible.");
  if (!Number.isSafeInteger(identity.render_building_count) || identity.render_building_count < 1) classificationFail("Classification snapshot render building count is invalid.");
  if (typeof identity.render_identity_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(identity.render_identity_sha256)) classificationFail("Classification snapshot render identity SHA-256 is invalid.");

  const source = exactKeys(snapshot.source, ["dataset_key", "feature_count", "release_content_sha256", "release_key"], "Classification snapshot source", classificationFail);
  if (source.dataset_key !== "buildings" || !Number.isSafeInteger(source.feature_count) || source.feature_count !== identity.render_building_count) classificationFail("Classification snapshot source identity is inconsistent.");
  if (typeof source.release_key !== "string" || source.release_key.length === 0 || typeof source.release_content_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(source.release_content_sha256)) classificationFail("Classification snapshot building release identity is invalid.");
  const accepted = manifest?.database?.accepted_releases?.buildings;
  if (!isPlainObject(accepted) || source.release_key !== accepted.release_key || source.release_content_sha256 !== accepted.release_content_sha256 || source.feature_count !== accepted.feature_count) classificationFail("Classification snapshot building release does not match the validated package manifest.");
  if (!isPlainObject(buildingIndex?.source) || source.release_key !== buildingIndex.source.release_key || source.release_content_sha256 !== buildingIndex.source.release_content_sha256 || source.feature_count !== buildingIndex.source.feature_count) classificationFail("Classification snapshot does not match the validated building KRF identity.");

  const explicit = exactKeys(snapshot.explicit, ["count", "counts", "non_rendered_explicit_count", "records", "records_sha256"], "Classification snapshot explicit state", classificationFail);
  if (!Number.isSafeInteger(explicit.count) || explicit.count < 0 || explicit.count > identity.render_building_count) classificationFail("Classification snapshot explicit count is invalid.");
  if (!Number.isSafeInteger(explicit.non_rendered_explicit_count) || explicit.non_rendered_explicit_count < 0) classificationFail("Classification snapshot non-rendered explicit count is invalid.");
  if (!Array.isArray(explicit.records) || explicit.records.length !== explicit.count) classificationFail("Classification snapshot explicit records are invalid.");
  if (typeof explicit.records_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(explicit.records_sha256)) classificationFail("Classification snapshot explicit-record SHA-256 is invalid.");

  const lookup = new Map();
  let previousKey = null;
  const expectedCounts = { unclassified: 0, other: 0, condominium: 0, apartments: 0 };
  for (const [index, record] of explicit.records.entries()) {
    if (!Array.isArray(record) || record.length !== 2) classificationFail(`Classification snapshot record ${index} is not a two-item array.`);
    const [buildingKey, classification] = record;
    if (typeof buildingKey !== "string" || !BUILDING_KEY_PATTERN.test(buildingKey)) classificationFail(`Classification snapshot record ${index} building_key is invalid.`);
    if (!EXPLICIT_CLASSIFICATIONS.includes(classification)) classificationFail(`Classification snapshot record ${index} classification is invalid.`);
    if (previousKey !== null && buildingKey <= previousKey) classificationFail("Classification snapshot records are not strictly sorted by building_key.");
    previousKey = buildingKey;
    lookup.set(buildingKey, classification);
    expectedCounts[classification] += 1;
  }
  expectedCounts.unclassified = identity.render_building_count - explicit.records.length;
  const counts = exactKeys(explicit.counts, CLASSIFICATION_VALUES, "Classification snapshot counts", classificationFail);
  for (const classification of CLASSIFICATION_VALUES) {
    if (!Number.isSafeInteger(counts[classification]) || counts[classification] < 0 || counts[classification] !== expectedCounts[classification]) classificationFail(`Classification snapshot ${classification} count is inconsistent.`);
  }
  const computedRecordsSha = await sha256Bytes(new TextEncoder().encode(canonicalize(explicit.records)));
  if (computedRecordsSha !== explicit.records_sha256) classificationFail("Classification snapshot explicit-record SHA-256 is invalid.");

  const compatibility = manifest?.classification_compatibility;
  if (!isPlainObject(compatibility) || compatibility.building_component !== "buildings" || compatibility.classification_component !== "classification_snapshot") classificationFail("Package classification compatibility metadata is unavailable or incompatible.");
  if (identity.render_building_count !== compatibility.render_building_count || identity.render_identity_sha256 !== compatibility.render_identity_sha256 || explicit.count !== compatibility.explicit_count || explicit.records_sha256 !== compatibility.records_sha256 || source.release_key !== compatibility.source_release_key || source.release_content_sha256 !== compatibility.source_release_content_sha256) classificationFail("Classification snapshot does not match package classification compatibility metadata.");

  return { document: snapshot, lookup };
}

export function classificationForBuildingKey(lookup, buildingKey) {
  const value = lookup instanceof Map ? lookup.get(buildingKey) : undefined;
  return EXPLICIT_CLASSIFICATIONS.includes(value) ? value : "unclassified";
}

export function buildingClassificationPathData(records, lookup) {
  const paths = { unclassified: [], other: [], condominium: [], apartments: [] };
  for (const record of records) {
    const classification = classificationForBuildingKey(lookup, record.building_key);
    const polygons = record.geometry_type === "Polygon" ? [record.coordinates] : record.coordinates;
    for (const polygon of polygons) for (const ring of polygon) paths[classification].push(ringPathData(ring));
  }
  return Object.fromEntries(CLASSIFICATION_VALUES.map((classification) => [classification, paths[classification].join(" ")]));
}
// End Batch 040 classification colors.

function createBuildingLayerController(ui, container, homeViewBox, classificationLookup, onLevelChange = () => {}) {
  const cache = new Map();
  const pending = new Map();
  let visibleLevel = null;
  let visibleRecords = [];
  let wantedLevel = null;
  let requestSerial = 0;

  const loadLevel = (levelKey) => {
    if (cache.has(levelKey)) return Promise.resolve(cache.get(levelKey));
    if (pending.has(levelKey)) return pending.get(levelKey);
    const work = decodeBuildingLevel(container, levelKey).then((records) => {
      const decoded = { records, paths: buildingClassificationPathData(records, classificationLookup) };
      cache.set(levelKey, decoded);
      pending.delete(levelKey);
      return decoded;
    }, (error) => {
      pending.delete(levelKey);
      throw error;
    });
    pending.set(levelKey, work);
    return work;
  };

  const request = async (viewBox) => {
    const levelKey = buildingLevelForViewBox(viewBox, homeViewBox);
    wantedLevel = levelKey;
    if (visibleLevel === levelKey) return;
    const serial = ++requestSerial;
    const decoded = await loadLevel(levelKey);
    if (serial !== requestSerial || wantedLevel !== levelKey) return;
    for (const classification of CLASSIFICATION_VALUES) {
      const path = ui.buildingPaths[classification];
      path.setAttribute("d", decoded.paths[classification]);
      path.dataset.level = levelKey;
    }
    visibleRecords = decoded.records;
    visibleLevel = levelKey;
    onLevelChange(levelKey);
  };
  return { request, getVisibleLevel: () => visibleLevel, getVisibleRecords: () => [...visibleRecords] };
}
// End Batch 039 buildings.

async function loadConfig() {
  let response;
  try { response = await fetch("/config.json", { cache: "no-store" }); }
  catch (error) { fail("CONFIG_UNAVAILABLE", "Local runtime configuration could not be loaded.", String(error)); }
  if (!response.ok) fail("CONFIG_UNAVAILABLE", `Local runtime configuration returned HTTP ${response.status}.`);
  try { return validateLocalConfig(await response.json()); }
  catch (error) {
    if (error instanceof PackageValidationError) throw error;
    fail("CONFIG_INVALID_JSON", "Local runtime configuration is not valid JSON.", String(error));
  }
}

async function loadCountyOverview(config, manifest) {
  const component = manifest.components.find((item) => item.role === "county_overview");
  if (!component) fail("OVERVIEW_INCOMPATIBLE", "Validated package has no county overview component.");
  const manifestUrl = new URL(config.package_manifest_url, globalThis.location.href);
  const overviewUrl = new URL(component.filename, manifestUrl);
  let response;
  try { response = await fetch(overviewUrl, { cache: "no-store" }); }
  catch (error) { fail("OVERVIEW_UNAVAILABLE", "County overview could not be loaded.", String(error)); }
  if (!response.ok) fail("OVERVIEW_UNAVAILABLE", `County overview returned HTTP ${response.status}.`, overviewUrl.href);
  try { return validateCountyOverview(await response.json(), manifest); }
  catch (error) {
    if (error instanceof PackageValidationError) throw error;
    fail("OVERVIEW_INVALID_JSON", "County overview is not valid JSON.", String(error));
  }
}

function getUi(doc) {
  return {
    indicator: doc.querySelector("#status-indicator"), title: doc.querySelector("#status-title"), message: doc.querySelector("#status-message"),
    details: doc.querySelector("#package-details"), detailCounty: doc.querySelector("#detail-county"), detailCreated: doc.querySelector("#detail-created"), detailIdentity: doc.querySelector("#detail-identity"),
    errorDetail: doc.querySelector("#error-detail"), mapPanel: doc.querySelector("#map-panel"), mapCanvas: doc.querySelector("#map-canvas"), countyPath: doc.querySelector("#county-outline"), waterPolygons: doc.querySelector("#water-polygons"), waterLines: doc.querySelector("#water-lines"), buildingPaths: { unclassified: doc.querySelector("#building-unclassified"), other: doc.querySelector("#building-other"), condominium: doc.querySelector("#building-condominium"), apartments: doc.querySelector("#building-apartments") }, roadPath: doc.querySelector("#road-network"), mapCaption: doc.querySelector("#map-caption"), resetView: doc.querySelector("#reset-county-view"),
  };
}

function setStatus(ui, state, heading, text) { ui.indicator.dataset.state = state; ui.title.textContent = heading; ui.message.textContent = text; }
function showError(ui, error) {
  const known = error instanceof PackageValidationError;
  setStatus(ui, "error", `Package unavailable: ${known ? error.code : "UNEXPECTED_APPLICATION_ERROR"}`, known ? error.message : "Unexpected error while opening the local map.");
  ui.details.hidden = true; ui.mapPanel.hidden = true; ui.errorDetail.hidden = false; ui.errorDetail.textContent = known && error.detail ? error.detail : String(error);
  document.documentElement.dataset.packageState = "error";
}

function renderCountyOverview(ui, overview) {
  const viewBox = overviewViewBox(overview.fit.bounds);
  applyViewBox(ui.mapCanvas, viewBox);
  ui.mapCanvas.setAttribute("preserveAspectRatio", "xMidYMid meet");
  ui.countyPath.setAttribute("d", overviewPathData(overview.outline.rings));
  ui.mapCaption.textContent = "Loading county road, water, and building context layers";
  ui.mapPanel.hidden = false;
  return viewBox;
}

async function start(doc = document) {
  const ui = getUi(doc);
  try {
    setStatus(ui, "checking", "Checking local package", "Loading local configuration.");
    const config = await loadConfig();
    let roadsBytes = null;
    let waterBytes = null;
    let buildingsBytes = null;
    let classificationBytes = null;
    const manifest = await validateLocalPackage(config, {
      onProgress(progress) { setStatus(ui, "checking", "Checking local package", progress.message); },
      onComponent(component, bytes) {
        if (component.role === "roads") roadsBytes = bytes;
        if (component.role === "water") waterBytes = bytes;
        if (component.role === "buildings") buildingsBytes = bytes;
        if (component.role === "classification_snapshot") classificationBytes = bytes;
      },
    });
    if (!roadsBytes) fail("ROAD_INCOMPATIBLE", "Validated package did not expose its road component bytes.");
    if (!waterBytes) fail("WATER_INCOMPATIBLE", "Validated package did not expose its water component bytes.");
    if (!buildingsBytes) fail("BUILDING_INCOMPATIBLE", "Validated package did not expose its building component bytes.");
    if (!classificationBytes) fail("CLASSIFICATION_INCOMPATIBLE", "Validated package did not expose its classification snapshot bytes.");
    const county = manifest.database.county;
    ui.detailCounty.textContent = `${county.name}, ${county.state_code}`;
    ui.detailCreated.textContent = manifest.created_at;
    ui.detailIdentity.textContent = manifest.identities.package_content_sha256;
    ui.details.hidden = false; ui.errorDetail.hidden = true;

    setStatus(ui, "checking", "Opening Kane County", "Loading the validated county overview.");
    const overview = await loadCountyOverview(config, manifest);
    const homeViewBox = renderCountyOverview(ui, overview);

    setStatus(ui, "checking", "Opening Kane County", "Decoding county road, water, building, and classification layers.");
    const roadContainer = parseRoadContainer(roadsBytes, manifest);
    const waterContainer = parseWaterContainer(waterBytes, manifest);
    const buildingContainer = parseBuildingContainer(buildingsBytes, manifest);
    const classification = await parseClassificationSnapshot(classificationBytes, manifest, buildingContainer.index);
    const visibleLevels = { road: null, water: null, building: null };
    const updateCaption = () => {
      const road = visibleLevels.road ?? "loading";
      const water = visibleLevels.water ?? "loading";
      const building = visibleLevels.building ?? "loading";
      ui.mapCaption.textContent = `Road detail: ${road} • Water detail: ${water} • Building detail: ${building} • drag to pan • wheel or trackpad to zoom`;
    };
    const roads = createRoadLayerController(ui, roadContainer, homeViewBox, (level) => { visibleLevels.road = level; updateCaption(); });
    const water = createWaterLayerController(ui, waterContainer, homeViewBox, (level) => { visibleLevels.water = level; updateCaption(); });
    const buildings = createBuildingLayerController(ui, buildingContainer, homeViewBox, classification.lookup, (level) => { visibleLevels.building = level; updateCaption(); });
    await Promise.all([roads.request(homeViewBox), water.request(homeViewBox), buildings.request(homeViewBox)]);
    installMapNavigation(ui, homeViewBox, (viewBox) => {
      roads.request(viewBox).catch((error) => showError(ui, error));
      water.request(viewBox).catch((error) => showError(ui, error));
      buildings.request(viewBox).catch((error) => showError(ui, error));
    });

    setStatus(ui, "ready", "Kane County ready", "Continuous navigation with progressive local road, water, and classification-colored building rendering is available without data writes.");
    doc.documentElement.dataset.packageState = "ready";
  } catch (error) { showError(ui, error); }
}

if (typeof document !== "undefined") start();
