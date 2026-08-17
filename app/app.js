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

function overviewFail(message, detail = null) {
  throw new PackageValidationError("OVERVIEW_INCOMPATIBLE", message, detail);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) {
    overviewFail(`${label} is not an object.`);
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    overviewFail(
      `${label} fields are incompatible.`,
      `Expected: ${wanted.join(", ")}\nFound: ${actual.join(", ")}`,
    );
  }
  return value;
}

function finiteNumber(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    overviewFail(`${label} is not a finite number.`);
  }
  return value;
}

function almostEqual(left, right, tolerance = 1e-12) {
  return Math.abs(left - right) <= tolerance * Math.max(1, Math.abs(left), Math.abs(right));
}

export function validateCountyOverview(document, manifest) {
  const overview = exactKeys(
    document,
    ["county", "fit", "format", "outline", "source", "srs_id", "version"],
    "County overview",
  );
  if (overview.format !== OVERVIEW_FORMAT || overview.version !== OVERVIEW_VERSION) {
    overviewFail(
      `Unsupported county overview ${String(overview.format)} version ${String(overview.version)}.`,
      `Expected ${OVERVIEW_FORMAT} version ${OVERVIEW_VERSION}.`,
    );
  }
  if (overview.srs_id !== OVERVIEW_SRS_ID) {
    overviewFail(`County overview SRS ${String(overview.srs_id)} is unsupported.`);
  }

  const county = exactKeys(
    overview.county,
    ["county_key", "fips_code", "name", "state_code"],
    "County overview county",
  );
  const manifestCounty = manifest?.database?.county;
  if (!isPlainObject(manifestCounty)) {
    overviewFail("Validated package manifest does not expose county identity.");
  }
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (county[key] !== EXPECTED_COUNTY[key] || county[key] !== manifestCounty[key]) {
      overviewFail(`County overview ${key} does not match the validated Kane County package.`);
    }
  }

  const source = exactKeys(
    overview.source,
    [
      "dataset_key",
      "geometry_sha256",
      "geometry_type",
      "release_content_sha256",
      "release_key",
      "source_feature_id",
    ],
    "County overview source",
  );
  if (source.dataset_key !== "county-boundary") {
    overviewFail("County overview does not identify the county-boundary dataset.");
  }
  if (source.geometry_type !== "Polygon" && source.geometry_type !== "MultiPolygon") {
    overviewFail(`County overview geometry type ${String(source.geometry_type)} is unsupported.`);
  }
  const acceptedBoundary = manifest?.database?.accepted_releases?.["county-boundary"];
  if (
    !isPlainObject(acceptedBoundary) ||
    source.release_key !== acceptedBoundary.release_key ||
    source.release_content_sha256 !== acceptedBoundary.release_content_sha256
  ) {
    overviewFail("County overview boundary release does not match the validated package manifest.");
  }

  const fit = exactKeys(overview.fit, ["bounds", "center", "height", "width"], "County overview fit");
  if (!Array.isArray(fit.bounds) || fit.bounds.length !== 4) {
    overviewFail("County overview fit bounds are invalid.");
  }
  const [minX, minY, maxX, maxY] = fit.bounds.map((value, index) => finiteNumber(value, `County overview bound ${index}`));
  if (!(maxX > minX) || !(maxY > minY)) {
    overviewFail("County overview fit bounds do not describe a positive extent.");
  }
  if (!Array.isArray(fit.center) || fit.center.length !== 2) {
    overviewFail("County overview fit center is invalid.");
  }
  const centerX = finiteNumber(fit.center[0], "County overview center longitude");
  const centerY = finiteNumber(fit.center[1], "County overview center latitude");
  const width = finiteNumber(fit.width, "County overview fit width");
  const height = finiteNumber(fit.height, "County overview fit height");
  if (
    !almostEqual(width, maxX - minX) ||
    !almostEqual(height, maxY - minY) ||
    !almostEqual(centerX, (minX + maxX) / 2) ||
    !almostEqual(centerY, (minY + maxY) / 2)
  ) {
    overviewFail("County overview fit metadata is inconsistent with its exact bounds.");
  }

  const outline = exactKeys(
    overview.outline,
    [
      "kind",
      "ring_count",
      "rings",
      "simplification_tolerance_degrees",
      "source_interior_ring_count",
      "source_vertex_count",
      "vertex_count",
    ],
    "County overview outline",
  );
  if (outline.kind !== "exterior-rings" || !Array.isArray(outline.rings)) {
    overviewFail("County overview outline is not an exterior-ring collection.");
  }
  if (!Number.isSafeInteger(outline.ring_count) || outline.ring_count < 1 || outline.ring_count !== outline.rings.length) {
    overviewFail("County overview ring count is invalid.");
  }
  for (let ringIndex = 0; ringIndex < outline.rings.length; ringIndex += 1) {
    const ring = outline.rings[ringIndex];
    if (!Array.isArray(ring) || ring.length < 4) {
      overviewFail(`County overview ring ${ringIndex} is too short.`);
    }
    for (let pointIndex = 0; pointIndex < ring.length; pointIndex += 1) {
      const point = ring[pointIndex];
      if (!Array.isArray(point) || point.length !== 2) {
        overviewFail(`County overview ring ${ringIndex} point ${pointIndex} is invalid.`);
      }
      const x = finiteNumber(point[0], `County overview ring ${ringIndex} longitude`);
      const y = finiteNumber(point[1], `County overview ring ${ringIndex} latitude`);
      if (x < minX - 1e-12 || x > maxX + 1e-12 || y < minY - 1e-12 || y > maxY + 1e-12) {
        overviewFail(`County overview ring ${ringIndex} extends outside the exact source bounds.`);
      }
    }
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      overviewFail(`County overview ring ${ringIndex} is not closed.`);
    }
  }

  return overview;
}

