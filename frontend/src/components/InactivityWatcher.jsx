/**
 * InactivityWatcher.jsx — v0.5.5.e
 *
 * Surveille l'activité utilisateur et déconnecte automatiquement après
 * une période d'inactivité configurée par l'admin
 * (`GET /api/security/timeout` → `session_hours`, exprimé en heures).
 *
 * Événements écoutés : mousemove, mousedown, keydown, scroll, touchstart,
 * wheel. Un timer se remet à zéro à chaque événement (throttlé à 5s pour
 * éviter le spam). Après `session_hours * 3600` s sans activité :
 *   1. Appel logout() (efface les tokens)
 *   2. Redirect `/login?reason=inactivity`
 *   3. Login.jsx affiche : « Vous avez été déconnecté en raison de
 *      l'inactivité (politique de timeout) »
 *
 * Silencieux si :
 *   - Aucun user connecté (idle avant login)
 *   - Impossible de récupérer /api/security/timeout (fallback 8h)
 */
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "wheel"];
const THROTTLE_MS = 5000;
const DEFAULT_HOURS = 8;

export default function InactivityWatcher() {
  const { user, logout } = useApp();
  const navigate = useNavigate();
  const lastActivityRef = useRef(Date.now());
  const lastRecordedRef = useRef(0);
  const timerRef = useRef(null);
  const hoursRef = useRef(DEFAULT_HOURS);

  useEffect(() => {
    if (!user) return undefined;

    const recordActivity = () => {
      const now = Date.now();
      // Throttle : au max 1 update toutes les 5s
      if (now - lastRecordedRef.current < THROTTLE_MS) return;
      lastRecordedRef.current = now;
      lastActivityRef.current = now;
    };

    // Récupère le timeout configuré (best-effort)
    api.get("/security/timeout").then((r) => {
      const h = Number(r?.data?.session_hours);
      if (h && h > 0 && h <= 24) hoursRef.current = h;
    }).catch(() => {/* fallback DEFAULT_HOURS */});

    // Attache les listeners d'activité
    ACTIVITY_EVENTS.forEach((ev) => window.addEventListener(ev, recordActivity, { passive: true }));

    // Tick de vérification toutes les 15s
    timerRef.current = setInterval(() => {
      const idleMs = Date.now() - lastActivityRef.current;
      const maxMs = hoursRef.current * 3600 * 1000;
      if (idleMs >= maxMs) {
        clearInterval(timerRef.current);
        ACTIVITY_EVENTS.forEach((ev) => window.removeEventListener(ev, recordActivity));
        // Déconnexion + redirect avec raison.
        try { logout(); } catch (_) { /* ignore */ }
        navigate("/login?reason=inactivity", { replace: true });
      }
    }, 15000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      ACTIVITY_EVENTS.forEach((ev) => window.removeEventListener(ev, recordActivity));
    };
  }, [user, logout, navigate]);

  return null;
}
