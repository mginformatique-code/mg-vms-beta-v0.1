// v3.36 · Registre léger des diagnostics tracking, un par caméra montée.
//
// Pourquoi : les métriques (Detection FPS, Display FPS, Prediction active,
// âge dernière détection) vivaient à l'origine en incrustation sur chaque
// tuile de la mosaïque live — signalé comme un chevauchement d'information
// supplémentaire ("trop d'info se chevauchent"). Déplacé dans le panneau
// debug app-level existant (AppDebugPanel.jsx, Ctrl+Shift+D, admin) plutôt
// que dans le menu caméra — c'est le bon niveau pour ce genre d'info à
// l'échelle de 100+ caméras (une vue tabulaire, pas une incrustation par
// tuile).
//
// Chaque OverlayCanvas (LiveView.jsx) enregistre un getter (pas une valeur
// figée) à son montage, et le retire à son démontage. Aucun état n'est
// dupliqué ici — juste une table de callbacks vers l'interpolateur réel de
// chaque tuile actuellement affichée.

const getters = new Map();

export function register(cameraId, getSnapshot) {
  getters.set(cameraId, getSnapshot);
}

export function unregister(cameraId) {
  getters.delete(cameraId);
}

/** @returns {Record<string, object>} camera_id -> snapshot diagnostics */
export function snapshotAll() {
  const now = performance.now();
  const out = {};
  for (const [cameraId, getSnapshot] of getters) {
    try {
      out[cameraId] = getSnapshot(now);
    } catch (e) {
      out[cameraId] = { error: String(e) };
    }
  }
  return out;
}
