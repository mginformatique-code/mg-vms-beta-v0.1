// v3.57 · Rendu partagé pour le rapport PDF "CCTV design tool" — capture
// une image (data URI PNG) pour la page de garde/vue d'ensemble et pour
// chaque page caméra, dans les deux modes de plan (image Konva / carte
// live Leaflet).
//
// Pour un plan carte_live, on NE PEUT PAS capturer le DOM Leaflet en
// direct de façon fiable : la bibliothèque de référence pour ça
// (leaflet-image) ne sait pas rastériser les marqueurs `L.divIcon` (HTML)
// — exactement le type utilisé pour les caméras/équipements dans
// LiveMapCanvas.jsx. On recompose donc l'image nous-mêmes sur un canvas
// dédié : mêmes tuiles OSM/Esri que LiveMapCanvas.jsx (vérifié en direct :
// les deux serveurs envoient `Access-Control-Allow-Origin: *`, donc
// `crossOrigin="anonymous"` + `canvas.toDataURL()` fonctionnent sans
// "tainted canvas"), dessinées via la géométrie de tuile Web Mercator
// standard, puis le cône FOV et l'icône caméra dessinés par-dessus avec
// les MÊMES fonctions déjà utilisées par la carte live (fovPolygon).
import { fovPolygon, COVERAGE_COLOR, coverageQuality, STATUS_COLOR } from "./mapCenterHelpers";

