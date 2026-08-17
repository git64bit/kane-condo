import {
  PackageValidationError,
  validateLocalConfig,
  validateLocalPackage,
} from "/package-validator.js";

const indicator = document.querySelector("#status-indicator");
const title = document.querySelector("#status-title");
const message = document.querySelector("#status-message");
const details = document.querySelector("#package-details");
const detailCounty = document.querySelector("#detail-county");
const detailCreated = document.querySelector("#detail-created");
const detailIdentity = document.querySelector("#detail-identity");
const errorDetail = document.querySelector("#error-detail");

function setStatus(state, heading, text) {
  indicator.dataset.state = state;
  title.textContent = heading;
  message.textContent = text;
}

function showError(error) {
  const known = error instanceof PackageValidationError;
  const code = known ? error.code : "UNEXPECTED_APPLICATION_ERROR";
  const text = known ? error.message : "Unexpected error while validating the local package.";
  setStatus("error", `Package unavailable: ${code}`, text);
  details.hidden = true;
  errorDetail.hidden = false;
  errorDetail.textContent = known && error.detail ? error.detail : String(error);
  document.documentElement.dataset.packageState = "error";
}

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

async function start() {
  try {
    setStatus("checking", "Checking local package", "Loading local configuration.");
    const config = await loadConfig();
    const manifest = await validateLocalPackage(config, {
      onProgress(progress) {
        setStatus("checking", "Checking local package", progress.message);
      },
    });
    const county = manifest.database.county;
    detailCounty.textContent = `${county.name}, ${county.state_code}`;
    detailCreated.textContent = manifest.created_at;
    detailIdentity.textContent = manifest.identities.package_content_sha256;
    details.hidden = false;
    errorDetail.hidden = true;
    setStatus("ready", "Local package ready", "Integrity and compatibility checks passed. Read-only map rendering is ready for Batch 035.");
    document.documentElement.dataset.packageState = "ready";
  } catch (error) {
    showError(error);
  }
}

start();
