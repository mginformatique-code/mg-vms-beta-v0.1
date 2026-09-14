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
 * (`hd=0`, largement suffisant pour un carré de 44px) pour ne pas
 * solliciter inutilement les caméras.
 *
 * v3.106 · La v3.104 changeait juste l'URL de l'`<img>` une fois par
 * heure — ça évitait de recharger entre deux rendus React, mais PAS
 * entre deux rechargements de PAGE (F5) : sans en-tête de cache côté
 * `frame.jpeg` (flux dynamique), chaque `<img>` neuve retape la caméra
 * en direct, d'où la lenteur signalée ("ça charge la photo à chaque
 * actualisation... c'est long"). Remplacé par un vrai cache CÔTÉ
 * NAVIGATEUR : `fetch()` le JPEG une fois, converti en data URL, stocké
 * dans localStorage avec un horodatage — tant que l'entrée a moins de
 * `THUMB_TTL_MS` (1h30, milieu de la fourchette "1-2h" demandée), AUCUNE
 * requête réseau n'est refaite, même après un rechargement complet de
 * page. Icône caméra en fallback tant qu'aucune miniature n'est en cache
 * ou disponible.
 */
import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Cctv, Loader2, ChevronLeft } from "lucide-react";

const THUMB_TTL_MS = 90 * 60 * 1000;
const THUMB_CACHE_PREFIX = "mgvms_cam_thumb_";

function readCachedThumb(camId) {
  try {
    const raw = localStorage.getItem(THUMB_CACHE_PREFIX + camId);
    if (!raw) return null;
    const { data, at } = JSON.parse(raw);
    if (!data || Date.now() - at > THUMB_TTL_MS) return null;
    return data;
  } catch { return null; }
}

function useCachedCameraThumb(camId) {
  const [dataUrl, setDataUrl] = useState(() => readCachedThumb(camId));

  useEffect(() => {
    const cached = readCachedThumb(camId);
    if (cached) { setDataUrl(cached); return; }
    let alive = true;
    const token = localStorage.getItem("mg_token") || "";
    const base = process.env.REACT_APP_BACKEND_URL || "";
    fetch(`${base}/api/stream/${camId}/frame.jpeg?hd=0`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error("snapshot indisponible"); return r.blob(); })
      .then((blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      }))
      .then((data) => {
        if (!alive) return;
        setDataUrl(data);
        try { localStorage.setItem(THUMB_CACHE_PREFIX + camId, JSON.stringify({ data, at: Date.now() })); } catch {}
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [camId]);

  return dataUrl;
}

function CameraRow({ cam, onClick, t }) {
  const thumb = useCachedCameraThumb(cam.id);
  return (
    <button onClick={onClick} data-testid="mobile-camera-row"
            className="flex items-center gap-3 rounded-xl border border-border bg-card p-2.5 text-left">
      <div className="relative w-11 h-11 shrink-0 flex items-center justify-center bg-secondary rounded-lg overflow-hidden">
        <Cctv size={16} className="text-muted-foreground" />
        {thumb && <img src={thumb} alt="" className="absolute inset-0 w-full h-full object-cover" />}
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
  );
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
          <CameraRow key={cam.id} cam={cam} t={t} onClick={() => navigate(`/m/cameras/${cam.id}`)} />
        ))}
      </div>
    </div>
  );
}
