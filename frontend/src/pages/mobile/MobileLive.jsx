/**
 * MobileLive — vue live mobile (v3.91, interface mobile dédiée).
 *
 * Contrairement à `LiveView.jsx` (mur vidéo desktop, grille dense 1-64
 * caméras), la vue par défaut ici est UNE caméra à la fois en plein écran
 * (navigation par flèches/swipe) — une grille 3×3/4×4 est illisible sur un
 * écran de 375px de large (confirmé par exploration : ~40-90px par tuile).
 * Un mode grille secondaire (2 colonnes max) reste disponible pour un aperçu
 * d'ensemble, tap → bascule en plein écran sur cette caméra.
 *
 * Réutilise tel quel `LivePlayer.jsx` (aucune modification) et
 * `CameraControlOverlay.jsx` en mode par défaut (`visible=true`, pas
 * `visible={hover}` comme le fait LiveView.jsx desktop — le hover n'existe
 * pas au toucher, donc ici les contrôles restent simplement toujours
 * visibles, sans changement de code du composant lui-même).
 */
import React, { useEffect, useState, useRef, useCallback } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import LivePlayer from "@/components/video/LivePlayer";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import PtzPad from "@/components/mobile/PtzPad";
import { ChevronLeft, ChevronRight, Grid2x2, Rows, Loader2 } from "lucide-react";

const SWIPE_THRESHOLD_PX = 50;

function StatusDot({ online }) {
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${online ? "bg-[#00E676]" : "bg-muted-foreground"}`} />;
}

export default function MobileLive() {
  const { t } = useApp();
  const location = useLocation();
  const [cams, setCams] = useState(null);
  const [idx, setIdx] = useState(0);
  const [view, setView] = useState("single"); // "single" | "grid"
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

  const toolbar = (
    <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-card shrink-0">
      <div className="text-xs truncate min-w-0">
        {view === "single" ? `${idx + 1} / ${cams.length}` : `${cams.length} ${t("mobile.cameras_suffix")}`}
      </div>
      <button onClick={() => setView((v) => (v === "single" ? "grid" : "single"))}
              data-testid="mobile-live-view-toggle"
              className="p-1.5 text-muted-foreground hover:text-foreground">
        {view === "single" ? <Grid2x2 size={18} /> : <Rows size={18} />}
      </button>
    </div>
  );

  if (view === "grid") {
    return (
      <div className="h-full flex flex-col">
        {toolbar}
        <div className="flex-1 overflow-y-auto grid grid-cols-2 gap-1 p-1 content-start">
          {cams.map((cam, i) => (
            <button key={cam.id} onClick={() => { setIdx(i); setView("single"); }}
                    className="relative bg-black aspect-video overflow-hidden" data-testid="mobile-live-grid-tile">
              <LivePlayer camera={cam} hd={false} className="w-full h-full" dataTestId={`mobile-grid-player-${i}`} />
              <div className="absolute bottom-0 inset-x-0 px-1.5 py-1 bg-gradient-to-t from-black/80 to-transparent flex items-center gap-1">
                <StatusDot online={cam.status === "online"} />
                <span className="text-[10px] text-white truncate">{cam.name}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  const cam = cams[idx];
  return (
    <div className="h-full flex flex-col" data-testid="mobile-live-single">
      {toolbar}
      <div className="relative flex-1 bg-black" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        <LivePlayer camera={cam} hd className="w-full h-full" dataTestId="mobile-live-player" />
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
      {caps?.ptz && (
        <div className="shrink-0 flex justify-center py-2 border-t border-border bg-card">
          <PtzPad cameraId={cam.id} />
        </div>
      )}
    </div>
  );
}
