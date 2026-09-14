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
import React, { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { toast } from "sonner";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import LivePlayer from "@/components/video/LivePlayer";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import MobilePtzPanel from "@/components/mobile/MobilePtzPanel";
import MobileFocusTimeline from "@/components/mobile/MobileFocusTimeline";
import Logo from "@/components/Logo";
import {
  ChevronLeft, ChevronRight, Grid2x2, Grid3x3, LayoutGrid, Loader2, Film, Move,
  Camera as CameraIcon, Video as VideoIcon, Square, Volume2, VolumeX, Maximize, Minimize,
} from "lucide-react";

const SWIPE_THRESHOLD_PX = 50;
const CAMERA_ORDER_KEY = "mgvms_mobile_camera_order";
// v3.92 · Densités de mosaïque proposées (demande explicite : "choisir
// 4-8-16 caméras") — 16 utilise 4 colonnes (tuiles volontairement petites,
// esprit "app Reolink" : aperçu dense, on tape pour agrandir), 4/8 restent
// à 2 colonnes (lisible en portrait). v3.93 : choix via popover empilé
// (icônes 16/8/4/1), pas une rangée de boutons — voir le bouton
// "mobile-live-density-btn" plus bas.

function StatusDot({ online }) {
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${online ? "bg-[#00E676]" : "bg-muted-foreground"}`} />;
}

// v3.113 · La grille rendait un <LivePlayer> (donc une connexion WebRTC
// complète) PAR TUILE — 16 connexions vidéo simultanées, chacune avec son
// propre décodeur, dépasse ce que la plupart des téléphones peuvent tenir
// (plantage signalé). Remplacé par des tuiles en aperçu JPEG rafraîchi
// (même endpoint que la miniature de MobileCameras.jsx, réutilisé ici à un
// rythme plus rapide car c'est un aperçu "live-ish", pas une icône
// statique) — aucune connexion vidéo tant qu'on ne tape pas la tuile pour
// passer en vue plein écran (seul endroit qui ouvre un vrai flux WebRTC).
// Corrige aussi partiellement la fiabilité WebRTC en grille dense (une
// grille qui ne fait plus AUCUNE connexion WebRTC ne peut plus en perdre).
const LONG_PRESS_MS = 350;

// v3.114 · Glisser-déposer des tuiles pour réorganiser la grille (demande
// explicite). Le drag&drop HTML5 natif (`draggable`) n'existe pas sur
// tactile — implémenté à la main : un appui long (350ms) démarre le
// déplacement (distingue "taper pour ouvrir" de "glisser pour
// réorganiser"), puis `document.elementFromPoint` sous le doigt pendant
// `touchmove` détecte la tuile survolée pour réordonner en direct
// (géré par le parent via `onReorderOver`/`onReorderEnd`).
function GridTile({ cam, onClick, onDragStart, onReorderOver, onReorderEnd, isDragging }) {
  const [thumbUrl, setThumbUrl] = useState(null);
  const pressTimer = useRef(null);
  const movedRef = useRef(false);

  useEffect(() => {
    let alive = true;
    let currentUrl = null;
    const token = localStorage.getItem("mg_token") || "";
    const base = process.env.REACT_APP_BACKEND_URL || "";
    const fetchFrame = () => {
      fetch(`${base}/api/stream/${cam.id}/frame.jpeg?hd=0`, { headers: { Authorization: `Bearer ${token}` } })
        .then((r) => (r.ok ? r.blob() : Promise.reject()))
        .then((blob) => {
          if (!alive) return;
          const url = URL.createObjectURL(blob);
          if (currentUrl) URL.revokeObjectURL(currentUrl);
          currentUrl = url;
          setThumbUrl(url);
        })
        .catch(() => {});
    };
    fetchFrame();
    const iv = setInterval(fetchFrame, 6000);
    return () => { alive = false; clearInterval(iv); if (currentUrl) URL.revokeObjectURL(currentUrl); };
  }, [cam.id]);

  const handleTouchStart = () => {
    movedRef.current = false;
    pressTimer.current = setTimeout(() => { onDragStart(cam.id); }, LONG_PRESS_MS);
  };
  const handleTouchMove = (e) => {
    movedRef.current = true;
    if (!isDragging) { clearTimeout(pressTimer.current); return; }
    const touch = e.touches[0];
    const el = document.elementFromPoint(touch.clientX, touch.clientY);
    const tileEl = el?.closest("[data-cam-id]");
    if (tileEl) onReorderOver(tileEl.dataset.camId);
  };
  const handleTouchEnd = () => {
    clearTimeout(pressTimer.current);
    if (isDragging) onReorderEnd();
  };

  return (
    <button data-cam-id={cam.id} onClick={() => { if (!isDragging && !movedRef.current) onClick(); }}
            onTouchStart={handleTouchStart} onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd} onTouchCancel={handleTouchEnd}
            style={{ touchAction: isDragging ? "none" : "pan-y" }}
            className={`relative bg-black aspect-video overflow-hidden rounded-lg transition-transform ${isDragging ? "opacity-60 scale-95 ring-2 ring-[#0044FF]" : ""}`}
            data-testid="mobile-live-grid-tile">
      {thumbUrl ? (
        <img src={thumbUrl} alt="" className="w-full h-full object-cover" />
      ) : (
        <div className="w-full h-full flex items-center justify-center"><CameraIcon size={18} className="text-white/20" /></div>
      )}
      <div className="absolute bottom-0 inset-x-0 px-1.5 py-1 bg-gradient-to-t from-black/80 to-transparent flex items-center gap-1">
        <StatusDot online={cam.status === "online"} />
        <span className="text-[10px] text-white truncate">{cam.name}</span>
      </div>
    </button>
  );
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
  // v3.113 · "quand on clique sur live on arrive direct sur une vue caméra
  // sans choisir laquelle... un système à la Reolink avec des tuiles pour
  // sélectionner la caméra avant d'être envoyé sur la vue live" — la grille
  // de sélection est désormais la vue PAR DÉFAUT ; seule une arrivée
  // ciblée depuis MobileCameras (state.cameraId, tap sur une caméra
  // précise) saute directement en vue plein écran, comme avant.
  const [view, setView] = useState(location.state?.cameraId ? "single" : "grid"); // "single" | "grid"
  const [gridSize, setGridSize] = useState(8);
  const [densityOpen, setDensityOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isLandscape, setIsLandscape] = useState(() => window.matchMedia("(orientation: landscape)").matches);
  const videoWrapRef = useRef(null);
  // v3.114 · Ordre personnalisé des tuiles (glisser-déposer, demande
  // explicite) — persisté en localStorage, fusionné avec la liste réelle
  // à chaque rafraîchissement (une caméra ajoutée/supprimée n'efface pas
  // l'ordre choisi pour les autres).
  const [camOrder, setCamOrder] = useState(null); // [camId, ...] | null
  const [draggingId, setDraggingId] = useState(null);
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
  // v3.114 · `orderedCams` — liste affichée après application de l'ordre
  // personnalisé (grille ET vue plein écran partagent le même ordre, pour
  // que les flèches précédent/suivant restent cohérentes avec la grille).
  const orderedCams = useMemo(() => {
    if (!cams) return null;
    if (!camOrder) return cams;
    const byId = new Map(cams.map((c) => [c.id, c]));
    return camOrder.map((id) => byId.get(id)).filter(Boolean);
  }, [cams, camOrder]);
  const { caps } = useDeviceCapabilities(orderedCams?.[idx]?.id);
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
      // v3.114 · Fusionne l'ordre sauvegardé (localStorage) avec la liste
      // réelle DANS LE MÊME EFFET que le chargement des caméras — évite un
      // rendu intermédiaire où `camOrder` est encore vide pendant que
      // `cams` est déjà rempli, qui décalerait temporairement l'index visé
      // par `requestedCameraId`.
      setCamOrder((prevOrder) => {
        let base = prevOrder;
        if (!base) {
          try {
            const saved = JSON.parse(localStorage.getItem(CAMERA_ORDER_KEY) || "null");
            if (Array.isArray(saved)) base = saved;
          } catch { /* ignore */ }
        }
        const ids = list.map((c) => c.id);
        const idSet = new Set(ids);
        const kept = (base || []).filter((id) => idSet.has(id));
        const missing = ids.filter((id) => !kept.includes(id));
        const finalOrder = [...kept, ...missing];
        if (requestedCameraId.current) {
          const found = finalOrder.indexOf(requestedCameraId.current);
          if (found >= 0) setIdx(found);
          requestedCameraId.current = null;
        }
        return finalOrder;
      });
    }).catch(() => {});
    load();
    const iv = setInterval(load, 20000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const handleDragStart = useCallback((camId) => setDraggingId(camId), []);
  const handleReorderOver = useCallback((overId) => {
    setDraggingId((currentDraggingId) => {
      if (!currentDraggingId || overId === currentDraggingId) return currentDraggingId;
      setCamOrder((prev) => {
        const base = prev || (orderedCams ? orderedCams.map((c) => c.id) : []);
        const next = [...base];
        const from = next.indexOf(currentDraggingId);
        const to = next.indexOf(overId);
        if (from === -1 || to === -1) return prev;
        next.splice(from, 1);
        next.splice(to, 0, currentDraggingId);
        return next;
      });
      return currentDraggingId;
    });
  }, [orderedCams]);
  const handleReorderEnd = useCallback(() => {
    setDraggingId(null);
    setCamOrder((order) => {
      if (order) { try { localStorage.setItem(CAMERA_ORDER_KEY, JSON.stringify(order)); } catch { /* ignore */ } }
      return order;
    });
  }, []);

  // v3.98 · Ferme le panneau PTZ si on change de caméra (swipe/flèches)
  // pendant qu'il est ouvert — évite de piloter le PTZ de la caméra
  // précédente en croyant contrôler la nouvelle.
  useEffect(() => { setPanelMode(null); }, [idx]);

  // v3.113 · Bouton plein écran (demande explicite) — plein écran sur le
  // conteneur vidéo lui-même (pas tout le document) pour que les contrôles
  // superposés (CameraControlOverlay, flèches, nom de la caméra) restent
  // visibles ET fonctionnels une fois en plein écran, pas seulement le
  // flux vidéo brut.
  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);
  useEffect(() => {
    const mq = window.matchMedia("(orientation: landscape)");
    const handler = (e) => setIsLandscape(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  const toggleFullscreen = () => {
    if (!videoWrapRef.current) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      videoWrapRef.current.requestFullscreen?.().catch(() => {
        toast.error(t("mobile.live_fullscreen_unavailable"));
      });
    }
  };

  const goPrev = useCallback(() => setIdx((i) => (orderedCams?.length ? (i - 1 + orderedCams.length) % orderedCams.length : 0)), [orderedCams]);
  const goNext = useCallback(() => setIdx((i) => (orderedCams?.length ? (i + 1) % orderedCams.length : 0)), [orderedCams]);

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

  const cols = gridSize === 16 ? 4 : gridSize === 8 ? 3 : 2;

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
            boutons texte.
            v3.113 · En vue plein écran, ce bouton ramène directement à la
            grille de sélection (plus besoin d'ouvrir le popover pour
            revenir en arrière) — le popover de densité ne concerne que le
            mode grille lui-même. */}
        <div className="relative">
          <button onClick={() => (view === "single" ? setView("grid") : setDensityOpen((v) => !v))}
                  data-testid="mobile-live-density-btn"
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
        {/* v3.113 · Plus de pagination (demande explicite : "qu'on puisse
            défiler vers le bas de l'écran pour afficher le reste des
            cams") — la grille garde le nombre de colonnes choisi mais
            grandit avec TOUTES les caméras, défilement vertical naturel. */}
        <div className="flex-1 overflow-y-auto grid gap-1 p-1 content-start" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {orderedCams.map((cam, i) => (
            <GridTile key={cam.id} cam={cam} onClick={() => { setIdx(i); setView("single"); }}
                      isDragging={draggingId === cam.id}
                      onDragStart={handleDragStart} onReorderOver={handleReorderOver} onReorderEnd={handleReorderEnd} />
          ))}
        </div>
      </div>
    );
  }

  const cam = orderedCams[idx];
  // v3.113 · "quand je mets en paysage ça rend très mal" — la vidéo restait
  // à ~32% de hauteur même en paysage (où la hauteur d'écran disponible
  // est bien plus faible qu'en portrait), donnant une bande vidéo minuscule
  // au milieu d'un grand vide. En plein écran (bouton dédié ci-dessous),
  // l'élément occupe tout le viewport nativement (Fullscreen API).
  const videoFlex = isFullscreen ? "1 1 100%" : isLandscape ? "0 0 70%" : "0 0 32%";
  return (
    <div className="h-full flex flex-col" data-testid="mobile-live-single">
      {!isFullscreen && toolbar}
      <div ref={videoWrapRef} className="relative bg-black shrink-0" style={{ flex: videoFlex }}
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
        {/* v3.113 · Le bouton plein écran vit dans la rangée d'icônes
            ci-dessous (pas sur la vidéo — demande explicite passée : "que
            rien ne soit sur l'emplacement de la vidéo"). Cette icône de
            SORTIE n'existe que PENDANT le plein écran lui-même : une fois
            actif, la rangée d'icônes n'est plus visible (hors de l'élément
            mis en plein écran par le navigateur), donc un moyen de sortir
            doit vivre à l'intérieur de ce même élément. */}
        {isFullscreen && (
          <button onClick={toggleFullscreen} data-testid="mobile-live-fullscreen-exit-btn"
                  className="absolute top-2 right-2 w-8 h-8 rounded-full flex items-center justify-center bg-black/50 text-white">
            <Minimize size={16} />
          </button>
        )}
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
          <button onClick={toggleFullscreen} data-testid="mobile-live-fullscreen-btn"
                  className="flex flex-col items-center gap-0.5 text-muted-foreground">
            <Maximize size={20} />
            <span className="text-[9px] uppercase">{t("mobile.live_fullscreen")}</span>
          </button>
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

        {/* v3.103 · Timeline sous la rangée d'icônes, toujours visible,
            indépendante de panelMode.
            v3.114 · Remplacée par la VRAIE référence demandée — la
            timeline d'ACTIVITÉ façon `FocusTimeline` de LiveView.jsx
            desktop (événements + plaques récents), pas les segments
            d'enregistrement (qui ont déjà leur page dédiée). */}
        <MobileFocusTimeline cameraId={cam.id} />
      </div>
    </div>
  );
}
