/**
 * Tests v0.5.0.a — Pipeline Center + Camera Center
 *
 * Ces tests vérifient les invariants structurels des deux nouveaux Hubs
 * (routes déclarées, tabs présents, i18n renseigné). Ils tournent sans
 * @testing-library : simple parsing des fichiers source.
 *
 * Usage : node frontend/tests/camera-pipeline-centers.test.js
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log("  ✓", name); passed++; }
  catch (e) { console.log("  ✗", name, "\n    ", e.message); failed++; }
}

console.log("Pipeline Center / Camera Center — invariants v0.5.0.a\n");

console.log("[Routes]");
const app = read("src/App.js");
test("route /pipeline-center enregistrée", () => {
  assert.ok(/path="\/pipeline-center"/.test(app));
  assert.ok(/<PipelineCenter/.test(app));
});
test("route /camera-center/:cameraId enregistrée", () => {
  assert.ok(/path="\/camera-center\/:cameraId"/.test(app));
  assert.ok(/<CameraCenter/.test(app));
});
test("anciennes routes /pipeline-inspector, /pipeline-designer conservées", () => {
  assert.ok(/path="\/pipeline-inspector"/.test(app),
            "route /pipeline-inspector supprimée (regression)");
  assert.ok(/path="\/pipeline-designer"/.test(app),
            "route /pipeline-designer supprimée (regression)");
});

console.log("\n[Pipeline Center — 10 onglets]");
const pc = read("src/pages/PipelineCenter.jsx");
["overview", "capture", "ai", "tracking", "plugins", "workflows",
 "designer", "inspector", "performance", "debug"].forEach((tab) => {
  test(`tab '${tab}' présent`, () => {
    assert.ok(new RegExp(`id: "${tab}"`).test(pc), `manque tab ${tab}`);
    assert.ok(new RegExp(`data-testid="tab-${tab}"`).test(pc)
             || pc.includes("data-testid={`tab-${id}`}"),
             `data-testid manquant pour ${tab}`);
  });
});
test("consomme /api/diagnostics/capture/stats", () => {
  assert.ok(/\/diagnostics\/capture\/stats/.test(pc));
});
test("consomme /api/diagnostics/pipeline-v2/stats", () => {
  assert.ok(/\/diagnostics\/pipeline-v2\/stats/.test(pc));
});
test("empty state pour aucune caméra", () => {
  assert.ok(/data-testid="pipeline-empty"/.test(pc));
});

console.log("\n[Camera Center — 11 onglets par caméra]");
const cc = read("src/pages/CameraCenter.jsx");
["overview", "live", "network", "streams", "capabilities", "ai",
 "audio", "lighting", "alarm", "ptz", "maintenance"].forEach((tab) => {
  test(`tab '${tab}' présent`, () => {
    assert.ok(new RegExp(`id: "${tab}"`).test(cc), `manque tab ${tab}`);
  });
});
test("utilise useDeviceCapabilities (jamais direct)", () => {
  assert.ok(/useDeviceCapabilities/.test(cc),
            "CameraCenter DOIT utiliser useDeviceCapabilities — jamais fetch direct");
});
test("bouton Discover pour probe manuel", () => {
  assert.ok(/data-testid="cam-discover"/.test(cc));
});
test("widgets conditionnels : Sirène guardée par caps?.siren", () => {
  assert.ok(/if \(!caps\?\.siren\).*NotSupported.*Sirène/s.test(cc)
           || /!caps\?\.siren/.test(cc));
});
test("widgets conditionnels : PTZ guardé par caps?.ptz", () => {
  assert.ok(/if \(!caps\?\.ptz\)/.test(cc));
});
test("widgets conditionnels : Lighting guardé par spotlight/white_light", () => {
  assert.ok(/caps\?\.spotlight \|\| caps\?\.white_light/.test(cc));
});
test("widgets conditionnels : Audio guardé par audio_input/output", () => {
  assert.ok(/!caps\?\.audio_input && !caps\?\.audio_output/.test(cc));
});
test("commandes POST passent PAR /api/devices/*", () => {
  const apiPosts = (cc.match(/api\.post\(`\/[^`]+`/g) || []);
  apiPosts.forEach((c) => {
    assert.ok(c.includes("/devices/"),
              `Commande POST hors device layer détectée : ${c}`);
  });
});
test("gestion erreur discover propre (toast)", () => {
  assert.ok(/toast\.error/.test(cc));
});

console.log("\n[Hook useDeviceCapabilities]");
const hook = read("src/hooks/useDeviceCapabilities.js");
test("hook expose {caps, info, loading, error, refresh, discover}", () => {
  assert.ok(/caps.*info.*loading.*error.*refresh.*discover/.test(
    hook.replace(/\s+/g, " ")));
});
test("hook mappe l'erreur au format {status,code,message}", () => {
  assert.ok(/setError\(\{ status,/.test(hook));
});
test("discover POST /api/devices/{id}/discover", () => {
  assert.ok(/api\.post\(`\/devices\/\$\{cameraId\}\/discover`\)/.test(hook));
});

console.log("\n[Layout menu]");
const layout = read("src/components/Layout.jsx");
test("entrée menu /pipeline-center ajoutée", () => {
  assert.ok(/to: "\/pipeline-center"/.test(layout));
  assert.ok(/nav\.pipeline_center/.test(layout));
});

console.log("\n[i18n]");
const i18n = read("src/i18n.js");
test("label nav.pipeline_center défini", () => {
  assert.ok(/nav\.pipeline_center/.test(i18n));
});

console.log("\n[Cameras.jsx compatibilité]");
const cams = read("src/pages/Cameras.jsx");
test("ancien bouton diagnostic-btn conservé", () => {
  assert.ok(/data-testid="diagnostic-btn"/.test(cams));
});
test("nouveau lien open-camera-center ajouté", () => {
  assert.ok(/data-testid="open-camera-center"/.test(cams));
  assert.ok(/camera-center\/\$\{c\.id\}/.test(cams));
});

console.log(`\nRésultat : ${passed} passés, ${failed} échoués`);
process.exit(failed === 0 ? 0 : 1);
