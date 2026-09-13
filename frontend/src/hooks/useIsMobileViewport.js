/**
 * useIsMobileViewport — détection responsive + préférence utilisateur
 * persistée (v3.91, chantier interface mobile dédiée).
 *
 * Trois modes possibles, stockés dans `localStorage.mgvms_ui_mode` :
 *   - "auto"    (défaut) : suit `window.matchMedia('(max-width: 767px)')` en direct
 *   - "mobile"  : force l'interface mobile quelle que soit la largeur d'écran
 *   - "desktop" : force l'interface desktop quelle que soit la largeur d'écran
 *
 * Le mode "auto" reste réactif à un redimensionnement de fenêtre (pas juste
 * lu une fois au chargement) — utile en développement pour tester le rendu
 * mobile depuis un navigateur desktop en rétrécissant la fenêtre.
 */
import { useEffect, useState, useCallback } from "react";

const STORAGE_KEY = "mgvms_ui_mode";
const QUERY = "(max-width: 767px)";

function readStoredMode() {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === "mobile" || v === "desktop" ? v : "auto";
}

export default function useIsMobileViewport() {
  const [mode, setModeState] = useState(readStoredMode);
  const [viewportMatches, setViewportMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(QUERY).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const onChange = (e) => setViewportMatches(e.matches);
    // Safari < 14 n'a pas addEventListener sur MediaQueryList — repli addListener.
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener(onChange);
    };
  }, []);

  const setMode = useCallback((next) => {
    if (next === "auto") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, next);
    setModeState(next);
  }, []);

  const isMobile = mode === "mobile" || (mode === "auto" && viewportMatches);
  return { isMobile, mode, setMode };
}
