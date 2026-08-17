#!/usr/bin/env python3
"""Standard-library tests for the Kane Condo local loopback runtime."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "app/tools/kane_local_server.py"


def load_module():
    spec = importlib.util.spec_from_file_location("_kane_local_server_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERVER = load_module()


class LocalServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.package = self.root / "package"
        self.app.mkdir()
        self.package.mkdir()
        (self.app / "index.html").write_text("<!doctype html><title>Kane Condo</title>", encoding="utf-8")
        (self.app / "app.js").write_text("export const ok = true;\n", encoding="utf-8")
        (self.package / "render-package-manifest.json").write_text("{}", encoding="utf-8")
        (self.package / "roads-lod.krf").write_bytes(b"krf-test")
        self.server = SERVER.build_server(self.app, self.package, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def fetch(self, path: str, *, method: str = "GET"):
        request = urllib.request.Request(self.base + path, method=method)
        return urllib.request.urlopen(request, timeout=5)

    def test_root_serves_browser_shell(self) -> None:
        with self.fetch("/") as response:
            self.assertEqual(200, response.status)
            self.assertIn(b"Kane Condo", response.read())
            self.assertEqual("no-store", response.headers["Cache-Control"])
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_config_is_canonical_and_points_to_local_package(self) -> None:
        with self.fetch("/config.json") as response:
            payload = response.read()
            self.assertEqual(200, response.status)
            self.assertEqual(str(len(payload)), response.headers["Content-Length"])
        document = json.loads(payload)
        self.assertEqual(SERVER.CONFIG_FORMAT, document["format"])
        self.assertEqual(SERVER.CONFIG_VERSION, document["version"])
        self.assertEqual("/package/render-package-manifest.json", document["package_manifest_url"])
        self.assertEqual(SERVER.canonical_json_bytes(document), payload)

    def test_package_files_are_served_from_external_directory(self) -> None:
        with self.fetch("/package/roads-lod.krf") as response:
            self.assertEqual(b"krf-test", response.read())
            self.assertEqual("application/octet-stream", response.headers.get_content_type())

    def test_head_reports_length_without_body(self) -> None:
        with self.fetch("/package/roads-lod.krf", method="HEAD") as response:
            self.assertEqual("8", response.headers["Content-Length"])
            self.assertEqual(b"", response.read())

    def test_directory_listing_is_not_exposed(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.fetch("/package/")
        self.assertEqual(404, context.exception.code)

    def test_path_traversal_does_not_escape_roots(self) -> None:
        secret = self.root / "secret.txt"
        secret.write_text("not served", encoding="utf-8")
        for path in ("/%2e%2e/secret.txt", "/package/%2e%2e/secret.txt"):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.fetch(path)
            self.assertEqual(404, context.exception.code)

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            SERVER.build_server(self.app, self.package, "0.0.0.0", 0)

    def test_permanent_shell_contains_full_county_svg_viewport(self) -> None:
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        self.assertIn('id="map-panel"', html)
        self.assertIn('id="map-canvas"', html)
        self.assertIn('id="county-outline"', html)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', html)
        self.assertNotIn("Map rendering begins in Batch 035", html)

    def test_documentation_preserves_headless_orchestrator_boundary(self) -> None:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        app_readme = (ROOT / "app/README.md").read_text(encoding="utf-8")
        for text in (root_readme, app_readme):
            self.assertIn("orchestrator", text.lower())
            self.assertIn("Batch 042", text)
        self.assertIn("must not require a desktop browser", root_readme)
        self.assertIn("acceptance on the orchestrator is headless", app_readme)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed; browser math probe skipped")
    def test_browser_overview_validation_fit_and_path_generation(self) -> None:
        app_uri = (ROOT / "app/app.js").resolve().as_uri()
        script = f"""
import assert from 'node:assert/strict';
import {{ validateCountyOverview, overviewViewBox, overviewPathData }} from {json.dumps(app_uri)};

const manifest = {{
  database: {{
    county: {{county_key:'kane-county-il', fips_code:'17089', name:'Kane County', state_code:'IL'}},
    accepted_releases: {{
      'county-boundary': {{release_key:'boundary-release', release_content_sha256:'a'.repeat(64), feature_count:1}}
    }}
  }}
}};
const ring = [
  [-88.0, 41.5], [-87.7, 41.5], [-87.7, 41.9], [-88.0, 41.9], [-88.0, 41.5]
];
const overview = {{
  county: manifest.database.county,
  fit: {{bounds:[-88.0,41.5,-87.7,41.9], center:[-87.85,41.7], height:0.4, width:0.3}},
  format:'kane-condo-county-overview',
  outline: {{
    kind:'exterior-rings', ring_count:1, rings:[ring], simplification_tolerance_degrees:0.001,
    source_interior_ring_count:0, source_vertex_count:5, vertex_count:5
  }},
  source: {{
    dataset_key:'county-boundary', geometry_sha256:'b'.repeat(64), geometry_type:'Polygon',
    release_content_sha256:'a'.repeat(64), release_key:'boundary-release', source_feature_id:'boundary-1'
  }},
  srs_id:4326,
  version:1
}};

const validated = validateCountyOverview(overview, manifest);
assert.deepEqual(validated.fit.bounds, [-88.0,41.5,-87.7,41.9]);
const viewBox = overviewViewBox(validated.fit.bounds);
assert.equal(viewBox.length, 4);
assert.ok(viewBox[0] < -88.0);
assert.ok(viewBox[1] < -41.9);
assert.ok(viewBox[2] > 0.3);
assert.ok(viewBox[3] > 0.4);
const path = overviewPathData(validated.outline.rings);
assert.match(path, /^M -88 -41.5 /);
assert.match(path, / Z$/);

const incompatible = structuredClone(overview);
incompatible.source.release_key = 'wrong-release';
assert.throws(() => validateCountyOverview(incompatible, manifest), /boundary release does not match/);
"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