export function overviewViewBox(bounds, paddingFraction = 0.04) {
  if (!Array.isArray(bounds) || bounds.length !== 4) {
    throw new TypeError("bounds must contain four numbers");
  }
  const [minX, minY, maxX, maxY] = bounds;
  const width = maxX - minX;
  const height = maxY - minY;
  if (!(width > 0) || !(height > 0) || !(paddingFraction >= 0)) {
    throw new RangeError("bounds and padding must describe a positive extent");
  }
  const padX = width * paddingFraction;
  const padY = height * paddingFraction;
  return [minX - padX, -(maxY + padY), width + (2 * padX), height + (2 * padY)];
}

function formatCoordinate(value) {
  return Number(value).toString();
}

export function overviewPathData(rings) {
  return rings.map((ring) => {
    const points = ring.slice(0, -1);
    if (points.length < 3) {
      throw new RangeError("overview ring must contain at least three distinct vertices");
    }
    const [first, ...rest] = points;
    const commands = [`M ${formatCoordinate(first[0])} ${formatCoordinate(-first[1])}`];
    for (const point of rest) {
      commands.push(`L ${formatCoordinate(point[0])} ${formatCoordinate(-point[1])}`);
    }
    commands.push("Z");
    return commands.join(" ");
  }).join(" ");
}

// Batch 036 navigation: pure viewport state only.
function validateViewBox(viewBox) {
  if (!Array.isArray(viewBox) || viewBox.length !== 4 || viewBox.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
    throw new TypeError("viewBox must contain four finite numbers");
  }
  if (!(viewBox[2] > 0) || !(viewBox[3] > 0)) {
    throw new RangeError("viewBox width and height must be positive");
  }
  return viewBox;
}

export function viewportMetrics(viewBox, pixelWidth, pixelHeight) {
  validateViewBox(viewBox);
  if (!(pixelWidth > 0) || !(pixelHeight > 0)) {
    throw new RangeError("viewport pixel dimensions must be positive");
  }
  const scale = Math.min(pixelWidth / viewBox[2], pixelHeight / viewBox[3]);
  const renderedWidth = viewBox[2] * scale;
  const renderedHeight = viewBox[3] * scale;
  return {
    scale,
    offsetX: (pixelWidth - renderedWidth) / 2,
    offsetY: (pixelHeight - renderedHeight) / 2,
  };
}

export function clientPointToWorld(viewBox, pixelWidth, pixelHeight, pixelX, pixelY) {
  const metrics = viewportMetrics(viewBox, pixelWidth, pixelHeight);
  return [
    viewBox[0] + ((pixelX - metrics.offsetX) / metrics.scale),
    viewBox[1] + ((pixelY - metrics.offsetY) / metrics.scale),
  ];
}

