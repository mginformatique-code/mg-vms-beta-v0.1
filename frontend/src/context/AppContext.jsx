import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import api from "@/lib/api";
import { translations } from "@/i18n";
import { toast } from "sonner";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

export function AppProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=auth
  const [lang, setLang] = useState(() => localStorage.getItem("mg_lang") || "fr");
  const [theme, setTheme] = useState(() => localStorage.getItem("mg_theme") || "dark");
  const [liveMetrics, setLiveMetrics] = useState(null);
  const [liveAlert, setLiveAlert] = useState(null);
  const [alertPing, setAlertPing] = useState(0);

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

  // ---- WebSocket temps réel ----
  useEffect(() => {
    if (!user) return;
    const token = localStorage.getItem("mg_token");
    if (!token) return;
    let ws, alive = true, retry;
    const base = process.env.REACT_APP_BACKEND_URL.replace(/^http/, "ws");
    const connect = () => {
      try {
        ws = new WebSocket(`${base}/api/ws?token=${token}`);
        ws.onmessage = (e) => {
          let msg;
          try { msg = JSON.parse(e.data); } catch { return; }
          if (msg.type === "metrics") setLiveMetrics(msg.data);
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
        ws.onclose = () => { if (alive) retry = setTimeout(connect, 4000); };
        ws.onerror = () => { try { ws.close(); } catch (e) {} };
      } catch (e) { if (alive) retry = setTimeout(connect, 4000); }
    };
    connect();
    return () => { alive = false; clearTimeout(retry); try { ws && ws.close(); } catch (e) {} };
  }, [user]);

  return (
    <AppContext.Provider value={{ user, setUser, login, logout, lang, setLang, toggleLang, theme, setTheme, toggleTheme, t, can, liveMetrics, liveAlert, alertPing }}>
      {children}
    </AppContext.Provider>
  );
}