const TILE_SIZE = 256;
const TILE_URL = {
  street: (x, y, z) => `https://a.tile.openstreetmap.org/${z}/${x}/${y}.png`,
  satellite: (x, y, z) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`,
};

function lngToWorldX(lng, zoom) {
  return ((lng + 180) / 360) * TILE_SIZE * 2 ** zoom;
}
function latToWorldY(lat, zoom) {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * TILE_SIZE * 2 ** zoom;
}

// Résolution standard Web Mercator (m/pixel) — utilisée pour choisir un
// niveau de zoom qui fait tenir une portée de caméra donnée dans le cadre.
export function metersPerPixel(zoom, lat) {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
}
export function zoomForRangeMeters(rangeM, widthPx, lat, padding = 2.4) {
  const targetMpp = (rangeM * padding) / (widthPx / 2);
  const raw = Math.log2(156543.03392 * Math.cos((lat * Math.PI) / 180) / targetMpp);
  return Math.max(3, Math.min(20, Math.round(raw)));
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null); // tuile manquante : trou transparent plutôt qu'un échec total
    img.src = src;
  });
}

function drawCameraIcon(ctx, x, y, pos, status) {
  const cov = COVERAGE_COLOR[coverageQuality(pos)];
  const dot = STATUS_COLOR[status] || "#71717a";
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, 9, 0, Math.PI * 2);
  ctx.fillStyle = "#0d1117";
  ctx.fill();
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = cov;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x + 6, y - 6, 3, 0, Math.PI * 2);
  ctx.fillStyle = dot;
  ctx.fill();
  ctx.strokeStyle = "#0d1117";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.restore();
}

/**
 * Recompose une zone de carte live (tuiles + cônes FOV + icônes caméra)
 * sur un canvas hors-écran, retourne un data URI PNG.
 * `highlightId` (optionnel) grossit le cône/l'icône de cette caméra —
 * utilisé pour la page dédiée d'une caméra au milieu d'autres.
 */
export async function renderGeoCrop({
  centerLat, centerLng, zoom, widthPx, heightPx, tileKind = "satellite",
  cameras = [], highlightId = null,
}) {
  const z = Math.round(Math.max(1, Math.min(19, zoom)));
  const canvas = document.createElement("canvas");
  canvas.width = widthPx;
  canvas.height = heightPx;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#0b0b0f";
  ctx.fillRect(0, 0, widthPx, heightPx);

  const centerWorldX = lngToWorldX(centerLng, z);
  const centerWorldY = latToWorldY(centerLat, z);
  const originX = centerWorldX - widthPx / 2;
  const originY = centerWorldY - heightPx / 2;
  const maxTile = 2 ** z;

  const minTileX = Math.floor(originX / TILE_SIZE);
  const maxTileX = Math.floor((originX + widthPx) / TILE_SIZE);
  const minTileY = Math.floor(originY / TILE_SIZE);
  const maxTileY = Math.floor((originY + heightPx) / TILE_SIZE);

  const urlFor = TILE_URL[tileKind] || TILE_URL.satellite;
  const tiles = [];
  for (let tx = minTileX; tx <= maxTileX; tx++) {
    for (let ty = minTileY; ty <= maxTileY; ty++) {
      if (ty < 0 || ty >= maxTile) continue;
      const wrappedX = ((tx % maxTile) + maxTile) % maxTile;
      tiles.push({ tx, ty, url: urlFor(wrappedX, ty, z) });
    }
  }
  const images = await Promise.all(tiles.map((t) => loadImage(t.url)));
  tiles.forEach((t, i) => {
    if (!images[i]) return;
    const drawX = t.tx * TILE_SIZE - originX;
    const drawY = t.ty * TILE_SIZE - originY;
    ctx.drawImage(images[i], drawX, drawY, TILE_SIZE, TILE_SIZE);
  });

  const toCanvasXY = (lat, lng) => [
    lngToWorldX(lng, z) - originX,
    latToWorldY(lat, z) - originY,
  ];

  // Cônes FOV d'abord (sous les icônes), caméra mise en avant dessinée en
  // dernier pour rester au-dessus des autres si elles se chevauchent.
  const ordered = [...cameras].sort((a) => (a.id === highlightId ? 1 : -1));
  for (const cam of ordered) {
    const pos = cam.map_position || {};
    if (pos.lat == null || pos.lng == null) continue;
    const isHighlighted = cam.id === highlightId;
    const poly = fovPolygon(pos.lat, pos.lng, pos).map(([la, ln]) => toCanvasXY(la, ln));
    const cov = COVERAGE_COLOR[coverageQuality(pos)];
    ctx.beginPath();
    poly.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = cov + (isHighlighted ? "55" : "33");
    ctx.fill();
    ctx.strokeStyle = cov;
    ctx.lineWidth = isHighlighted ? 2 : 1;
    ctx.stroke();
  }
  for (const cam of ordered) {
    const pos = cam.map_position || {};
    if (pos.lat == null || pos.lng == null) continue;
    const [x, y] = toCanvasXY(pos.lat, pos.lng);
    drawCameraIcon(ctx, x, y, pos, cam.status);
    if (cam.id === highlightId) {
      ctx.beginPath();
      ctx.arc(x, y, 15, 0, Math.PI * 2);
      ctx.strokeStyle = "#00E676";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  return canvas.toDataURL("image/png");
}

/**
 * Vue d'ensemble d'un plan IMAGE (Konva) — capture EXACTEMENT ce que
 * l'utilisateur voit actuellement à l'écran (même méthode que exportPng()
 * dans MapCenter.jsx : `stage.toDataURL({pixelRatio})` sans crop, le
 * viewport courant EST le cadrage).
 */
export function captureKonvaView(stageRef, pixelRatio = 2) {
  const stage = stageRef?.current;
  return stage ? stage.toDataURL({ pixelRatio }) : null;
}

/**
 * Crop centré sur UNE caméra pour un plan IMAGE (Konva). `toDataURL()`
 * crope dans l'espace ÉCRAN courant du stage (post pan/zoom), pas dans les
 * coordonnées "monde" d'origine des formes (pos.x/pos.y sont, elles,
 * exprimées dans ce repère monde, indépendant du pan/zoom) — plutôt que de
 * deviner la correspondance entre les deux, on pilote nous-mêmes le
 * pan/zoom du stage le temps de la capture (déterministe), puis on le
 * restaure. `range_m * 4` reproduit EXACTEMENT le facteur visuel déjà
 * utilisé pour dessiner le Wedge du cône FOV (voir MapCenter.jsx, "4 px =
 * 1 m visuel") — le cadrage choisi correspond donc à ce qui est déjà
 * affiché à l'écran, pas à un nouveau calcul.
 */
export function captureKonvaCameraCrop(stageRef, pos, widthPx, heightPx, pixelRatio = 2) {
  const stage = stageRef?.current;
  if (!stage) return null;
  const savedScale = stage.scale();
  const savedPos = stage.position();
  try {
    const radiusPx = (pos.range_m ? pos.range_m * 4 : 60) || 60;
    const desiredScale = Math.min(3, (Math.min(widthPx, heightPx) * 0.32) / radiusPx);
    stage.scale({ x: desiredScale, y: desiredScale });
    stage.position({
      x: widthPx / 2 - (pos.x ?? 0) * desiredScale,
      y: heightPx / 2 - (pos.y ?? 0) * desiredScale,
    });
    stage.batchDraw();
    return stage.toDataURL({ width: widthPx, height: heightPx, pixelRatio });
  } finally {
    stage.scale(savedScale);
    stage.position(savedPos);
    stage.batchDraw();
  }
}
