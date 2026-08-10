/**
 * SessionExpiryWatcher.jsx — v0.5.4
 *
 * Décode le JWT côté client pour détecter l'approche de l'expiration et
 * affiche un dialog "Votre session expire dans X secondes" 60 secondes avant.
 * Options :
 *   - Continuer : refresh implicite (le backend accepte le token courant si
 *     encore valide ; le prochain login prolongera de session_hours).
 *   - Déconnexion : logout + redirect /login.
 *
 * Aucun risque de faux positif : si le JWT ne peut être décodé (pas de exp),
 * le watcher reste silencieux.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";

function decodeExp(token) {
  try {
    const b64 = token.split(".")[1];
    const json = JSON.parse(atob(b64.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch { return null; }
}

export default function SessionExpiryWatcher() {
  const { user, logout, t } = useApp();
  const navigate = useNavigate();
  const [warnLeft, setWarnLeft] = useState(null); // secondes restantes

  useEffect(() => {
    if (!user) { setWarnLeft(null); return; }
    // v1.0-rc4.5 · Fix clé de token — le JWT est stocké dans "mg_token"
    // (voir lib/api.js), PAS "access_token". L'ancien nom laissait le
    // watcher silencieux en permanence.
    const token = localStorage.getItem("mg_token");
    if (!token) return;
    const expMs = decodeExp(token);
    if (!expMs) return;
    const iv = setInterval(() => {
      const leftSec = Math.floor((expMs - Date.now()) / 1000);
      if (leftSec <= 0) {
        clearInterval(iv);
        setWarnLeft(null);
        logout();
        navigate("/login");
      } else if (leftSec <= 60) {
        setWarnLeft(leftSec);
      } else {
        setWarnLeft(null);
      }
    }, 1000);
    return () => clearInterval(iv);
  }, [user, logout, navigate]);

  if (warnLeft == null) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[90] bg-card border-2 border-[#FFB800] p-4 max-w-sm shadow-xl" data-testid="session-expiry-popup">
      <div className="text-sm font-medium mb-1">{t("security.expiry_title")}</div>
      <div className="text-xs text-muted-foreground mb-3">
        {t("security.expiry_body", { s: warnLeft }) || `Votre session expire dans ${warnLeft} secondes.`}
      </div>
      <div className="flex gap-2">
        <button
          onClick={async () => {
            // Refresh token: appeler /api/auth/refresh (best-effort)
            try {
              const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/refresh`,
                                     { method: "POST", credentials: "include" });
              const d = await r.json();
              if (d.access_token) {
                localStorage.setItem("access_token", d.access_token);
                setWarnLeft(null);
                window.location.reload();
              }
            } catch { /* ignore */ }
          }}
          className="bg-[#0044FF] text-white text-xs px-3 py-1.5 uppercase tracking-wider"
          data-testid="session-expiry-continue"
        >
          {t("security.expiry_continue")}
        </button>
        <button
          onClick={() => { logout(); navigate("/login"); }}
          className="border border-[#FF3333] text-[#FF3333] text-xs px-3 py-1.5 uppercase tracking-wider"
          data-testid="session-expiry-logout"
        >
          {t("security.expiry_logout")}
        </button>
      </div>
    </div>
  );
}
