// v3.35 · Extrapolation cinématique pure — PAS un tracker.
//
// Ne fait ni association ni attribution d'identité : prend un record déjà
// résolu par ByteTrack (TrackState) et calcule où sa boîte devrait se
// trouver "maintenant" en prolongeant le mouvement observé entre les deux
// dernières confirmations réelles. C'est ce qui permet un affichage fluide
// à la cadence de l'écran (25-30 img/s) alors que la détection tourne à
// 1-2 img/s (voir l'audit tracking MG-VMS, section "tracker ou détection ?").
//
// Extrapole le CENTRE de la boîte (pas chaque coin indépendamment) et garde
// sa largeur/hauteur constantes depuis la dernière détection réelle — un
// choix délibéré : extrapoler les 4 coins séparément amplifierait le bruit
// de détection en dérive de taille (boîte qui grossit/rétrécit visiblement).

const MIN_DT_MS = 30; // écart trop court entre 2 confirmations -> vitesse non fiable, on ne l'utilise pas
const MAX_SPEED_NORM_PER_S = 3; // borne de sécurité (coordonnées normalisées/s) — évite une vitesse aberrante de faire sortir la boîte de l'écran sur une mesure bruitée

const clamp = (v) => Math.max(-MAX_SPEED_NORM_PER_S, Math.min(MAX_SPEED_NORM_PER_S, v));

/**
 * @param {object} rec - un record TrackState (bbox, prevBbox, ts, prevTs).
 * @param {number} nowMs
 * @param {number} maxPredictionMs - au-delà, on gèle sur la dernière position
 *   réelle plutôt que de continuer à deviner (voir ai.smoothing.max_prediction_ms
 *   côté config caméra) — une piste toujours confirmée par ByteTrack mais pas
 *   mise à jour depuis longtemps (ralentissement ponctuel du pipeline) ne doit
 *   pas dériver indéfiniment sur une simple extrapolation linéaire.
 * @returns {{bbox: number[], predicted: boolean, ageMs: number}}
 */
export function extrapolate(rec, nowMs, maxPredictionMs) {
  const age = nowMs - rec.ts;
  if (age <= 0) return { bbox: rec.bbox, predicted: false, ageMs: 0 };
  if (age > maxPredictionMs) return { bbox: rec.bbox, predicted: false, ageMs: age };

  const dt = rec.ts - rec.prevTs;
  if (dt < MIN_DT_MS) return { bbox: rec.bbox, predicted: false, ageMs: age };

  const [x1, y1, x2, y2] = rec.bbox;
  const [px1, py1, px2, py2] = rec.prevBbox;
  const w = x2 - x1, h = y2 - y1;
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
  const pcx = (px1 + px2) / 2, pcy = (py1 + py2) / 2;

  const dtS = dt / 1000;
  const vx = clamp((cx - pcx) / dtS);
  const vy = clamp((cy - pcy) / dtS);

  const ageS = age / 1000;
  const ncx = cx + vx * ageS;
  const ncy = cy + vy * ageS;

  return {
    bbox: [ncx - w / 2, ncy - h / 2, ncx + w / 2, ncy + h / 2],
    predicted: true,
    ageMs: age,
  };
}
