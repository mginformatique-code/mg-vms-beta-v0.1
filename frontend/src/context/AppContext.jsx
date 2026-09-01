import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import api from "@/lib/api";
import { translations } from "@/i18n";
import { toast } from "sonner";
import { bumpWsMessage, bumpWsReconnect, bumpEviction, setAiDetectionsMapSize } from "@/lib/perf";

// v0.7.e · Wave B · TTL des entrées aiDetections (une caméra qui n'a
// pas émis depuis N secondes est purgée pour éviter l'accumulation
// mémoire quand des caméras sont supprimées ou passent offline).
const AI_DETECTIONS_TTL_MS = 45_000;
const AI_DETECTIONS_PRUNE_INTERVAL_MS = 30_000;

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

export function AppProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=auth
  const [lang, setLang] = useState(() => localStorage.getItem("mg_lang") || "fr");
  const [theme, setTheme] = useState(() => localStorage.getItem("mg_theme") || "dark");
  const [liveMetrics, setLiveMetrics] = useState(null);
  const [liveAlert, setLiveAlert] = useState(null);
  const [alertPing, setAlertPing] = useState(0);
  const [aiDetections, setAiDetections] = useState({}); // { camera_id -> {boxes, counts, ts, motion_pct} }

  const t = useCallback((key) => translations[lang]?.[key] ?? translations.fr[key] ?? key, [lang]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("mg_theme", theme);
  }, [theme]);

  useEffect(() => { localStorage.setItem("mg_lang", lang); }, [lang]);

  useEffect(() => {
    const token = localStorage.getItem("mg_token");
    if (!token) { setUser(false); return; }
    api.get("/auth/me").then((r) => setUser(r.data)).catch(() => {
      localStorage.removeItem("mg_token");
      setUser(false);
    });
  }, []);

  const login = async (email, password, totp_code) => {
    const { data } = await api.post("/auth/login", { email, password, totp_code });
    if (data.requires_2fa) return { requires_2fa: true };
    localStorage.setItem("mg_token", data.access_token);
    if (data.refresh_token) localStorage.setItem("mg_refresh", data.refresh_token);
    // Marque une connexion FRAÎCHE (pas une restauration de session au
    // rechargement de page) — consommé une seule fois par Layout pour
    // déclencher le popup de bienvenue juste après le login.
    sessionStorage.setItem("mg_just_logged_in", "1");
    setUser(data.user);
    return { ok: true };
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch (e) {}
    localStorage.removeItem("mg_token");
    localStorage.removeItem("mg_refresh");
    setUser(false);
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");
  const toggleLang = () => setLang(lang === "fr" ? "en" : "fr");

  const can = (role) => {
    const lvl = { guest: 0, readonly: 1, client: 2, technician: 3, admin: 4 };
    return user && lvl[user.role] >= lvl[role];
  };

  const hasPerm = (perm) => {
    if (!user) return false;
    if (user.role === "admin") return true;
    return !!(user.permissions && user.permissions[perm]);
  };

  // ---- WebSocket temps réel ----
  useEffect(() => {
    if (!user) return;
    const token = localStorage.getItem("mg_token");
    if (!token) return;
    let ws, alive = true, retry;
    // v1.0-rc4.4 · WebSocket : si REACT_APP_BACKEND_URL est vide (build HTTPS
    // reproductible qui passe par Nginx), on construit l'URL depuis window.location.
    // Sinon on garde le comportement historique (preview Emergent, dev direct).
    const envBase = process.env.REACT_APP_BACKEND_URL || "";
    const base = envBase
      ? envBase.replace(/^http/, "ws")
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
    const connect = () => {
      try {
        ws = new WebSocket(`${base}/api/ws?token=${token}`);
        ws.onmessage = (e) => {
          bumpWsMessage();
          let msg;
          try { msg = JSON.parse(e.data); } catch { return; }
          if (msg.type === "metrics") setLiveMetrics(msg.data);
          else if (msg.type === "ai_detections") {
            // v0.7.e · Wave B · on ne recrée la map que si le payload est
            // effectivement différent (référence stable ⇒ pas de re-render
            // des consommateurs inutile).
            setAiDetections((prev) => {
              const camId = msg.data.camera_id;
              const nowTs = msg.data.timestamp;
              const existing = prev[camId];
              const nextEntry = {
                boxes: msg.data.boxes || [],
                counts: msg.data.counts || {},
                ts: nowTs,
                _rx_at: Date.now(),   // timestamp local pour pruning TTL
                motion_pct: msg.data.motion_pct,
                retail: msg.data.retail || null,  // état plugin anti-vol (dwell/visites), par track_id
              };
              // Skip si les données sont identiques (même ts + mêmes boxes count)
              if (existing && existing.ts === nowTs &&
                  (existing.boxes?.length || 0) === nextEntry.boxes.length) {
                return prev;
              }
              const next = { ...prev, [camId]: nextEntry };
              setAiDetectionsMapSize(Object.keys(next).length);
              return next;
            });
          }
          else if (msg.type === "alert") {
            setLiveAlert(msg.data);
            setAlertPing((p) => p + 1);
            const fr = (localStorage.getItem("mg_lang") || "fr") === "fr";
            const txt = `${fr ? "Alerte" : "Alert"}: ${msg.data.message}`;
            if (msg.data.severity === "critical") toast.error(txt);
            else if (msg.data.severity === "warning") toast.warning(txt);
            else toast.info(txt);
          }
        };
        ws.onclose = () => { if (alive) { bumpWsReconnect(); retry = setTimeout(connect, 4000); } };
        ws.onerror = () => { try { ws.close(); } catch (e) {} };
      } catch (e) { if (alive) retry = setTimeout(connect, 4000); }
    };
    connect();
    return () => { alive = false; clearTimeout(retry); try { ws && ws.close(); } catch (e) {} };
  }, [user]);

  // v0.7.e · Wave B · Pruning périodique des aiDetections stales
  // (caméras supprimées ou passées offline depuis longtemps).
  useEffect(() => {
    if (!user) return;
    const iv = setInterval(() => {
      const cutoff = Date.now() - AI_DETECTIONS_TTL_MS;
      setAiDetections((prev) => {
        let evicted = 0;
        const next = {};
        for (const [k, v] of Object.entries(prev)) {
          if ((v?._rx_at ?? 0) >= cutoff) next[k] = v;
          else evicted += 1;
        }
        if (evicted === 0) return prev;
        bumpEviction(evicted);
        setAiDetectionsMapSize(Object.keys(next).length);
        return next;
      });
    }, AI_DETECTIONS_PRUNE_INTERVAL_MS);
    return () => clearInterval(iv);
  }, [user]);

  return (
    <AppContext.Provider value={{ user, setUser, login, logout, lang, setLang, toggleLang, theme, setTheme, toggleTheme, t, can, hasPerm, liveMetrics, liveAlert, alertPing, aiDetections }}>
      {children}
    </AppContext.Provider>
  );
}
