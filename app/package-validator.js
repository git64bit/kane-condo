const MANIFEST_FORMAT = "kane-condo-render-package-manifest";
const MANIFEST_VERSION = 1;
const CONFIG_FORMAT = "kane-condo-local-runtime-config";
const CONFIG_VERSION = 1;
const SHA256_RE = /^[0-9a-f]{64}$/;
const EXPECTED_COUNTY = { county_key: "kane-county-il", fips_code: "17089", name: "Kane County", state_code: "IL" };
const COMPONENT_SPECS = [
  ["county_overview", "county-overview.json", "kane-condo-county-overview", 1],
  ["roads", "roads-lod.krf", "kane-condo-road-lod", 1],
  ["water", "water-lod.krf", "kane-condo-water-lod", 1],
  ["buildings", "buildings-lod.krf", "kane-condo-building-lod", 1],
  ["classification_snapshot", "classification-snapshot.json", "kane-condo-classification-snapshot", 1],
];
const DATASET_KEYS = ["county-boundary", "roads", "water-fox-river", "water-creeks", "buildings"];

export class PackageValidationError extends Error {
  constructor(code, message, detail = null) { super(message); this.name = "PackageValidationError"; this.code = code; this.detail = detail; }
}
function fail(code, message, detail = null) { throw new PackageValidationError(code, message, detail); }
function isPlainObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function requireExactKeys(value, keys, label) {
  if (!isPlainObject(value)) fail("MANIFEST_INCOMPATIBLE", `${label} is not an object.`);
  const actual = Object.keys(value).sort(); const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail("MANIFEST_INCOMPATIBLE", `${label} fields are incompatible.`, `Expected: ${expected.join(", ")}\nFound: ${actual.join(", ")}`);
  return value;
}
function requireSha(value, label) { if (typeof value !== "string" || !SHA256_RE.test(value)) fail("MANIFEST_INCOMPATIBLE", `${label} is not a lowercase SHA-256 value.`); }
function canonicalize(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (isPlainObject(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
async function sha256Bytes(bytes) {
  if (!globalThis.crypto?.subtle) fail("CRYPTO_UNAVAILABLE", "This browser does not provide Web Crypto SHA-256 support.");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}
async function sha256Text(text) { return sha256Bytes(new TextEncoder().encode(text)); }

function validateDatabase(database) {
  requireExactKeys(database, ["accepted_releases", "byte_length", "county", "sha256"], "Manifest database");
  if (!Number.isSafeInteger(database.byte_length) || database.byte_length < 0) fail("MANIFEST_INCOMPATIBLE", "Manifest database byte length is invalid.");
  requireSha(database.sha256, "Manifest database SHA-256");
  const county = requireExactKeys(database.county, ["county_key", "fips_code", "name", "state_code"], "Manifest county");
  for (const key of Object.keys(EXPECTED_COUNTY)) {
    if (typeof county[key] !== "string" || county[key].length === 0) fail("MANIFEST_INCOMPATIBLE", `Manifest county ${key} is invalid.`);
    if (county[key] !== EXPECTED_COUNTY[key]) fail("MANIFEST_INCOMPATIBLE", `Manifest county ${key} does not identify Kane County, Illinois.`);
  }
  const releases = requireExactKeys(database.accepted_releases, DATASET_KEYS, "Manifest accepted releases");
  for (const datasetKey of DATASET_KEYS) {
    const release = requireExactKeys(releases[datasetKey], ["feature_count", "release_content_sha256", "release_key"], `Manifest release ${datasetKey}`);
    if (!Number.isSafeInteger(release.feature_count) || release.feature_count < 0) fail("MANIFEST_INCOMPATIBLE", `Manifest release ${datasetKey} feature count is invalid.`);
    requireSha(release.release_content_sha256, `Manifest release ${datasetKey} content SHA-256`);
    if (typeof release.release_key !== "string" || release.release_key.length === 0) fail("MANIFEST_INCOMPATIBLE", `Manifest release ${datasetKey} key is invalid.`);
  }
}
function validateCompatibility(value) {
  const c = requireExactKeys(value, ["building_component", "classification_component", "explicit_count", "records_sha256", "render_building_count", "render_identity_sha256", "source_release_content_sha256", "source_release_key"], "Manifest classification compatibility");
  if (c.building_component !== "buildings" || c.classification_component !== "classification_snapshot") fail("MANIFEST_INCOMPATIBLE", "Manifest classification component linkage is unsupported.");
  for (const key of ["explicit_count", "render_building_count"]) if (!Number.isSafeInteger(c[key]) || c[key] < 0) fail("MANIFEST_INCOMPATIBLE", `Manifest classification compatibility ${key} is invalid.`);
  for (const key of ["records_sha256", "render_identity_sha256", "source_release_content_sha256"]) requireSha(c[key], `Manifest classification compatibility ${key}`);
  if (typeof c.source_release_key !== "string" || c.source_release_key.length === 0) fail("MANIFEST_INCOMPATIBLE", "Manifest classification source release key is invalid.");
}
async function validateManifest(document, rawText) {
  const manifest = requireExactKeys(document, ["classification_compatibility", "components", "created_at", "database", "format", "identities", "version"], "Manifest");
  if (manifest.format !== MANIFEST_FORMAT || manifest.version !== MANIFEST_VERSION) fail("MANIFEST_INCOMPATIBLE", `Unsupported render-package manifest ${String(manifest.format)} version ${String(manifest.version)}.`, `Expected ${MANIFEST_FORMAT} version ${MANIFEST_VERSION}.`);
  if (rawText !== canonicalize(manifest)) fail("MANIFEST_NON_CANONICAL", "Render-package manifest is not canonical JSON.");
  if (typeof manifest.created_at !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(manifest.created_at)) fail("MANIFEST_INCOMPATIBLE", "Manifest creation time is not UTC RFC3339 whole-second format.");
  validateDatabase(manifest.database); validateCompatibility(manifest.classification_compatibility);
  const buildingRelease = manifest.database.accepted_releases.buildings;
  if (manifest.classification_compatibility.source_release_key !== buildingRelease.release_key || manifest.classification_compatibility.source_release_content_sha256 !== buildingRelease.release_content_sha256) fail("MANIFEST_INCOMPATIBLE", "Classification snapshot source release does not match the package building release.");
  if (!Array.isArray(manifest.components) || manifest.components.length !== COMPONENT_SPECS.length) fail("MANIFEST_INCOMPATIBLE", "Manifest component inventory is invalid.");
  for (let index = 0; index < COMPONENT_SPECS.length; index += 1) {
    const [role, filename, format, version] = COMPONENT_SPECS[index];
    const component = requireExactKeys(manifest.components[index], ["byte_length", "filename", "format", "role", "sha256", "version"], `Manifest component ${index}`);
    if (component.role !== role || component.filename !== filename || component.format !== format || component.version !== version) fail("MANIFEST_INCOMPATIBLE", `Manifest component ${role} identity/version is unsupported.`);
    if (!Number.isSafeInteger(component.byte_length) || component.byte_length < 0) fail("MANIFEST_INCOMPATIBLE", `Manifest component ${role} byte length is invalid.`);
    requireSha(component.sha256, `Manifest component ${role} SHA-256`);
  }
  const identities = requireExactKeys(manifest.identities, ["base_geometry_sha256", "classification_snapshot_sha256", "package_content_sha256"], "Manifest identities");
  for (const [key, value] of Object.entries(identities)) requireSha(value, `Manifest identity ${key}`);
  const baseComponents = manifest.components.filter((item) => item.role !== "classification_snapshot");
  if (identities.base_geometry_sha256 !== await sha256Text(canonicalize(baseComponents))) fail("MANIFEST_IDENTITY_MISMATCH", "Manifest base-geometry identity does not match its component descriptors.");
  const classification = manifest.components.find((item) => item.role === "classification_snapshot");
  if (identities.classification_snapshot_sha256 !== classification.sha256) fail("MANIFEST_IDENTITY_MISMATCH", "Manifest classification identity does not match its component descriptor.");
  const expectedContent = await sha256Text(canonicalize({ components: manifest.components, database: manifest.database, classification_compatibility: manifest.classification_compatibility }));
  if (identities.package_content_sha256 !== expectedContent) fail("MANIFEST_IDENTITY_MISMATCH", "Manifest package-content identity does not match its declared contents.");
  return manifest;
}
async function fetchRequired(url, label) {
  let response; try { response = await fetch(url, { cache: "no-store" }); } catch (error) { fail("LOCAL_RESOURCE_UNAVAILABLE", `${label} could not be loaded.`, String(error)); }
  if (!response.ok) fail("LOCAL_RESOURCE_UNAVAILABLE", `${label} returned HTTP ${response.status}.`, url);
  return response;
}
async function validateSmallJsonComponent(component, bytes) {
  if (component.role !== "county_overview" && component.role !== "classification_snapshot") return;
  let text; let document;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); document = JSON.parse(text); } catch (error) { fail("COMPONENT_INCOMPATIBLE", `${component.role} is not valid UTF-8 JSON.`, String(error)); }
  if (text !== canonicalize(document) && !(component.role === "county_overview" && text === `${canonicalize(document)}\n`)) fail("COMPONENT_INCOMPATIBLE", `${component.role} is not canonical JSON.`);
  if (!isPlainObject(document) || document.format !== component.format || document.version !== component.version) fail("COMPONENT_INCOMPATIBLE", `${component.role} internal format/version does not match the manifest.`);
}

export function validateLocalConfig(document) {
  const config = requireExactKeys(document, ["format", "package_manifest_url", "version"], "Local runtime configuration");
  if (config.format !== CONFIG_FORMAT || config.version !== CONFIG_VERSION) fail("CONFIG_INCOMPATIBLE", "Local runtime configuration format/version is unsupported.");
  if (typeof config.package_manifest_url !== "string" || !config.package_manifest_url.startsWith("/package/") || config.package_manifest_url.includes("..")) fail("CONFIG_INCOMPATIBLE", "Local runtime package manifest URL is invalid.");
  return config;
}

export async function validateLocalPackage(config, { onProgress = () => {}, onComponent = () => {} } = {}) {
  const manifestUrl = new URL(config.package_manifest_url, globalThis.location?.href ?? "http://127.0.0.1/");
  onProgress({ phase: "manifest", message: "Loading render-package manifest." });
  const response = await fetchRequired(manifestUrl, "Render-package manifest");
  const rawText = await response.text();
  let document; try { document = JSON.parse(rawText); } catch (error) { fail("MANIFEST_INVALID_JSON", "Render-package manifest is not valid JSON.", String(error)); }
  const manifest = await validateManifest(document, rawText);
  for (let index = 0; index < manifest.components.length; index += 1) {
    const component = manifest.components[index];
    onProgress({ phase: "component", role: component.role, index: index + 1, total: manifest.components.length, message: `Validating ${component.filename} (${index + 1}/${manifest.components.length}).` });
    const componentUrl = new URL(component.filename, manifestUrl);
    const componentResponse = await fetchRequired(componentUrl, `Render component ${component.role}`);
    const bytes = await componentResponse.arrayBuffer();
    if (bytes.byteLength !== component.byte_length) fail("COMPONENT_LENGTH_MISMATCH", `${component.role} byte length does not match the manifest.`, `Expected ${component.byte_length}; found ${bytes.byteLength}.`);
    const actualSha = await sha256Bytes(bytes);
    if (actualSha !== component.sha256) fail("COMPONENT_HASH_MISMATCH", `${component.role} SHA-256 does not match the manifest.`, `Expected ${component.sha256}; found ${actualSha}.`);
    await validateSmallJsonComponent(component, bytes);
    await onComponent(component, bytes);
  }
  onProgress({ phase: "complete", message: "Local render package is valid and compatible." });
  return manifest;
}

export const _test = { canonicalize, validateManifest, COMPONENT_SPECS };
