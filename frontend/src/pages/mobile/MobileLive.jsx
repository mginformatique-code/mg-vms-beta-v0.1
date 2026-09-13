/**
 * MobileLive — vue live mobile (v3.91-v3.92, interface mobile dédiée).
 *
 * Contrairement à `LiveView.jsx` (mur vidéo desktop, grille dense 1-64
 * caméras), la vue par défaut ici est UNE caméra à la fois en plein écran
 * (navigation par flèches/swipe) — une grille 3×3/4×4 est illisible sur un
 * écran de 375px de large (confirmé par exploration : ~40-90px par tuile).
 * Un mode grille secondaire (densité 4/8/16, esprit "app Reolink" — demande
 * explicite) reste disponible pour un aperçu d'ensemble, tap → bascule en
 * plein écran sur cette caméra.
 *
 * Réutilise tel quel `LivePlayer.jsx` (aucune modification) et
 * `CameraControlOverlay.jsx` en mode par défaut (`visible=true`, pas
 * `visible={hover}` comme le fait LiveView.jsx desktop — le hover n'existe
 * pas au toucher, donc ici les contrôles restent simplement toujours
 * visibles, sans changement de code du composant lui-même).
 */
import React, { useEffect, useState, useRef, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import LivePlayer from "@/components/video/LivePlayer";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import PtzPad from "@/components/mobile/PtzPad";
import Logo from "@/components/Logo";
import { ChevronLeft, ChevronRight, Grid2x2, Grid3x3, LayoutGrid, Loader2, Film } from "lucide-react";

const SWIPE_THRESHOLD_PX = 50;
// v3.92 · Densités de mosaïque proposées (demande explicite : "choisir
// 4-8-16 caméras") — 16 utilise 4 colonnes (tuiles volontairement petites,
// esprit "app Reolink" : aperçu dense, on tape pour agrandir), 4/8 restent
// à 2 colonnes (lisible en portrait). v3.93 : choix via popover empilé
// (icônes 16/8/4/1), pas une rangée de boutons — voir le bouton
// "mobile-live-density-btn" plus bas.

function StatusDot({ online }) {
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${online ? "bg-[#00E676]" : "bg-muted-foreground"}`} />;
}

export default function MobileLive() {
  const { t } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [cams, setCams] = useState(null);
  const [idx, setIdx] = useState(0);
  const [hd, setHd] = useState(true);
  const [view, setView] = useState("single"); // "single" | "grid"
  const [gridSize, setGridSize] = useState(4);
  const [page, setPage] = useState(0);
  const [densityOpen, setDensityOpen] = useState(false);
  const touchStartX = useRef(null);
  const { caps } = useDeviceCapabilities(cams?.[idx]?.id);
  // v3.91 · Arrivée depuis MobileCameras (tap sur une caméra précise) —
  // consommé une seule fois dès que la liste charge, par id (pas par index,
  // robuste à un ordre de tri différent entre les deux appels /cameras).
  const requestedCameraId = useRef(location.state?.cameraId || null);

  useEffect(() => {
    let alive = true;
    const load = () => api.get("/cameras").then((r) => {
      if (!alive) return;
      const list = r.data || [];
      setCams(list);
      if (requestedCameraId.current) {
        const found = list.findIndex((c) => c.id === requestedCameraId.current);
        if (found >= 0) setIdx(found);
        requestedCameraId.current = null;
      }
    }).catch(() => {});
    load();
    const iv = setInterval(load, 20000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // v3.92 · Revient à la 1ère page à chaque changement de densité — une
  // page 2 calculée sur l'ancienne taille n'aurait plus de sens.
  useEffect(() => { setPage(0); }, [gridSize]);

  const goPrev = useCallback(() => setIdx((i) => (cams?.length ? (i - 1 + cams.length) % cams.length : 0)), [cams]);
  const goNext = useCallback(() => setIdx((i) => (cams?.length ? (i + 1) % cams.length : 0)), [cams]);

  const onTouchStart = (e) => { touchStartX.current = e.touches[0].clientX; };
  const onTouchEnd = (e) => {
    if (touchStartX.current == null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (dx > SWIPE_THRESHOLD_PX) goPrev();
    else if (dx < -SWIPE_THRESHOLD_PX) goNext();
    touchStartX.current = null;
  };

  if (cams === null) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground" data-testid="mobile-live-loading">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  if (cams.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm px-6 text-center" data-testid="mobile-live-empty">
        {t("mobile.live_no_cameras")}
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(cams.length / gridSize));
  const pageCams = cams.slice(page * gridSize, page * gridSize + gridSize);
  const cols = gridSize === 16 ? 4 : 2;

  const toolbar = (
    <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-card shrink-0">
      <div className="flex items-center gap-1.5 min-w-0">
        <Logo size={18} className="w-[18px] h-[18px] shrink-0" />
        <span className="text-xs truncate">
          {view === "single" ? `${idx + 1} / ${cams.length}` : `${cams.length} ${t("mobile.cameras_suffix")}`}
        </span>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {view === "single" && (
          <button onClick={() => setHd((v) => !v)} data-testid="mobile-live-hdsd-toggle"
                  className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider border border-border text-muted-foreground">
            {hd ? "HD" : "SD"}
          </button>
        )}
        {/* v3.93 · Sélecteur de densité façon app Reolink : un seul bouton
            grille, tap → popover avec les densités disponibles empilées
            verticalement (16/8/4/vue unique) plutôt qu'une rangée de
            boutons texte. */}
        <div className="relative">
          <button onClick={() => setDensityOpen((v) => !v)} data-testid="mobile-live-density-btn"
                  className="p-1.5 text-muted-foreground hover:text-foreground">
            {view === "single" ? <Grid2x2 size={18} /> : <Grid3x3 size={18} />}
          </button>
          {densityOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setDensityOpen(false)} />
              <div className="absolute right-0 top-full mt-1 z-50 bg-black/90 border border-white/10 flex flex-col p-1 gap-0.5"
                   data-testid="mobile-live-density-popover">
                <button onClick={() => { setGridSize(16); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-16"
                        className={`w-10 h-10 flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 16 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <Grid3x3 size={20} />
                </button>
                <button onClick={() => { setGridSize(8); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-8"
                        className={`w-10 h-10 flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 8 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <LayoutGrid size={20} />
                </button>
                <button onClick={() => { setGridSize(4); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-4"
                        className={`w-10 h-10 flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 4 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <Grid2x2 size={20} />
                </button>
                <button onClick={() => { setView("single"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-1"
                        className="w-10 h-10 flex items-center justify-center hover:bg-white/10">
                  <span className={`w-5 h-5 ${view === "single" ? "bg-[#0044FF]" : "bg-white/30"}`} />
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );

  if (view === "grid") {
    return (
      <div className="h-full flex flex-col">
        {toolbar}
        <div className="flex-1 overflow-y-auto grid gap-1 p-1 content-start" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {pageCams.map((cam) => {
            const i = cams.indexOf(cam);
            return (
              <button key={cam.id} onClick={() => { setIdx(i); setView("single"); }}
                      className="relative bg-black aspect-video overflow-hidden" data-testid="mobile-live-grid-tile">
                <LivePlayer camera={cam} hd={false} className="w-full h-full" dataTestId={`mobile-grid-player-${i}`} />
                <div className="absolute bottom-0 inset-x-0 px-1.5 py-1 bg-gradient-to-t from-black/80 to-transparent flex items-center gap-1">
                  <StatusDot online={cam.status === "online"} />
                  <span className="text-[10px] text-white truncate">{cam.name}</span>
                </div>
              </button>
            );
          })}
        </div>
        {totalPages > 1 && (
          <div className="shrink-0 flex items-center justify-center gap-3 py-2 border-t border-border bg-card">
            <button onClick={() => setPage((p) => (p - 1 + totalPages) % totalPages)} data-testid="mobile-live-grid-prev-page"
                    className="p-1.5 text-muted-foreground"><ChevronLeft size={16} /></button>
            <span className="text-xs mono text-muted-foreground">{page + 1} / {totalPages}</span>
            <button onClick={() => setPage((p) => (p + 1) % totalPages)} data-testid="mobile-live-grid-next-page"
                    className="p-1.5 text-muted-foreground"><ChevronRight size={16} /></button>
          </div>
        )}
      </div>
    );
  }

  const cam = cams[idx];
  return (
    <div className="h-full flex flex-col" data-testid="mobile-live-single">
      {toolbar}
      <div className="relative flex-1 bg-black" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        <LivePlayer camera={cam} hd={hd} bigMute className="w-full h-full" dataTestId="mobile-live-player" />
        <CameraControlOverlay cam={cam} />
        {cams.length > 1 && (
          <>
            <button onClick={goPrev} data-testid="mobile-live-prev"
                    className="absolute left-1 top-1/2 -translate-y-1/2 w-9 h-9 flex items-center justify-center bg-black/50 text-white">
              <ChevronLeft size={20} />
            </button>
            <button onClick={goNext} data-testid="mobile-live-next"
                    className="absolute right-1 top-1/2 -translate-y-1/2 w-9 h-9 flex items-center justify-center bg-black/50 text-white">
              <ChevronRight size={20} />
            </button>
          </>
        )}
        <div className="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 bg-black/60 text-white text-xs truncate max-w-[70%]">
          {cam.name}
        </div>
      </div>
      {/* v3.94 · Bouton "Enregistrements" à côté du pavé PTZ (demande
          explicite : "tu ajoutes à droite ou à gauche ... la recherche
          d'enregistrement de la caméra en question") — réutilise
          Recordings.jsx tel quel via `/m/recordings?camera=`, qu'il lit
          déjà lui-même (aucune modification nécessaire). Affiché même sans
          PTZ (une caméra fixe a aussi des enregistrements à consulter). */}
      <div className="shrink-0 flex items-center justify-center gap-3 py-2 border-t border-border bg-card">
        {caps?.ptz && <PtzPad cameraId={cam.id} />}
        <button onClick={() => navigate(`/m/recordings?camera=${cam.id}`)}
                data-testid="mobile-live-recordings-btn"
                className="w-11 h-11 flex flex-col items-center justify-center gap-0.5 bg-black/60 text-white">
          <Film size={16} />
          <span className="text-[8px] uppercase">{t("mobile.live_recordings")}</span>
        </button>
      </div>
    </div>
  );
}
