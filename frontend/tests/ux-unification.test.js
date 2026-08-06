/**
 * Tests v0.5.0.b — UX Unification
 *
 * Vérifie que :
 *   1. Menu principal nettoyé (pipeline-video/monitor/designer/inspector RETIRÉS)
 *   2. Routes anciennes conservées + alias /pipeline/designer, /pipeline/inspector
 *   3. Cameras.jsx : ligne cliquable → Camera Center
 *   4. Camera Center : health banner + prev/next + Events tab + WebRTC embed
 *   5. Capabilities : présentation catégorisée (jamais JSON brut)
 *   6. AI : latences live (Decode/YOLO/Tracking/ANPR)
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

console.log("v0.5.0.b — UX Unification invariants\n");

console.log("[Menu nettoyé]");
const layout = read("src/components/Layout.jsx");
["pipeline-video", "pipeline-monitor", "pipeline-designer", "pipeline-inspector"].forEach((r) => {
  test(`menu principal SANS ${r}`, () => {
    // Ces routes ne doivent PAS apparaître dans NAV_GROUPS (to: "/xxx")
    assert.ok(!new RegExp(`\\bto: "/${r}"`).test(layout),
              `route /${r} encore présente dans le menu`);
  });
});
test("pipeline-center dans le menu", () => {
  assert.ok(/to: "\/pipeline-center"/.test(layout));
});

console.log("\n[Routes conservées + alias]");
const app = read("src/App.js");
["pipeline-designer", "pipeline-inspector", "pipeline-center"].forEach((r) => {
  test(`route /${r} conservée`, () => {
    assert.ok(new RegExp(`path="/${r}"`).test(app), `route /${r} supprimée`);
  });
});
test("alias /pipeline/designer", () => {
  assert.ok(/path="\/pipeline\/designer"/.test(app));
});
test("alias /pipeline/inspector", () => {
  assert.ok(/path="\/pipeline\/inspector"/.test(app));
});

console.log("\n[Cameras.jsx — ligne cliquable]");
const cams = read("src/pages/Cameras.jsx");
test("row onClick vers /camera-center/:id", () => {
  assert.ok(/onClick=\{\(e\) => \{ if \(e\.target\.closest/.test(cams)
           && /window\.location\.href = `\/camera-center\/\$\{c\.id\}`/.test(cams));
});
test("classe cursor-pointer sur la ligne", () => {
  assert.ok(/cursor-pointer/.test(cams));
});
test("anciens boutons conservés (diagnostic-btn, open-camera-center)", () => {
  assert.ok(/data-testid="diagnostic-btn"/.test(cams));
  assert.ok(/data-testid="open-camera-center"/.test(cams));
});

console.log("\n[CameraCenter v0.5.0.b enrichi]");
const cc = read("src/pages/CameraCenter.jsx");
test("HealthBanner (bandeau global CPU/GPU/RAM/VRAM/Mongo/go2rtc/Capture/Pipeline)", () => {
  assert.ok(/data-testid="health-banner"/.test(cc));
  assert.ok(/system-health/.test(cc) || /system_health/.test(cc));
});
test("Navigation prev/next entre caméras", () => {
  assert.ok(/data-testid="cam-prev"/.test(cc));
  assert.ok(/data-testid="cam-next"/.test(cc));
});
test("Retour direct à la liste caméras", () => {
  assert.ok(/data-testid="back-to-cameras"/.test(cc));
});
test("Live tab intègre WebRTCPlayer (fin des renvois vers /live)", () => {
  assert.ok(/import WebRTCPlayer/.test(cc));
  assert.ok(/<WebRTCPlayer cameraId=\{cameraId\}/.test(cc));
});
test("Events tab présent", () => {
  assert.ok(/id: "events"/.test(cc));
  assert.ok(/data-testid="cam-events"/.test(cc));
});
test("Events : plaques + alertes + erreurs", () => {
  assert.ok(/Dernières plaques/.test(cc));
  assert.ok(/Dernières alertes/.test(cc));
  assert.ok(/Dernières erreurs/.test(cc));
});
test("Capabilities catégorisées (VIDEO, PTZ, AUDIO, LUMIÈRE, ALARME, CAPTEURS, IA)", () => {
  ["VIDEO", "PTZ", "AUDIO", "LUMIÈRE", "ALARME", "CAPTEURS", "IA EMBARQUÉE"].forEach((g) => {
    assert.ok(new RegExp(`title: "${g}"`).test(cc), `groupe ${g} manquant`);
  });
});
test("AI tab : latences live YOLO/Tracking/ROI/ANPR/Total", () => {
  ["YOLO", "Tracking", "ROI", "ANPR", "Total"].forEach((s) => {
    assert.ok(new RegExp(`<div>${s}</div>`).test(cc), `latence ${s} manquante`);
  });
});
test("Overview tab : Driver, FPS capture, Frames dropped, IA active, ANPR", () => {
  ["Driver", "FPS capture", "Frames dropped", "IA active", "ANPR"].forEach((f) => {
    assert.ok(new RegExp(`<div>${f}</div>`).test(cc), `champ overview '${f}' manquant`);
  });
});

console.log(`\nRésultat : ${passed} passés, ${failed} échoués`);
process.exit(failed === 0 ? 0 : 1);