export function panViewBoxByPixels(viewBox, pixelWidth, pixelHeight, deltaX, deltaY) {
  validateViewBox(viewBox);
  const metrics = viewportMetrics(viewBox, pixelWidth, pixelHeight);
  return [
    viewBox[0] - (deltaX / metrics.scale),
    viewBox[1] - (deltaY / metrics.scale),
    viewBox[2],
    viewBox[3],
  ];
}

export function zoomViewBoxAt(viewBox, homeViewBox, anchorX, anchorY, requestedSizeScale) {
  validateViewBox(viewBox);
  validateViewBox(homeViewBox);
  if (![anchorX, anchorY, requestedSizeScale].every((value) => typeof value === "number" && Number.isFinite(value))) {
    throw new TypeError("zoom anchor and scale must be finite numbers");
  }
  if (!(requestedSizeScale > 0)) {
    throw new RangeError("zoom scale must be positive");
  }

  const currentZoom = homeViewBox[2] / viewBox[2];
  const requestedZoom = currentZoom / requestedSizeScale;
  const targetZoom = Math.min(NAVIGATION_MAX_ZOOM, Math.max(NAVIGATION_MIN_ZOOM, requestedZoom));
  const actualSizeScale = currentZoom / targetZoom;
  const nextWidth = viewBox[2] * actualSizeScale;
  const nextHeight = viewBox[3] * actualSizeScale;
  return [
    anchorX - ((anchorX - viewBox[0]) * actualSizeScale),
    anchorY - ((anchorY - viewBox[1]) * actualSizeScale),
    nextWidth,
    nextHeight,
  ];
}

export function wheelSizeScale(deltaY) {
  if (typeof deltaY !== "number" || !Number.isFinite(deltaY)) {
    throw new TypeError("wheel delta must be finite");
  }
  const boundedDelta = Math.max(-240, Math.min(240, deltaY));
  return Math.exp(boundedDelta * WHEEL_SENSITIVITY);
}

export function resetViewBox(homeViewBox) {
  validateViewBox(homeViewBox);
  return [...homeViewBox];
}

function parseViewBox(text) {
  const values = String(text).trim().split(/\s+/).map(Number);
  return validateViewBox(values);
}

function applyViewBox(canvas, viewBox) {
  canvas.setAttribute("viewBox", validateViewBox(viewBox).join(" "));
}

function installMapNavigation(ui, homeViewBox) {
  const canvas = ui.mapCanvas;
  let currentViewBox = resetViewBox(homeViewBox);
  let drag = null;

  const update = (viewBox) => {
    currentViewBox = validateViewBox(viewBox);
    applyViewBox(canvas, currentViewBox);
  };

  const reset = () => update(resetViewBox(homeViewBox));
  ui.resetView.disabled = false;
  ui.resetView.addEventListener("click", reset);

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !event.isPrimary) {
      return;
    }
    event.preventDefault();
    drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    canvas.classList.add("is-panning");
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const deltaX = event.clientX - drag.x;
    const deltaY = event.clientY - drag.y;
    if (deltaX !== 0 || deltaY !== 0) {
      update(panViewBoxByPixels(currentViewBox, rect.width, rect.height, deltaX, deltaY));
      drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    }
  });

  const finishDrag = (event) => {
    if (!drag || event.pointerId !== drag.pointerId) {
      return;
    }
    if (canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
    drag = null;
    canvas.classList.remove("is-panning");
  };
  canvas.addEventListener("pointerup", finishDrag);
  canvas.addEventListener("pointercancel", finishDrag);

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const [anchorX, anchorY] = clientPointToWorld(
      currentViewBox,
      rect.width,
      rect.height,
      event.clientX - rect.left,
      event.clientY - rect.top,
    );
    update(zoomViewBoxAt(currentViewBox, homeViewBox, anchorX, anchorY, wheelSizeScale(event.deltaY)));
  }, { passive: false });

  return {
    getViewBox() {
      return [...currentViewBox];
    },
    reset,
  };
}
// End Batch 036 navigation.

async function loadConfig() {
  let response;
  try {
    response = await fetch("/config.json", { cache: "no-store" });
  } catch (error) {
    throw new PackageValidationError("CONFIG_UNAVAILABLE", "Local runtime configuration could not be loaded.", String(error));
  }
  if (!response.ok) {
    throw new PackageValidationError("CONFIG_UNAVAILABLE", `Local runtime configuration returned HTTP ${response.status}.`);
  }
  let document;
  try {
    document = await response.json();
  } catch (error) {
    throw new PackageValidationError("CONFIG_INVALID_JSON", "Local runtime configuration is not valid JSON.", String(error));
  }
  return validateLocalConfig(document);
}

