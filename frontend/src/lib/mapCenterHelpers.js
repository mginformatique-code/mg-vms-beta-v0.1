// v3.54 · Extrait de MapCenter.jsx pour être partagé avec LiveMapCanvas.jsx
// (fond de carte interactif) sans dupliquer la logique — comportement
// strictement inchangé, juste déplacé.

export const DEFAULT_CAM = {
  x: 100, y: 100, rotation: 0, height_m: 3,
  angle_h: 90, angle_v: 60, range_m: 20, color: "#0044FF",
  fixture: "wall", lens_mm: 4,
};

export const STATUS_COLOR = {
  online: "#00E676", offline: "#FF3333", degraded: "#FFB800",
};

// v0.5.2.c · Phase 2 — heuristique qualité de couverture.
// Le cône est coloré selon la combinaison (angle horizontal, portée) et la
// hauteur d'installation. Ce n'est pas une simulation optique, juste un
// signal visuel pour l'installateur.
//   Vert  = couverture "correcte" (angle 60-100° · portée 15-30m · hauteur 2.5-4m)
//   Jaune = couverture moyenne
//   Rouge = limite (angle trop large, portée trop courte/longue)
export const COVERAGE_COLOR = {
  good: "#00E676",
  medium: "#FFB800",
  poor: "#FF3333",
};

export function coverageQuality(pos) {
  const a = pos?.angle_h ?? DEFAULT_CAM.angle_h;
  const r = pos?.range_m ?? DEFAULT_CAM.range_m;
  const h = pos?.height_m ?? DEFAULT_CAM.height_m;
  let score = 100;
  if (a < 40 || a > 130) score -= 30; // trop étroit ou fisheye
  else if (a < 60 || a > 110) score -= 15;
  if (r < 8 || r > 40) score -= 30;
  else if (r < 15 || r > 30) score -= 10;
  if (h < 2 || h > 6) score -= 25;
  else if (h < 2.5 || h > 4.5) score -= 10;
  if (score >= 75) return "good";
  if (score >= 45) return "medium";
  return "poor";
}

// Détection des rôles caméra pour badges (heuristique légère)
export function detectCameraRoles(cam) {
  const plugins = (cam.enabled_plugins || []).map((p) => p.toLowerCase());
  const roles = [];
  if (plugins.some((p) => p.includes("alpr") || p.includes("anpr"))) roles.push("anpr");
  if ((cam.driver || "").toLowerCase().includes("ptz") ||
      (cam.model || "").toLowerCase().includes("ptz") ||
      cam.is_ptz) roles.push("ptz");
  if ((cam.model || "").toLowerCase().includes("thermal") ||
      plugins.includes("thermal")) roles.push("thermal");
  if (cam.record_enabled) roles.push("rec");
  if (cam.detect_enabled) roles.push("ai");
  return roles;
}
export const ROLE_LABELS = {
  anpr: "ANPR", ptz: "PTZ", thermal: "TH", ai: "IA", rec: "REC",
};
export const ROLE_COLORS = {
  anpr: "#0044FF", ptz: "#A855F7", thermal: "#F97316",
  ai: "#00A2FF", rec: "#FF3333",
};

// v0.5.2.c · Phase 3 — audit : détecte les caméras "incomplètes"
export function auditCamera(cam) {
  const pos = cam.map_position || {};
  const flags = [];
  if (!cam.status || cam.status === "offline") flags.push("offline");
  if (!(pos.photos && pos.photos.length)) flags.push("no_photo");
  if (pos.height_m == null) flags.push("no_height");
  if (pos.angle_h == null) flags.push("no_angle");
  // v3.54 · Une caméra positionnée sur une carte live utilise lat/lng, pas
  // x/y — l'un OU l'autre couple complet vaut "positionnée".
  const hasPixelPos = pos.x != null && pos.y != null;
  const hasGeoPos = pos.lat != null && pos.lng != null;
  if (!hasPixelPos && !hasGeoPos) flags.push("no_place");
  if (!cam.driver) flags.push("no_driver");
  if (!cam.firmware) flags.push("no_firmware");
  return flags;
}
export const AUDIT_LABEL = {
  offline: "Hors ligne",
  no_photo: "Sans photo",
  no_height: "Hauteur non renseignée",
  no_angle: "Angle non renseigné",
  no_place: "Non positionnée",
  no_driver: "Sans driver",
  no_firmware: "Firmware absent",
};

// v3.54 · Formule de destination géographique (haversine) — utilisée pour
// dessiner le cône FOV en géométrie réelle sur un plan "carte_live" à
// partir des MÊMES champs rotation/angle_h/range_m que le mode pixel
// (aucun nouveau champ de saisie côté utilisateur).
const EARTH_RADIUS_M = 6371000;
export function geoDestination(lat, lng, bearingDeg, distanceM) {
  const δ = distanceM / EARTH_RADIUS_M;
  const θ = (bearingDeg * Math.PI) / 180;
  const φ1 = (lat * Math.PI) / 180;
  const λ1 = (lng * Math.PI) / 180;
  const φ2 = Math.asin(
    Math.sin(φ1) * Math.cos(δ) + Math.cos(φ1) * Math.sin(δ) * Math.cos(θ)
  );
  const λ2 = λ1 + Math.atan2(
    Math.sin(θ) * Math.sin(δ) * Math.cos(φ1),
    Math.cos(δ) - Math.sin(φ1) * Math.sin(φ2)
  );
  return [(φ2 * 180) / Math.PI, ((λ2 * 180) / Math.PI + 540) % 360 - 180];
}

// Construit le polygone (lat/lng) du cône FOV pour une caméra positionnée
// en coordonnées réelles — même convention que le Wedge Konva : `rotation`
// est le cap central (0° = nord), `angle_h` l'ouverture totale en degrés.
export function fovPolygon(lat, lng, pos, steps = 12) {
  const rot = pos?.rotation || 0;
  const angleH = pos?.angle_h ?? DEFAULT_CAM.angle_h;
  const range = pos?.range_m ?? DEFAULT_CAM.range_m;
  const start = rot - angleH / 2;
  const pts = [[lat, lng]];
  for (let i = 0; i <= steps; i++) {
    const bearing = start + (angleH * i) / steps;
    pts.push(geoDestination(lat, lng, bearing, range));
  }
  pts.push([lat, lng]);
  return pts;
}
