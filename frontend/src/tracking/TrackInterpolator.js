// v3.35 · Point d'entrée du module tracking côté frontend — la SEULE chose
// que LiveView.jsx (et tout autre consommateur d'affichage) importe.
//
// Rôle : recevoir les tracks ByteTrack (via ingest), calculer la vitesse et
// extrapoler la position (délégué à MotionPredictor), expirer proprement
// (délégué à TrackState), et fournir à chaque frame d'écran un état prêt à
// dessiner + des métriques de diagnostic. Aucune règle métier ANPR/alerte
// ici — uniquement de l'affichage, voir l'audit tracking MG-VMS §"Intégration
// ANPR" : les stages backend (ROI, ANPR, événements) consomment la sortie
// BRUTE de ByteTrack, jamais celle-ci.
//
// v3.36 · Les diagnostics (Detection FPS, Display FPS, Prediction active,
// âge dernière détection) sont maintenant lus depuis le panneau debug
// app-level (AppDebugPanel.jsx, Ctrl+Shift+D) plutôt qu'incrustés sur
// chaque tuile — voir getDiagnosticsSnapshot(), appelable à tout moment
// (même sans boucle de rendu active) et DiagnosticsRegistry.js pour
// l'enregistrement par caméra.

import { TrackState } from "./TrackState";
import { extrapolate } from "./MotionPredictor";

const DETECTION_FPS_WINDOW_MS = 5000;
const RENDER_FPS_WINDOW_MS = 2000;

export class TrackInterpolator {
  constructor() {
    this.state = new TrackState();
    this._detectionTimestamps = [];
    this._renderTimestamps = [];
    this._lastDetectionTs = null;
    this._lastDisplayFps = 0;
    this._lastPredictionActive = false;
  }

  /** Appelé quand un nouveau message `ai_detections` arrive pour cette caméra. */
  ingest(rawBoxes, timestampMs) {
    this.state.ingest(rawBoxes, timestampMs);
    this._lastDetectionTs = timestampMs;
    this._detectionTimestamps.push(timestampMs);
    const cutoff = timestampMs - DETECTION_FPS_WINDOW_MS;
    while (this._detectionTimestamps.length && this._detectionTimestamps[0] < cutoff) {
      this._detectionTimestamps.shift();
    }
  }

  /**
   * Appelé à chaque frame de la boucle de rendu (requestAnimationFrame côté
   * appelant — ce module ne possède pas sa propre boucle, pour rester un
   * simple calculateur d'état plutôt qu'un composant).
   *
   * @param {number} nowMs
   * @param {boolean} smoothingEnabled - `ai.smoothing.enabled` de la caméra.
   *   Désactivé -> comportement HISTORIQUE à l'identique (dernière position
   *   réelle telle quelle, aucune extrapolation) : c'est le repli garanti,
   *   jamais un chemin dégradé différent.
   * @param {number} maxPredictionMs - `ai.smoothing.max_prediction_ms`.
   */
  getRenderState(nowMs, smoothingEnabled, maxPredictionMs) {
    this._renderTimestamps.push(nowMs);
    const cutoff = nowMs - RENDER_FPS_WINDOW_MS;
    while (this._renderTimestamps.length && this._renderTimestamps[0] < cutoff) {
      this._renderTimestamps.shift();
    }

    const boxes = [];
    let predictionActive = false;

    for (const rec of this.state.values()) {
      let bbox = rec.bbox;
      let predicted = false;
      if (smoothingEnabled) {
        const ex = extrapolate(rec, nowMs, maxPredictionMs);
        bbox = ex.bbox;
        predicted = ex.predicted;
        if (predicted) predictionActive = true;
      }
      boxes.push({
        cls: rec.cls, label: rec.label, confidence: rec.confidence,
        vehicle_color: rec.vehicle_color, keypoints_norm: rec.keypoints_norm,
        track_id: rec.id, bbox_norm: bbox, predicted,
      });
    }
    // Détections sans track_id (tracker désactivé sur cette caméra) : aucune
    // interpolation possible sans identité stable — affichées telles quelles.
    for (const b of this.state.untracked) boxes.push({ ...b, predicted: false });

    this._lastDisplayFps = Math.round(this._renderTimestamps.length / (RENDER_FPS_WINDOW_MS / 1000));
    this._lastPredictionActive = predictionActive;

    return { boxes, diagnostics: this.getDiagnosticsSnapshot(nowMs) };
  }

  /**
   * Snapshot diagnostics, appelable à tout instant (poll du panneau debug,
   * ~1x/s) — indépendant de la boucle de rendu : Detection FPS et âge de la
   * dernière détection restent exacts même si aucune boucle rAF ne tourne
   * (lissage désactivé sur cette caméra). Display FPS / Prediction active
   * reflètent la dernière boucle de rendu connue (figés à 0/false si le
   * lissage n'est pas actif — rien à mesurer dans ce cas).
   */
  getDiagnosticsSnapshot(nowMs) {
    const cutoff = nowMs - DETECTION_FPS_WINDOW_MS;
    const recent = this._detectionTimestamps.filter((t) => t >= cutoff).length;
    const detectionFps = Math.round((recent / (DETECTION_FPS_WINDOW_MS / 1000)) * 10) / 10;
    const lastDetectionAgeMs = this._lastDetectionTs != null ? Math.max(0, nowMs - this._lastDetectionTs) : null;
    return {
      detectionFps,
      displayFps: this._lastDisplayFps,
      predictionActive: this._lastPredictionActive,
      lastDetectionAgeMs,
      trackedCount: this.state.size,
    };
  }
}