async function loadCountyOverview(config, manifest) {
  const overviewComponent = manifest.components.find((component) => component.role === "county_overview");
  if (!overviewComponent) {
    throw new PackageValidationError("OVERVIEW_INCOMPATIBLE", "Validated package has no county overview component.");
  }
  const manifestUrl = new URL(config.package_manifest_url, globalThis.location.href);
  const overviewUrl = new URL(overviewComponent.filename, manifestUrl);
  let response;
  try {
    response = await fetch(overviewUrl, { cache: "no-store" });
  } catch (error) {
    throw new PackageValidationError("OVERVIEW_UNAVAILABLE", "County overview could not be loaded.", String(error));
  }
  if (!response.ok) {
    throw new PackageValidationError("OVERVIEW_UNAVAILABLE", `County overview returned HTTP ${response.status}.`, overviewUrl.href);
  }
  let document;
  try {
    document = await response.json();
  } catch (error) {
    throw new PackageValidationError("OVERVIEW_INVALID_JSON", "County overview is not valid JSON.", String(error));
  }
  return validateCountyOverview(document, manifest);
}

function getUi(doc) {
  return {
    indicator: doc.querySelector("#status-indicator"),
    title: doc.querySelector("#status-title"),
    message: doc.querySelector("#status-message"),
    details: doc.querySelector("#package-details"),
    detailCounty: doc.querySelector("#detail-county"),
    detailCreated: doc.querySelector("#detail-created"),
    detailIdentity: doc.querySelector("#detail-identity"),
    errorDetail: doc.querySelector("#error-detail"),
    mapPanel: doc.querySelector("#map-panel"),
    mapCanvas: doc.querySelector("#map-canvas"),
    countyPath: doc.querySelector("#county-outline"),
    mapCaption: doc.querySelector("#map-caption"),
    resetView: doc.querySelector("#reset-county-view"),
  };
}

function setStatus(ui, state, heading, text) {
  ui.indicator.dataset.state = state;
  ui.title.textContent = heading;
  ui.message.textContent = text;
}

function showError(ui, error) {
  const known = error instanceof PackageValidationError;
  const code = known ? error.code : "UNEXPECTED_APPLICATION_ERROR";
  const text = known ? error.message : "Unexpected error while opening the local map.";
  setStatus(ui, "error", `Package unavailable: ${code}`, text);
  ui.details.hidden = true;
  ui.mapPanel.hidden = true;
  ui.errorDetail.hidden = false;
  ui.errorDetail.textContent = known && error.detail ? error.detail : String(error);
  document.documentElement.dataset.packageState = "error";
}

function renderCountyOverview(ui, overview) {
  const viewBox = overviewViewBox(overview.fit.bounds);
  applyViewBox(ui.mapCanvas, viewBox);
  ui.mapCanvas.setAttribute("preserveAspectRatio", "xMidYMid meet");
  ui.countyPath.setAttribute("d", overviewPathData(overview.outline.rings));
  ui.mapCaption.textContent = "Drag to pan • wheel or trackpad to zoom";
  installMapNavigation(ui, viewBox);
  ui.mapPanel.hidden = false;
}

async function start(doc = document) {
  const ui = getUi(doc);
  try {
    setStatus(ui, "checking", "Checking local package", "Loading local configuration.");
    const config = await loadConfig();
    const manifest = await validateLocalPackage(config, {
      onProgress(progress) {
        setStatus(ui, "checking", "Checking local package", progress.message);
      },
    });
    const county = manifest.database.county;
    ui.detailCounty.textContent = `${county.name}, ${county.state_code}`;
    ui.detailCreated.textContent = manifest.created_at;
    ui.detailIdentity.textContent = manifest.identities.package_content_sha256;
    ui.details.hidden = false;
    ui.errorDetail.hidden = true;

    setStatus(ui, "checking", "Opening Kane County", "Loading the validated county overview.");
    const overview = await loadCountyOverview(config, manifest);
    renderCountyOverview(ui, overview);

    setStatus(ui, "ready", "Kane County ready", "Continuous local pan and zoom are available without data writes.");
    doc.documentElement.dataset.packageState = "ready";
  } catch (error) {
    showError(ui, error);
  }
}

if (typeof document !== "undefined") {
  start();
}
