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
    if spec is None or spec.loader is None: raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module); return module
SERVER = load_module()

class LocalServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.app = self.root / "app"; self.package = self.root / "package"; self.app.mkdir(); self.package.mkdir()
        (self.app / "index.html").write_text("<!doctype html><title>Kane Condo</title>", encoding="utf-8")
        (self.app / "app.js").write_text("export const ok = true;\n", encoding="utf-8")
        (self.package / "render-package-manifest.json").write_text("{}", encoding="utf-8")
        (self.package / "roads-lod.krf").write_bytes(b"krf-test")
        self.server = SERVER.build_server(self.app, self.package, "127.0.0.1", 0); self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        host, port = self.server.server_address[:2]; self.base = f"http://{host}:{port}"
    def tearDown(self) -> None:
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp.cleanup()
    def fetch(self, path: str, *, method: str = "GET"):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, method=method), timeout=5)
    def test_root_serves_browser_shell(self):
        with self.fetch("/") as response:
            self.assertEqual(200, response.status); self.assertIn(b"Kane Condo", response.read()); self.assertEqual("no-store", response.headers["Cache-Control"]); self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
    def test_config_is_canonical_and_points_to_local_package(self):
        with self.fetch("/config.json") as response: payload=response.read(); self.assertEqual(200,response.status); self.assertEqual(str(len(payload)),response.headers["Content-Length"])
        document=json.loads(payload); self.assertEqual(SERVER.CONFIG_FORMAT,document["format"]); self.assertEqual(SERVER.CONFIG_VERSION,document["version"]); self.assertEqual("/package/render-package-manifest.json",document["package_manifest_url"]); self.assertEqual(SERVER.canonical_json_bytes(document),payload)
    def test_package_files_are_served_from_external_directory(self):
        with self.fetch("/package/roads-lod.krf") as response: self.assertEqual(b"krf-test",response.read()); self.assertEqual("application/octet-stream",response.headers.get_content_type())
    def test_head_reports_length_without_body(self):
        with self.fetch("/package/roads-lod.krf", method="HEAD") as response: self.assertEqual("8",response.headers["Content-Length"]); self.assertEqual(b"",response.read())
    def test_directory_listing_is_not_exposed(self):
        with self.assertRaises(urllib.error.HTTPError) as context: self.fetch("/package/")
        self.assertEqual(404,context.exception.code)
    def test_path_traversal_does_not_escape_roots(self):
        (self.root/"secret.txt").write_text("not served",encoding="utf-8")
        for path in ("/%2e%2e/secret.txt","/package/%2e%2e/secret.txt"):
            with self.assertRaises(urllib.error.HTTPError) as context: self.fetch(path)
            self.assertEqual(404,context.exception.code)
    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"loopback"): SERVER.build_server(self.app,self.package,"0.0.0.0",0)
    def test_permanent_shell_contains_progressive_roads_and_navigation(self):
        html=(ROOT/"app/index.html").read_text(encoding="utf-8")
        for marker in ('id="map-panel"','id="map-canvas"','id="county-outline"','id="road-network"','id="reset-county-view"','preserveAspectRatio="xMidYMid meet"'): self.assertIn(marker,html)
        self.assertNotIn("Map rendering begins in Batch 035",html)
    def test_documentation_preserves_headless_orchestrator_boundary(self):
        root_readme=(ROOT/"README.md").read_text(encoding="utf-8"); app_readme=(ROOT/"app/README.md").read_text(encoding="utf-8")
        for text in (root_readme,app_readme): self.assertIn("orchestrator",text.lower()); self.assertIn("Batch 042",text)
        self.assertIn("must not require a desktop browser",root_readme); self.assertIn("acceptance on the orchestrator is headless",app_readme)
    def test_navigation_handlers_have_no_data_or_network_side_effects(self):
        source=(ROOT/"app/app.js").read_text(encoding="utf-8"); nav=source.split("// Batch 036 navigation: pure viewport state only.",1)[1].split("// End Batch 036 navigation.",1)[0]
        for prohibited in ("fetch(","XMLHttpRequest","localStorage","sessionStorage","indexedDB"): self.assertNotIn(prohibited,nav)
        self.assertIn('setAttribute("viewBox"',nav)
    def test_road_rendering_is_browser_side_and_reuses_validated_bytes(self):
        app=(ROOT/"app/app.js").read_text(encoding="utf-8"); validator=(ROOT/"app/package-validator.js").read_text(encoding="utf-8")
        road=app.split("// Batch 037 roads: validated local KRF bytes, decoded only in browser memory.",1)[1].split("// End Batch 037 roads.",1)[0]
        self.assertIn('new DecompressionStream("deflate")',road); self.assertNotIn("/api/",road); self.assertNotIn("localStorage",road); self.assertIn("onComponent(component, bytes)",validator); self.assertIn('component.role === "roads"',app)
    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed; browser math/KRF probe skipped")
    def test_browser_overview_navigation_and_progressive_road_krf(self):
        app_uri=(ROOT/"app/app.js").resolve().as_uri()
        script="""
import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import { validateCountyOverview, overviewViewBox, overviewPathData, viewportMetrics, clientPointToWorld, panViewBoxByPixels, zoomViewBoxAt, wheelSizeScale, resetViewBox, parseRoadContainer, decodeRoadLevel, roadPathData, roadLevelForViewBox } from __APP_URI__;
const canon=(v)=>Array.isArray(v)?'['+v.map(canon).join(',')+']':(v!==null&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canon(v[k])).join(',')+'}':JSON.stringify(v));
const sha=(b)=>crypto.createHash('sha256').update(b).digest('hex');
const county={county_key:'kane-county-il',fips_code:'17089',name:'Kane County',state_code:'IL'};
const manifest={database:{county,accepted_releases:{'county-boundary':{release_key:'boundary-release',release_content_sha256:'a'.repeat(64),feature_count:1},roads:{release_key:'roads-release',release_content_sha256:'c'.repeat(64),feature_count:3}}}};
const ring=[[-88,41.5],[-87.7,41.5],[-87.7,41.9],[-88,41.9],[-88,41.5]];
const overview={county,fit:{bounds:[-88,41.5,-87.7,41.9],center:[-87.85,41.7],height:0.4,width:0.3},format:'kane-condo-county-overview',outline:{kind:'exterior-rings',ring_count:1,rings:[ring],simplification_tolerance_degrees:0.001,source_interior_ring_count:0,source_vertex_count:5,vertex_count:5},source:{dataset_key:'county-boundary',geometry_sha256:'b'.repeat(64),geometry_type:'Polygon',release_content_sha256:'a'.repeat(64),release_key:'boundary-release',source_feature_id:'boundary-1'},srs_id:4326,version:1};
const validated=validateCountyOverview(overview,manifest); const home=overviewViewBox(validated.fit.bounds); assert.match(overviewPathData(validated.outline.rings),/^M -88 -41.5/); assert.ok(viewportMetrics(home,1200,700).scale>0); const centerA=clientPointToWorld(home,1200,700,600,350); const centerB=clientPointToWorld(home,1800,900,900,450); assert.ok(Math.abs(centerA[0]-centerB[0])<1e-12); const panned=panViewBoxByPixels(home,1200,700,100,-50); assert.ok(panned[0]<home[0]); const anchor=clientPointToWorld(home,1200,700,400,300); const zoomed=zoomViewBoxAt(home,home,anchor[0],anchor[1],0.5); assert.ok(zoomed[2]<home[2]); assert.ok(wheelSizeScale(-120)<1); assert.deepEqual(resetViewBox(home),home);
const record=(id,x)=>({bounds:[x,41.6,x+0.01,41.61],coordinates:[[x,41.6],[x+0.01,41.61]],geometry_type:'LineString',source_feature_id:id});
const levelRecords={orientation:[record('1',-87.95)],context:[record('1',-87.95),record('2',-87.9)],detail:[record('1',-87.95),record('2',-87.9),record('3',-87.85)]};
let offset=0; const payloads=[]; const levels=[]; for (const [rank,key] of ['orientation','context','detail'].entries()) { const raw=Buffer.from(canon(levelRecords[key])); const compressed=zlib.deflateSync(raw,{level:9}); const chunk={bounds:[-88,41.5,-87.7,41.9],feature_count:levelRecords[key].length,length:compressed.length,offset,payload_sha256:sha(compressed),records_sha256:sha(raw),uncompressed_length:raw.length}; payloads.push(compressed); offset+=compressed.length; levels.push({chunks:[chunk],cumulative_length_fraction:[0.35,0.75,1][rank],feature_count:levelRecords[key].length,key,purpose:['county-orientation','regional-context','complete-exact-network'][rank],rank,simplification_tolerance_degrees:[0.001,0.00025,0][rank],source_vertex_count:levelRecords[key].length*2,vertex_count:levelRecords[key].length*2}); }
const index={chunk_feature_limit:256,format:'kane-condo-road-lod',levels,road_bounds:[-88,41.5,-87.7,41.9],selection:{basis:'deterministic-coordinate-length-score',coordinate_score_scale:10000000,note:'test'},source:{county,dataset_key:'roads',feature_count:3,release_content_sha256:'c'.repeat(64),release_key:'roads-release'},srs_id:4326,version:1};
const ib=Buffer.from(canon(index)); const il=Buffer.alloc(8); il.writeBigUInt64BE(BigInt(ib.length)); const krf=Buffer.concat([Buffer.from('KCRD028\\n','ascii'),il,ib,...payloads]); const container=parseRoadContainer(krf,manifest); assert.equal(container.index.levels.length,3); assert.equal((await decodeRoadLevel(container,'orientation')).length,1); assert.equal((await decodeRoadLevel(container,'context')).length,2); const detail=await decodeRoadLevel(container,'detail'); assert.equal(detail.length,3); assert.match(roadPathData(detail),/^M /); assert.equal(roadLevelForViewBox(home,home),'orientation'); assert.equal(roadLevelForViewBox([home[0],home[1],home[2]/4,home[3]/4],home),'context'); assert.equal(roadLevelForViewBox([home[0],home[1],home[2]/16,home[3]/16],home),'detail'); const broken=Buffer.from(krf); broken[0]=0; assert.throws(()=>parseRoadContainer(broken,manifest),/magic header/);
""".replace("__APP_URI__", json.dumps(app_uri))
        result=subprocess.run([shutil.which("node"),"--input-type=module"],input=script,text=True,capture_output=True,check=False)
        self.assertEqual(0,result.returncode,result.stderr or result.stdout)

if __name__ == "__main__": unittest.main()
