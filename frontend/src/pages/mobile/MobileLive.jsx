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
import MobilePtzPanel from "@/components/mobile/MobilePtzPanel";
import MobileRecordingsTimeline from "@/components/mobile/MobileRecordingsTimeline";
import Logo from "@/components/Logo";
import {
  ChevronLeft, ChevronRight, Grid2x2, Grid3x3, LayoutGrid, Loader2, Film, Move,
  Camera as CameraIcon, Video as VideoIcon, Square, Volume2, VolumeX,
} from "lucide-react";

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
  // v3.102 · Qualité par défaut SD (demande explicite) — HD reste un choix
  // actif de l'utilisateur (bouton HD/SD), pas un défaut qui consomme de la
  // bande passante avant même d'avoir été demandé.
  const [hd, setHd] = useState(false);
  const [view, setView] = useState("single"); // "single" | "grid"
  const [gridSize, setGridSize] = useState(4);
  const [page, setPage] = useState(0);
  const [densityOpen, setDensityOpen] = useState(false);
  // v3.102 · Remplace l'overlay plein écran v3.98 par un panneau INLINE
  // sous la vidéo (demande explicite, référence app Reolink : "ça s'ouvre
  // dans l'encadré blanc, rien devant la vue live") — `panelMode` choisit
  // ce qui s'affiche dans ce panneau ("ptz" ou rien), la vidéo reste
  // toujours visible au-dessus, jamais couverte.
  const [panelMode, setPanelMode] = useState(null); // null | "ptz"
  // v3.101 · Mute/screenshot/enregistrement pilotés depuis CETTE barre
  // d'icônes (plus d'overlay sur la vidéo, demande explicite) — LivePlayer
  // expose ses actions via ref et son état via ce callback.
  const playerRef = useRef(null);
  const [playerStatus, setPlayerStatus] = useState({ muted: true, recording: false, mode: "connecting", busy: false });
  const touchStart = useRef(null);
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
  // v3.98 · Ferme le panneau PTZ si on change de caméra (swipe/flèches)
  // pendant qu'il est ouvert — évite de piloter le PTZ de la caméra
  // précédente en croyant contrôler la nouvelle.
  useEffect(() => { setPanelMode(null); }, [idx]);

  const goPrev = useCallback(() => setIdx((i) => (cams?.length ? (i - 1 + cams.length) % cams.length : 0)), [cams]);
  const goNext = useCallback(() => setIdx((i) => (cams?.length ? (i + 1) % cams.length : 0)), [cams]);

  // v3.109 · Même correctif que VehicleDetail (MobileEvents.jsx) : exige un
  // geste nettement horizontal (|dx| > |dy|) avant de changer de caméra,
  // pour ne jamais confondre un swipe volontaire avec un frôlement diagonal.
  const onTouchStart = (e) => { touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; };
  const onTouchEnd = (e) => {
    if (touchStart.current == null) return;
    const dx = e.changedTouches[0].clientX - touchStart.current.x;
    const dy = e.changedTouches[0].clientY - touchStart.current.y;
    if (Math.abs(dx) > Math.abs(dy)) {
      if (dx > SWIPE_THRESHOLD_PX) goPrev();
      else if (dx < -SWIPE_THRESHOLD_PX) goNext();
    }
    touchStart.current = null;
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
                  className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md border border-border text-muted-foreground">
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
              <div className="absolute right-0 top-full mt-1 z-50 bg-black/90 border border-white/10 rounded-xl flex flex-col p-1 gap-0.5"
                   data-testid="mobile-live-density-popover">
                <button onClick={() => { setGridSize(16); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-16"
                        className={`w-10 h-10 rounded-lg flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 16 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <Grid3x3 size={20} />
                </button>
                <button onClick={() => { setGridSize(8); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-8"
                        className={`w-10 h-10 rounded-lg flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 8 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <LayoutGrid size={20} />
                </button>
                <button onClick={() => { setGridSize(4); setView("grid"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-4"
                        className={`w-10 h-10 rounded-lg flex items-center justify-center hover:bg-white/10 ${
                          view === "grid" && gridSize === 4 ? "text-[#0044FF]" : "text-white"
                        }`}>
                  <Grid2x2 size={20} />
                </button>
                <button onClick={() => { setView("single"); setDensityOpen(false); }}
                        data-testid="mobile-live-density-1"
                        className="w-10 h-10 rounded-lg flex items-center justify-center hover:bg-white/10">
                  <span className={`w-5 h-5 rounded-md ${view === "single" ? "bg-[#0044FF]" : "bg-white/30"}`} />
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
                      className="relative bg-black aspect-video overflow-hidden rounded-lg" data-testid="mobile-live-grid-tile">
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
      {/* v3.103 · Réduit à ~32% (demande explicite : "ça prend encore pas
          mal de place, il faudrait qu'il reste la moitié de la place en
          bas de page au moins" — la v3.102 à 45% n'était pas assez
          agressive). Avec la barre du haut (~48px) déduite, le panneau du
          bas conserve nettement plus de la moitié de l'écran. */}
      <div className="relative bg-black shrink-0" style={{ flex: "0 0 32%" }}
           onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        <LivePlayer ref={playerRef} camera={cam} hd={hd} externalControls onStatusChange={setPlayerStatus}
                    className="w-full h-full" dataTestId="mobile-live-player" />
        <CameraControlOverlay cam={cam} />
        {cams.length > 1 && (
          <>
            <button onClick={goPrev} data-testid="mobile-live-prev"
                    className="absolute left-1 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full flex items-center justify-center bg-black/50 text-white">
              <ChevronLeft size={20} />
            </button>
            <button onClick={goNext} data-testid="mobile-live-next"
                    className="absolute right-1 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full flex items-center justify-center bg-black/50 text-white">
              <ChevronRight size={20} />
            </button>
          </>
        )}
        <div className="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs truncate max-w-[70%]">
          {cam.name}
        </div>
      </div>

      {/* v3.98 · Rangée d'icônes façon app Reolink, plus le panneau PTZ
          (demande explicite) : "PTZ" ouvre son contenu ICI, dans ce même
          panneau sous la vidéo — jamais par-dessus l'image. "Lecture"
          navigue directement vers les enregistrements de cette caméra
          (Recordings.jsx réutilisé tel quel via `/m/recordings?camera=`).
          v3.101 · Son/capture photo/enregistrement vivent dans cette même
          rangée (pilotés via `playerRef`, LivePlayer expose ses actions). */}
      <div className="flex-1 overflow-y-auto flex flex-col bg-card" data-testid="mobile-live-panel">
        <div className="shrink-0 flex items-center justify-center gap-4 py-2 border-b border-border flex-wrap">
          {/* v3.99 · Bouton toujours affiché (demande explicite : "le bouton
              met 15 sec à apparaître" — il était gated par `caps?.ptz`, dont
              le chargement asynchrone causait ce délai visible/le
              "pop-in"). Le statut PTZ réel n'est vérifié qu'à l'ouverture
              du panneau, plus sur la présence du bouton lui-même. */}
          <button onClick={() => setPanelMode((m) => (m === "ptz" ? null : "ptz"))} data-testid="mobile-live-ptz-open-btn"
                  className={`flex flex-col items-center gap-0.5 ${panelMode === "ptz" ? "text-[#0044FF]" : "text-muted-foreground"}`}>
            <Move size={20} />
            <span className="text-[9px] uppercase">PTZ</span>
          </button>
          <button onClick={() => navigate(`/m/recordings?camera=${cam.id}`)}
                  data-testid="mobile-live-recordings-btn"
                  className="flex flex-col items-center gap-0.5 text-muted-foreground">
            <Film size={20} />
            <span className="text-[9px] uppercase">{t("mobile.live_recordings")}</span>
          </button>
          {playerStatus.mode === "webrtc" && (
            <button onClick={() => playerRef.current?.toggleMute()} data-testid="mobile-live-mute-btn"
                    className="flex flex-col items-center gap-0.5 text-muted-foreground">
              {playerStatus.muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
              <span className="text-[9px] uppercase">{playerStatus.muted ? t("mobile.live_muted") : t("mobile.live_unmuted")}</span>
            </button>
          )}
          {playerStatus.mode === "webrtc" && (
            <button onClick={() => playerRef.current?.takeScreenshot()} disabled={playerStatus.busy}
                    data-testid="mobile-live-screenshot-btn"
                    className="flex flex-col items-center gap-0.5 text-muted-foreground disabled:opacity-40">
              <CameraIcon size={20} />
              <span className="text-[9px] uppercase">{t("mobile.live_screenshot")}</span>
            </button>
          )}
          {playerStatus.mode === "webrtc" && (
            <button onClick={() => playerRef.current?.toggleRecord()} data-testid="mobile-live-record-btn"
                    className={`flex flex-col items-center gap-0.5 ${playerStatus.recording ? "text-[#FF3333]" : "text-muted-foreground"}`}>
              {playerStatus.recording ? <Square size={20} /> : <VideoIcon size={20} />}
              <span className="text-[9px] uppercase">{playerStatus.recording ? t("mobile.live_stop") : t("mobile.live_record")}</span>
            </button>
          )}
        </div>

        {panelMode === "ptz" && (
          caps === null ? (
            <div className="flex-1 flex items-center justify-center py-8"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
          ) : caps?.ptz ? (
            <MobilePtzPanel cameraId={cam.id} />
          ) : (
            <div className="text-muted-foreground text-sm px-6 py-8 text-center" data-testid="mobile-ptz-unavailable">
              {t("mobile.ptz_always_note")}
            </div>
          )
        )}

        {/* v3.103 · Timeline des enregistrements du jour, toujours visible
            sous la rangée d'icônes (demande explicite : "en dessous des
            boutons faudrait ajouter la timeline des camera stp, que les
            elements de la timeline soit cliquables aussi") — indépendante
            de panelMode, pas seulement affichée quand le panneau PTZ est
            ouvert. */}
        <MobileRecordingsTimeline cameraId={cam.id} />
      </div>
    </div>
  );
}
