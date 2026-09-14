/**
 * MobileCameras — liste de statut des caméras (v3.91, interface mobile).
 *
 * v3.93 · Peut être filtrée à un site (arrivée depuis MobileHome, tap sur
 * un site) — via `location.state.siteId`/`siteName`, mêmes conventions que
 * `cameraId` déjà utilisé par MobileLive.
 *
 * v3.94 · Tap → ouvre désormais `/m/cameras/:id` (CameraCenter réutilisé
 * tel quel, TOUS ses onglets — demande explicite) au lieu de MobileLive :
 * cet onglet sert à GÉRER une caméra précise (PTZ, audio, réglages), la
 * vue live "regarder plusieurs caméras" reste l'onglet Live séparé.
 *
 * v3.104 · Miniature réelle par caméra (demande explicite : "une micro
 * miniature de la caméra, qui s'actualise toutes seules toutes les 1h")
 * — réutilise `GET /api/stream/{id}/frame.jpeg` (existant, déjà utilisé
 * pour le debug IA/l'aperçu snapshot desktop), en basse résolution
 * (`hd=0`, largement suffisant pour un carré de 36px) pour ne pas
 * solliciter inutilement les caméras. Le paramètre `_h` (numéro d'heure
 * Unix) ne change qu'une fois par heure, donc le navigateur ne recharge
 * l'image qu'à ce rythme — pas de minuteur dédié, le poll `/cameras`
 * déjà en place (20s) suffit à déclencher le re-rendu qui détecte le
 * changement. Icône caméra en fallback (superposée en dessous, révélée
 * par `onError`) si le flux est indisponible.
 */
import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Cctv, Loader2, ChevronLeft } from "lucide-react";

function cameraSnapshotUrl(camId) {
  const token = localStorage.getItem("mg_token") || "";
  const base = process.env.REACT_APP_BACKEND_URL || "";
  const hourBucket = Math.floor(Date.now() / 3_600_000);
  return `${base}/api/stream/${camId}/frame.jpeg?hd=0&_h=${hourBucket}&token=${encodeURIComponent(token)}`;
}

export default function MobileCameras() {
  const { t } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const siteId = location.state?.siteId || null;
  const siteName = location.state?.siteName || "";
  const [cams, setCams] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.get("/cameras").then((r) => { if (alive) setCams(r.data || []); }).catch(() => {});
    load();
    const iv = setInterval(load, 20000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  if (cams === null) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground" data-testid="mobile-cameras-loading">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  const shown = siteId ? cams.filter((c) => c.site_id === siteId) : cams;

  return (
    <div data-testid="mobile-cameras-list">
      {siteId && (
        <button onClick={() => navigate("/m/home")} data-testid="mobile-cameras-back-to-sites"
                className="w-full flex items-center gap-2 px-3 py-2.5 border-b border-border text-left text-sm">
          <ChevronLeft size={16} className="text-muted-foreground" />
          <span className="font-medium">{siteName}</span>
        </button>
      )}
      <div className="p-2 flex flex-col gap-1.5">
        {shown.map((cam) => (
          <button key={cam.id} onClick={() => navigate(`/m/cameras/${cam.id}`)}
                  data-testid="mobile-camera-row"
                  className="flex items-center gap-3 rounded-xl border border-border bg-card p-2.5 text-left">
            <div className="relative w-11 h-11 shrink-0 flex items-center justify-center bg-secondary rounded-lg overflow-hidden">
              <Cctv size={16} className="text-muted-foreground" />
              <img src={cameraSnapshotUrl(cam.id)} alt="" loading="lazy"
                   className="absolute inset-0 w-full h-full object-cover"
                   onError={(e) => { e.currentTarget.style.display = "none"; }} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm truncate">{cam.name}</div>
              <div className="text-[11px] text-muted-foreground truncate">{cam.site_name || cam.ip}</div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <span className={`w-1.5 h-1.5 rounded-full ${cam.status === "online" ? "bg-[#00E676]" : "bg-muted-foreground"}`} />
              <span className="text-[10px] uppercase text-muted-foreground">
                {cam.status === "online" ? t("mobile.cameras_online") : t("mobile.cameras_offline")}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
