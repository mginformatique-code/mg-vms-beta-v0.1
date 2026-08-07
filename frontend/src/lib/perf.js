/**
 * v0.7.e · Wave B · Frontend Perf Instrumentation.
 *
 * Compteurs runtime accessibles via ``window.__mgvms_perf`` pour prouver
 * qu'aucune fuite ne s'installe côté frontend :
 *
 *   window.__mgvms_perf.snapshot()  → {
 *     renders_by_component: { AppContext: 12, LiveView: 3, ... },
 *     intervals_registered: 4,      // via useTrackedInterval
 *     timers_registered: 2,         // via useTrackedTimeout
 *     ws_messages: 152,
 *     ws_reconnects: 0,
 *     ai_detections_map_size: 5,    // caméras suivies en mémoire
 *     ai_detections_evictions: 27,  // entrées obsolètes purgées
 *   }
 *
 * Aussi exposé côté API : GET /api/diagnostics/frontend-perf n'existe pas
 * (rien ne remonte côté backend — c'est un state pur navigateur). Les tests
 * frontend peuvent lire ``window.__mgvms_perf`` directement.
 */
const _state = {
  renders_by_component: {},
  intervals_registered: 0,
  timers_registered: 0,
  ws_messages: 0,
  ws_reconnects: 0,
  ai_detections_map_size: 0,
  ai_detections_evictions: 0,
  started_at: Date.now(),
};

const _activeIntervals = new Set();
const _activeTimers = new Set();

export function bumpRender(component) {
  _state.renders_by_component[component] =
    (_state.renders_by_component[component] || 0) + 1;
}

export function bumpWsMessage() { _state.ws_messages += 1; }
export function bumpWsReconnect() { _state.ws_reconnects += 1; }
export function bumpEviction(n = 1) { _state.ai_detections_evictions += n; }
export function setAiDetectionsMapSize(n) { _state.ai_detections_map_size = n; }

export function registerInterval(id) {
  _activeIntervals.add(id);
  _state.intervals_registered = _activeIntervals.size;
}
export function unregisterInterval(id) {
  _activeIntervals.delete(id);
  _state.intervals_registered = _activeIntervals.size;
}
export function registerTimer(id) {
  _activeTimers.add(id);
  _state.timers_registered = _activeTimers.size;
}
export function unregisterTimer(id) {
  _activeTimers.delete(id);
  _state.timers_registered = _activeTimers.size;
}

export function snapshot() {
  return {
    ..._state,
    uptime_ms: Date.now() - _state.started_at,
    active_intervals: _activeIntervals.size,
    active_timers: _activeTimers.size,
  };
}

export function reset() {
  _state.renders_by_component = {};
  _state.ws_messages = 0;
  _state.ws_reconnects = 0;
  _state.ai_detections_evictions = 0;
  _state.started_at = Date.now();
}

// Expose sur window pour DevTools/Playwright
if (typeof window !== "undefined") {
  window.__mgvms_perf = { snapshot, reset };
}
