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
  const { user, logout, t, lang } = useApp();
  const navigate = useNavigate();
  const [warnLeft, setWarnLeft] = useState(null); // secondes restantes
  const [continuing, setContinuing] = useState(false);

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
  // v3.20 · `t()` ne supporte aucune interpolation (un seul argument, la
  // clé) — le 2e argument `{ s: warnLeft }` passé ici était donc
  // silencieusement ignoré, et la chaîne statique traduite ("...dans
  // quelques secondes.") gagnait TOUJOURS face au fallback JS avec le
  // vrai compte à rebours, qui ne s'exécutait donc jamais. D'où le
  // décompte demandé qui n'apparaissait jamais à l'écran.
  const bodyText = lang === "en"
    ? `Your session will expire in ${warnLeft} second${warnLeft > 1 ? "s" : ""}.`
    : `Votre session expire dans ${warnLeft} seconde${warnLeft > 1 ? "s" : ""}.`;
  return (
    <div className="fixed bottom-4 right-4 z-[90] bg-card border-2 border-[#FFB800] p-4 max-w-sm shadow-xl" data-testid="session-expiry-popup">
      <div className="text-sm font-medium mb-1">{t("security.expiry_title")}</div>
      <div className="text-xs text-muted-foreground mb-3 mono" data-testid="session-expiry-countdown">
        {bodyText}
      </div>
      <div className="flex gap-2">
        <button
          disabled={continuing}
          onClick={async () => {
            // v3.20 · Deux bugs corrigés ici :
            // 1) Le refresh token stocké au login est dans "mg_refresh"
            //    (voir AppContext.jsx) et doit être envoyé en Bearer — le
            //    backend n'accepte QUE ce chemin (pas de cookie posé nulle
            //    part, voir auth.py::refresh_token). L'ancien appel
            //    n'envoyait rien du tout : 401 systématique, silencieux.
            // 2) Le nouveau token doit être sauvé sous "mg_token" (pas
            //    "access_token", clé jamais lue ailleurs dans l'appli) —
            //    même correctif déjà fait plus haut pour la LECTURE du
            //    token, oublié ici pour l'ÉCRITURE après refresh.
            setContinuing(true);
            try {
              const refresh = localStorage.getItem("mg_refresh");
              if (!refresh) throw new Error("no refresh token");
              const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/refresh`, {
                method: "POST",
                headers: { Authorization: `Bearer ${refresh}` },
              });
              if (!r.ok) throw new Error(`refresh failed (${r.status})`);
              const d = await r.json();
              if (!d.access_token) throw new Error("no access_token in response");
              localStorage.setItem("mg_token", d.access_token);
              if (d.refresh_token) localStorage.setItem("mg_refresh", d.refresh_token);
              setWarnLeft(null);
              window.location.reload();
            } catch {
              // Refresh impossible (refresh token absent/expiré) — la seule
              // option honnête est de renvoyer vers /login plutôt que de
              // laisser le bouton "Continuer" ne rien faire silencieusement.
              logout();
              navigate("/login");
            } finally {
              setContinuing(false);
            }
          }}
          className="bg-[#0044FF] text-white text-xs px-3 py-1.5 uppercase tracking-wider disabled:opacity-50"
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
