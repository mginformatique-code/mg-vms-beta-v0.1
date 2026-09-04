// v3.35 · Mémoire des pistes ByteTrack, côté client, pour UNE caméra.
//
// Ne fait aucune association détection <-> piste — ByteTrack a déjà fait ce
// travail côté serveur (voir backend/pipeline_v2/tracking.py). Ce module se
// contente d'indexer par track_id ce que ByteTrack a déjà décidé, pour que
// MotionPredictor puisse interpoler entre deux confirmations réelles.
//
// Sémantique "remplacement complet" à chaque ingest() : un track_id absent
// du dernier message reçu est retiré immédiatement (jamais de "boîte
// fantôme") — c'est un miroir exact du comportement actuel de
// AppContext.jsx, qui remplace `boxes` en entier à chaque message plutôt que
// de fusionner. Un track que ByteTrack a perdu disparaît donc à l'instant où
// le backend cesse de l'inclure, avec ou sans lissage actif.

export class TrackState {
  constructor() {
    /** @type {Map<number|string, object>} track_id -> record */
    this.tracks = new Map();
    /** Détections sans track_id (tracker désactivé pour cette caméra) — pas
     * de continuité possible, affichées telles quelles, jamais interpolées. */
    this.untracked = [];
  }

  /**
   * @param {Array} rawBoxes - `overlay_boxes` tel que diffusé par le backend
   *   (bbox_norm, label, confidence, track_id, ...).
   * @param {number} timestampMs - horodatage de réception (performance.now()
   *   côté client — pas l'horodatage serveur, pour rester cohérent avec
   *   l'horloge utilisée par le rAF d'interpolation).
   */
  ingest(rawBoxes, timestampMs) {
    const boxes = rawBoxes || [];
    const nextIds = new Set();
    for (const b of boxes) {
      if (b.track_id === null || b.track_id === undefined) continue;
      nextIds.add(b.track_id);
      const prev = this.tracks.get(b.track_id);
      this.tracks.set(b.track_id, {
        id: b.track_id,
        cls: b.cls,
        label: b.label,
        confidence: b.confidence,
        vehicle_color: b.vehicle_color,
        keypoints_norm: b.keypoints_norm,
        bbox: b.bbox_norm,
        ts: timestampMs,
        // Snapshot de la position précédente CONFIRMÉE — sert uniquement au
        // calcul de vitesse (MotionPredictor). Si c'est la 1re confirmation
        // de ce track_id, prev == courant (vitesse nulle au démarrage, pas
        // de saut fantôme dès l'apparition d'un objet).
        prevBbox: prev ? prev.bbox : b.bbox_norm,
        prevTs: prev ? prev.ts : timestampMs,
      });
    }
    for (const id of Array.from(this.tracks.keys())) {
      if (!nextIds.has(id)) this.tracks.delete(id);
    }
    this.untracked = boxes.filter((b) => b.track_id === null || b.track_id === undefined);
  }

  values() {
    return this.tracks.values();
  }

  get size() {
    return this.tracks.size;
  }
}
