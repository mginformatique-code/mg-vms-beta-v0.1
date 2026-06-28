import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { translations } from "@/i18n";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

export function AppProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=auth
  const [lang, setLang] = useState(() => localStorage.getItem("mg_lang") || "fr");
  const [theme, setTheme] = useState(() => localStorage.getItem("mg_theme") || "dark");

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
    setUser(data.user);
    return { ok: true };
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch (e) {}
    localStorage.removeItem("mg_token");
    setUser(false);
  };

  const toggleTheme = () => setTheme((p) => (p === "dark" ? "light" : "dark"));
  const toggleLang = () => setLang((p) => (p === "fr" ? "en" : "fr"));

  const can = (role) => {
    const lvl = { guest: 0, readonly: 1, client: 2, technician: 3, admin: 4 };
    return user && lvl[user.role] >= lvl[role];
  };

  return (
    <AppContext.Provider value={{ user, setUser, login, logout, lang, setLang, toggleLang, theme, toggleTheme, t, can }}>
      {children}
    </AppContext.Provider>
  );
}
