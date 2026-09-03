import React, { useEffect, useState, useRef, useMemo } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import LivePlayer from "@/components/video/LivePlayer";
import { Maximize2, Camera as CamIcon, Move, ZoomIn, ZoomOut, Circle, Eye, EyeOff, X, ChevronLeft, ChevronRight, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Home, User, Car, Truck, Bike, PawPrint, ScanLine, Flame, AlertOctagon, HardHat, MapPin, Activity, Lightbulb, Moon, Siren, Volume2, RefreshCw, LayoutGrid, Save, RotateCcw, GripVertical, Play, Loader2 } from "lucide-react";
import { toast } from "sonner";

const LAYOUTS = [1, 4, 9, 16, 25, 36, 49, 64];

// Palette IA — une couleur distincte par classe
const CLASS_COLORS = {
  "Personne":   "#00E676",  // vert
  "Voiture":    "#0044FF",  // bleu
  "Camion":     "#FFB800",  // orange
  "Bus":        "#FFB800",
  "Moto":       "#FF66CC",  // rose
  "Vélo":       "#00E1FF",  // cyan
  "Animal":     "#B47CFF",  // violet
  "Chien":      "#B47CFF",
  "Chat":       "#B47CFF",
};
const colorFor = (label) => CLASS_COLORS[label] || "#FF3333";

function OverlayCanvas({ cam, boxes, showOverlay }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!showOverlay) return;
    const canvas = ref.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    // Ajuste taille canvas à celle de l'élément parent (le <img>)
    const w = parent.clientWidth, h = parent.clientHeight;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    if (!boxes || !boxes.length) return;
    ctx.lineWidth = 2;
    ctx.font = "bold 11px ui-monospace, monospace";
    for (const b of boxes) {
      const [x1, y1, x2, y2] = b.bbox_norm;
      const rx = x1 * w, ry = y1 * h, rw = (x2 - x1) * w, rh = (y2 - y1) * h;
      const color = colorFor(b.label);
      ctx.strokeStyle = color;
      ctx.strokeRect(rx, ry, rw, rh);
      // Label
      const label = `${b.label} ${(b.confidence * 100).toFixed(0)}%${b.vehicle_color ? " · " + b.vehicle_color : ""}${b.track_id ? " #" + b.track_id : ""}`;
      const metrics = ctx.measureText(label);
      const th = 15;
      ctx.fillStyle = color;
      ctx.fillRect(rx, Math.max(0, ry - th), metrics.width + 8, th);
      ctx.fillStyle = "#000";
      ctx.fillText(label, rx + 4, Math.max(11, ry - 3));
    }
  }, [boxes, showOverlay, cam?.id]);
  if (!showOverlay) return null;
  return <canvas ref={ref} className="absolute inset-0 w-full h-full pointer-events-none" data-testid="ai-overlay" />;
}

function FeedInner({ cam, idx, canPtz, hd, showOverlay, aiState, focused, onToggleFocus }) {
  const [hover, setHover] = useState(false);
  const [showPtz, setShowPtz] = useState(false);
  const online = cam?.status === "online";
  const ptz = async (command) => { try { await api.post(`/cameras/${cam.id}/ptz?command=${command}`); } catch (e) { /* ignore */ } };

  const boxes = aiState?.boxes || [];
  const counts = aiState?.counts || {};
  const totalDetected = Object.values(counts).reduce((a, b) => a + b, 0);
  // Détection sous-flux (résolution < 1280x720) — le user a probablement gardé un sub-stream
  const [subW, subH] = (cam?.resolution || "").split(/x/i).map((n) => parseInt(n, 10) || 0);
  const isSubStream = online && subW > 0 && subH > 0 && (subW < 1280 || subH < 720);
  return (
    <div
      className={`relative bg-black overflow-hidden group aspect-video cursor-pointer transition-shadow ${focused ? "ring-2 ring-[#00E5FF]" : "hover:ring-1 hover:ring-[#0044FF]/60"}`}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onClick={(e) => { if (!e.target.closest("[data-ptz-btn]")) onToggleFocus?.(cam?.id); }}
      title={cam ? (focused ? "Cliquez pour revenir à la mosaïque" : "Cliquez pour agrandir") : ""}
      data-testid="video-feed"
    >
      {cam?.id ? (
        <>
          <LivePlayer camera={cam} hd={hd} className="w-full h-full" dataTestId="wall-player" />
          {cam?.detect_enabled && <OverlayCanvas cam={cam} boxes={boxes} showOverlay={showOverlay} />}
          {/* Overlay No Signal superposé — le player reste monté en dessous */}
          {!online && (
            <div className="absolute inset-0 flex items-center justify-center bg-[#0a0a0a]/85 pointer-events-none z-10" data-testid="feed-no-signal-overlay">
              <div className="text-center">
                <CamIcon size={24} className="mx-auto text-[#FF3333] mb-1" />
                <span className="text-[10px] uppercase tracking-wider text-[#FF3333]">No Signal</span>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-[#0a0a0a]">
          <div className="text-center"><CamIcon size={24} className="mx-auto text-white/30 mb-1" /><span className="text-[10px] uppercase tracking-wider text-white/30">—</span></div>
        </div>
      )}
      <div className="absolute top-0 inset-x-0 flex items-center justify-between px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
        <span className="text-[10px] mono text-white truncate">{cam?.name || `CAM-${idx + 1}`}</span>
        <div className="flex items-center gap-1.5">
          {online && cam?.detect_enabled && showOverlay && totalDetected > 0 && (
            <span className="text-[9px] mono px-1.5 py-0.5 bg-black/70 text-white" data-testid="feed-ai-counter">
              {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(" · ")}
            </span>
          )}
          {online && cam?.resolution && (
            <span className="text-[9px] mono px-1 text-white/80 bg-black/50" data-testid="feed-resolution">{cam.resolution}</span>
          )}
          {online && <span className="flex items-center gap-1 text-[9px] mono text-[#00E676]"><Circle size={6} className="fill-[#00E676] rec-dot" /> LIVE</span>}
          {focused && <X size={13} className="text-white/80" />}
        </div>
      </div>
      {isSubStream && (
        <div className="absolute top-8 inset-x-0 px-2" data-testid="substream-warning">
          <div className="text-[10px] mono px-2 py-1 bg-[#FFB800]/95 text-black flex items-center gap-1.5">
            ⚠ Sous-flux détecté ({cam.resolution}) — ouvrez le diagnostic pour re-sélectionner le profil principal.
          </div>
        </div>
      )}
      <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-gradient-to-t from-black/70 to-transparent flex justify-between">
        <span className="text-[9px] mono text-white/70">{cam?.site_name || ""}</span>
        <span className="text-[9px] mono text-white/70">{new Date().toLocaleTimeString()}</span>
      </div>
      {/* v0.4 · Overlay contrôles caméra (Projecteur, IR, Sirène, TTS, Reboot)
          v3.19 · Toujours monté (visible pilote l'opacité) — voir
          CameraControlOverlay.jsx pour pourquoi le démontage sur hover
          cassait le bouton lumière. */}
      {online && cam?.id && (
        <CameraControlOverlay cam={cam} visible={hover} />
      )}
      {/* v3.19 · PTZ déplacé du centre plein écran (gênait la vue) vers un
          coin, avec un bouton dédié pour afficher/masquer le pavé — ne
          s'ouvre plus automatiquement au survol. */}
      {online && cam?.ptz_enabled && canPtz && (hover || showPtz) && (
        <button data-ptz-btn onClick={(e) => { e.stopPropagation(); setShowPtz((v) => !v); }}
                className={`absolute top-8 right-2 w-7 h-7 flex items-center justify-center text-white transition-colors ${showPtz ? "bg-[#0044FF]" : "bg-black/70 hover:bg-[#0044FF]"}`}
                data-testid="ptz-toggle" title={showPtz ? "Masquer les contrôles PTZ" : "Afficher les contrôles PTZ"}>
          <Move size={14} />
        </button>
      )}
      {showPtz && online && cam?.ptz_enabled && canPtz && (
        <div className="absolute top-16 right-2 bg-black/60 p-1.5" data-testid="ptz-controls">
          <div className="flex items-center gap-1.5">
            {/* Pan/Tilt cross */}
            <div className="grid grid-cols-3 gap-0.5">
              <div />
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("tilt_up"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-up" title="Tilt up">
                <ArrowUp size={14} />
              </button>
              <div />
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("pan_left"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-left" title="Pan left">
                <ArrowLeft size={14} />
              </button>
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("home"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#00E676] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-home" title="Home preset">
                <Home size={12} />
              </button>
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("pan_right"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-right" title="Pan right">
                <ArrowRight size={14} />
              </button>
              <div />
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("tilt_down"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-down" title="Tilt down">
                <ArrowDown size={14} />
              </button>
              <div />
            </div>
            {/* Zoom column */}
            <div className="flex flex-col gap-0.5">
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("zoom_in"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-zoom-in" title="Zoom in">
                <ZoomIn size={14} />
              </button>
              <button data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz("zoom_out"); }}
                      className="w-7 h-7 bg-black/70 hover:bg-[#0044FF] flex items-center justify-center text-white transition-colors"
                      data-testid="ptz-zoom-out" title="Zoom out">
                <ZoomOut size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// React.memo custom : évite les re-renders quand seule une prop non-visuelle change
// (ex : cam.last_seen mis à jour à chaque tick camera_status_loop → sinon tous les
// Feed re-render toutes les 20 s à cause du polling `/api/cameras`).
// On re-render UNIQUEMENT si un champ pertinent pour l'affichage a changé.
const Feed = React.memo(FeedInner, (prev, next) => {
  // Comparaison rapide des props scalaires
  if (prev.idx !== next.idx || prev.canPtz !== next.canPtz || prev.hd !== next.hd
      || prev.showOverlay !== next.showOverlay || prev.focused !== next.focused
      || prev.onToggleFocus !== next.onToggleFocus) return false;
  // Comparaison des propriétés utiles de la caméra (ignore `last_seen` etc.)
  const a = prev.cam || {}; const b = next.cam || {};
  if (a.id !== b.id) return false;
  if (a.status !== b.status) return false;
  if (a.stream_pipeline !== b.stream_pipeline) return false;
  if (a.name !== b.name) return false;
  if (a.site_name !== b.site_name) return false;
  if (a.resolution !== b.resolution) return false;
  if (a.detect_enabled !== b.detect_enabled) return false;
  if (a.ptz_enabled !== b.ptz_enabled) return false;
  // aiState change souvent (2 s) — comparaison par référence suffit
  if (prev.aiState !== next.aiState) return false;
  return true;  // égal → skip re-render
});

// Mapping type/label → icône + libellé + couleur (style Reolink)
// Icônes lucide-react cohérentes avec le reste de l'app.
// v0.7.e · Wave E · Palette timeline type Reolink alignée sur la demande
// utilisateur : 🟦 Personne, 🟩 Voiture, 🟨 Moto, 🟧 Camion, 🟪 Bus,
// 🟥 Animal, 🟫 Vélo. Les alertes critiques (feu/arme/bagarre) restent
// en rouge/orange pour cohérence sémantique.
const EVENT_KIND_META = {
  person:     { icon: User,        label: "Personne", color: "#0044FF" },   // 🟦 bleu
  car:        { icon: Car,         label: "Voiture",  color: "#00E676" },   // 🟩 vert
  motorbike:  { icon: Bike,        label: "Moto",     color: "#FFB800" },   // 🟨 jaune
  motorcycle: { icon: Bike,        label: "Moto",     color: "#FFB800" },
  truck:      { icon: Truck,       label: "Camion",   color: "#FF6600" },   // 🟧 orange
  bus:        { icon: Truck,       label: "Bus",      color: "#9333EA" },   // 🟪 violet
  animal:     { icon: PawPrint,    label: "Animal",   color: "#FF3333" },   // 🟥 rouge
  dog:        { icon: PawPrint,    label: "Chien",    color: "#FF3333" },
  cat:        { icon: PawPrint,    label: "Chat",     color: "#FF3333" },
  bird:       { icon: PawPrint,    label: "Oiseau",   color: "#FF3333" },
  bicycle:    { icon: Bike,        label: "Vélo",     color: "#8B4513" },   // 🟫 marron
  plate:      { icon: ScanLine,    label: "Plaque",   color: "#FFD700" },   // jaune vif (spécifique ANPR)
  // Alertes critiques (priorité visuelle rouge/orange)
  fire:       { icon: Flame,       label: "Feu",      color: "#FF3333" },
  smoke:      { icon: Flame,       label: "Fumée",    color: "#FF6600" },
  weapon:     { icon: AlertOctagon,label: "Arme",     color: "#FF3333" },
  fight:      { icon: AlertOctagon,label: "Bagarre",  color: "#FF3333" },
  fall:       { icon: AlertOctagon,label: "Chute",    color: "#FF6600" },
  ppe:        { icon: HardHat,     label: "EPI",      color: "#FFB800" },
  zone:       { icon: MapPin,      label: "Zone",     color: "#0044FF" },
  motion:     { icon: Activity,    label: "Mouvement",color: "#66CCFF" },   // cyan discret (bas signal)
};

function _kindFromEvent(ev) {
  const raw = String(ev.type || ev.label || ev.class || "").toLowerCase();
  // Ordre : plus spécifique → plus générique
  if (ev.plate || raw.includes("plate")) return "plate";
  if (raw.includes("fire")) return "fire";
  if (raw.includes("smoke")) return "smoke";
  if (raw.includes("weapon") || raw.includes("gun") || raw.includes("knife")) return "weapon";
  if (raw.includes("fight") || raw.includes("violence")) return "fight";
  if (raw.includes("fall")) return "fall";
  if (raw.includes("ppe") || raw.includes("helmet") || raw.includes("vest")) return "ppe";
  if (raw.includes("zone")) return "zone";
  if (raw.includes("truck") || raw.includes("camion")) return "truck";
  if (raw.includes("bus")) return "bus";
  if (raw.includes("bicycle") || raw.includes("velo")) return "bicycle";
  if (raw.includes("motorcycle") || raw.includes("motorbike") || raw.includes("moto")) return "motorbike";
  if (raw.includes("dog")) return "dog";
  if (raw.includes("cat")) return "cat";
  if (raw.includes("bird")) return "bird";
  if (raw.includes("animal")) return "animal";
  if (raw.includes("car") || raw.includes("vehicle") || raw.includes("voiture")) return "car";
  if (raw.includes("person") || raw.includes("human") || raw.includes("people")) return "person";
  if (raw.includes("motion")) return "motion";
  return "motion";
}


function FocusTimeline({ cameraId, onSelect }) {
  const { t } = useApp();
  // P5.b · Timeline dans LiveView façon Reolink :
  //   - fenêtre glissante (défaut 30 min) → scrub visuel + marqueurs par type
  //   - miniature générée à partir de `thumbnail` OU frame_thumb OU crop_thumb
  //   - icône par classe (person/car/truck/animal/plate/fire/…)
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  // v3.22 · "today" est un mode à part (pas une durée fixe) — demande
  // explicite : les 4 préréglages existants (15m/30m/1h/3h) sont tous des
  // fenêtres glissantes, aucun ne correspond à "les événements du jour".
  const [windowMode, setWindowMode] = useState(30); // minutes (nombre) ou "today"
  const [hoverEvent, setHoverEvent] = useState(null);

  const windowStartMs = (mode) => {
    if (mode === "today") {
      const d = new Date(); d.setHours(0, 0, 0, 0);
      return d.getTime();
    }
    return Date.now() - mode * 60 * 1000;
  };

  useEffect(() => {
    if (!cameraId) return;
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const startMs = windowStartMs(windowMode);
        const [ev, pl] = await Promise.all([
          api.get(`/events?camera_id=${cameraId}&limit=200`),
          api.get(`/plates?camera_id=${cameraId}&limit=100`),
        ]);
        const evArr = Array.isArray(ev.data) ? ev.data : (ev.data.items || []);
        const plArr = Array.isArray(pl.data) ? pl.data : (pl.data.items || []);
        // Fusionne events + plaques dans une seule timeline, filtré à la fenêtre
        const merged = [
          ...evArr.map((e) => ({ ...e, _kind: _kindFromEvent(e) })),
          ...plArr.map((p) => ({
            ...p, type: "plate_recognized", _kind: "plate",
            label: p.plate, thumbnail: p.plate_crop || p.vehicle_crop || p.frame_thumb,
          })),
        ].filter((x) => x.timestamp && new Date(x.timestamp).getTime() >= startMs)
         .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
        if (alive) setEvents(merged);
      } catch (e) { if (alive) setEvents([]); }
      finally { if (alive) setLoading(false); }
    };
    load();
    const iv = setInterval(load, 8000);
    return () => { alive = false; clearInterval(iv); };
  }, [cameraId, windowMode]);

  if (!cameraId) return null;

  const now = Date.now();
  const start = windowStartMs(windowMode);
  const posPct = (iso) => {
    const t = new Date(iso).getTime();
    return Math.max(0, Math.min(100, ((t - start) / (now - start)) * 100));
  };
  // Groupement des events par kind pour la répartition sur des rangées
  const kinds = Array.from(new Set(events.map((e) => e._kind)));
  const kindCounts = {};
  for (const e of events) kindCounts[e._kind] = (kindCounts[e._kind] || 0) + 1;

  // v3.1.4 · bottom-14 (au lieu de bottom-6) : CameraControlOverlay occupe déjà
  // bottom-2 sur ~32px (5 boutons projecteur/IR/sirène/TTS/reboot) — la
  // timeline chevauchait cette barre et rendait ses icônes injoignables.
  return (
    <div className="absolute bottom-14 inset-x-2 pointer-events-auto" data-testid="focus-timeline">
      <div className="bg-black/85 border border-white/10 px-2 py-2 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[9px] uppercase tracking-wider text-white/60 mono">
            Timeline — {events.length} événement(s) {loading && <span className="text-[#00E5FF]">…</span>}
          </span>
          <div className="flex items-center gap-1">
            {[15, 30, 60, 180].map((m) => (
              <button key={m} onClick={() => setWindowMode(m)}
                      data-testid={`focus-timeline-window-${m}`}
                      className={`text-[9px] mono px-1 py-0.5 border ${windowMode === m ? "border-[#00E5FF] text-[#00E5FF]" : "border-white/10 text-white/50"}`}>
                {m < 60 ? `${m}m` : `${m / 60}h`}
              </button>
            ))}
            <button onClick={() => setWindowMode("today")}
                    data-testid="focus-timeline-window-today"
                    className={`text-[9px] mono px-1 py-0.5 border ${windowMode === "today" ? "border-[#00E5FF] text-[#00E5FF]" : "border-white/10 text-white/50"}`}>
              Aujourd'hui
            </button>
          </div>
        </div>

        {/* Légende par kind + count */}
        {kinds.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {kinds.map((k) => {
              const m = EVENT_KIND_META[k] || { icon: Activity, label: k, color: "#888" };
              const Ic = m.icon;
              return (
                <span key={k} className="flex items-center gap-0.5 text-[9px] mono text-white/70"
                      style={{ color: m.color }}>
                  <Ic size={9} /> {m.label} <span className="text-white/40">×{kindCounts[k]}</span>
                </span>
              );
            })}
          </div>
        )}

        {events.length === 0 ? (
          <div className="text-[10px] text-white/40 py-1">{t("lv.no_event_window")}</div>
        ) : (
          <>
            {/* Scrub bar façon Reolink : icônes positionnées sur une frise temporelle */}
            <div className="relative h-6 bg-white/5" data-testid="focus-timeline-scrub">
              {events.map((ev, i) => {
                const m = EVENT_KIND_META[ev._kind] || { icon: Activity, label: ev._kind, color: "#888" };
                const Ic = m.icon;
                return (
                  <button
                    key={`sc-${ev.id || i}`}
                    onClick={() => onSelect?.(ev)}
                    onMouseEnter={() => setHoverEvent(ev)}
                    onMouseLeave={() => setHoverEvent(null)}
                    style={{ left: `${posPct(ev.timestamp)}%`, color: m.color }}
                    data-testid={`focus-timeline-marker-${ev._kind}`}
                    className="absolute top-0 -translate-x-1/2 h-full w-4 hover:scale-110 transition-transform flex items-center justify-center"
                    title={`${m.label} · ${new Date(ev.timestamp).toLocaleTimeString("fr-FR")}`}
                  >
                    <Ic size={11} strokeWidth={2.5} />
                  </button>
                );
              })}
              {/* Curseur "now" à droite */}
              <div className="absolute top-0 right-0 h-full w-px bg-[#00E5FF]" />
            </div>

            {/* Bande de miniatures façon Reolink — seuls les items avec thumb visible */}
            <div className="flex gap-1 overflow-x-auto" data-testid="focus-timeline-thumbs">
              {events.filter((ev) => ev.thumbnail || ev.crop_thumbnail).slice(-12).reverse().map((ev) => {
                const m = EVENT_KIND_META[ev._kind] || { icon: Activity, label: ev._kind, color: "#888" };
                const Ic = m.icon;
                const ts = ev.timestamp ? new Date(ev.timestamp) : null;
                const time = ts ? ts.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
                const thumb = ev.thumbnail || ev.crop_thumbnail;
                return (
                  <button key={`th-${ev.id}`} onClick={() => onSelect?.(ev)}
                          data-testid={`timeline-event-${ev.id}`}
                          className="relative flex-shrink-0 w-24 border border-white/10 hover:border-[#00E5FF] bg-black/60 text-left"
                          title={`${m.label} · ${ev.label || ev.type} · ${time}`}>
                    <img src={thumb} alt={m.label} className="w-full h-14 object-cover" />
                    <span className="absolute top-0.5 left-0.5 w-4 h-4 flex items-center justify-center rounded-full"
                          style={{ background: m.color + "cc" }}>
                      <Ic size={9} color="#fff" strokeWidth={2.5} />
                    </span>
                    <div className="px-1 py-0.5 bg-black/60">
                      <div className="text-[9px] mono text-white/90 truncate">{ev.label || ev.type}</div>
                      <div className="text-[8px] mono text-white/50">{time}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* Tooltip flottant */}
      {hoverEvent && (
        <div className="absolute -top-16 left-1/2 -translate-x-1/2 border border-white/20 bg-black/90 px-2 py-1 text-[10px] mono text-white pointer-events-none">
          {(EVENT_KIND_META[hoverEvent._kind] || {}).label} · {hoverEvent.label || hoverEvent.type}
          <div className="text-white/60">{new Date(hoverEvent.timestamp).toLocaleString("fr-FR")}</div>
        </div>
      )}
    </div>
  );
}

export default function LiveView() {
  const { t, can, aiDetections } = useApp();
  const [cams, setCams] = useState([]);
  const [layout, setLayout] = useState(4);
  const [hd, setHd] = useState(false);
  const [showOverlay, setShowOverlay] = useState(() => localStorage.getItem("mg_ai_overlay") !== "off");
  const [focusedId, setFocusedId] = useState(null);  // camera_id focalisée (single-view) — null = mosaïque
  const [showTimeline, setShowTimeline] = useState(true);
  const [previewEvent, setPreviewEvent] = useState(null);  // événement cliqué depuis la timeline
  // v3.22 · Retour utilisateur : le clic sur une miniature de la Timeline
  // "ne fait rien" — techniquement une image s'ouvrait déjà, mais pas la
  // vidéo de l'événement. Lecture directe ici (même mécanisme que
  // EventViewer.jsx::playAround), sans changer de page.
  const [previewVideo, setPreviewVideo] = useState(null); // {url, offset_sec}
  const [previewVideoLoading, setPreviewVideoLoading] = useState(false);
  const [previewVideoError, setPreviewVideoError] = useState("");
  useEffect(() => { setPreviewVideo(null); setPreviewVideoError(""); }, [previewEvent?.id]);
  const [previewMode] = useState("auto");  // legacy — plus utilisé (video-pipeline-v2 : pipeline par caméra)
  const canPtz = can("technician");
  const canEditLayout = can("technician");

  // v3.22 · Pagination + disposition personnalisée (demande explicite du
  // 02/09) : rester en vue 4 (ou 9, etc.) sans devoir passer en vue plus
  // grande juste pour voir d'autres caméras — flèches de part et d'autre
  // pour tourner par page, en boucle. Ordre des caméras personnalisable
  // par glisser-déposer et sauvegardé en base (survit à un upgrade.sh,
  // contrairement à un simple localStorage).
  const [page, setPage] = useState(0);
  const [savedOrder, setSavedOrder] = useState({}); // { [layoutSize]: [camera_id, ...] }
  const [editingLayout, setEditingLayout] = useState(false);
  const [dragFrom, setDragFrom] = useState(null);
  const [savingLayout, setSavingLayout] = useState(false);

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data));
    const iv = setInterval(() => api.get("/cameras").then((r) => setCams(r.data)).catch(() => { /* ignore */ }), 20000);
    return () => clearInterval(iv);
  }, []);
  useEffect(() => { localStorage.setItem("mg_ai_overlay", showOverlay ? "on" : "off"); }, [showOverlay]);
  useEffect(() => { setPage(0); setEditingLayout(false); }, [layout]);
  useEffect(() => {
    if (savedOrder[layout] !== undefined) return; // déjà chargé
    api.get(`/live/layout/${layout}`)
       .then((r) => setSavedOrder((prev) => ({ ...prev, [layout]: r.data.camera_ids || [] })))
       .catch(() => setSavedOrder((prev) => ({ ...prev, [layout]: [] })));
  }, [layout]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ordre effectif : caméras dans l'ordre sauvegardé pour cette taille de
  // grille, puis toute caméra nouvelle/non classée ajoutée à la suite
  // (dans l'ordre naturel de l'API) — jamais de caméra perdue.
  const orderedCams = useMemo(() => {
    const order = savedOrder[layout];
    if (!order || order.length === 0) return cams;
    const byId = new Map(cams.map((c) => [c.id, c]));
    const placed = new Set();
    const ordered = [];
    for (const id of order) {
      const c = byId.get(id);
      if (c) { ordered.push(c); placed.add(id); }
    }
    for (const c of cams) if (!placed.has(c.id)) ordered.push(c);
    return ordered;
  }, [cams, savedOrder, layout]);

  const pageCount = Math.max(1, Math.ceil(orderedCams.length / layout));
  const pageCamsRaw = orderedCams.slice(page * layout, page * layout + layout);

  const gotoPage = (delta) => setPage((p) => (p + delta + pageCount) % pageCount);

  const swapPositions = (fromLocalIdx, toLocalIdx) => {
    const fromGlobal = page * layout + fromLocalIdx;
    const toGlobal = page * layout + toLocalIdx;
    if (fromGlobal === toGlobal) return;
    const next = orderedCams.slice();
    [next[fromGlobal], next[toGlobal]] = [next[toGlobal], next[fromGlobal]];
    setSavedOrder((prev) => ({ ...prev, [layout]: next.map((c) => c.id) }));
  };

  const saveLayout = async () => {
    setSavingLayout(true);
    try {
      await api.put(`/live/layout/${layout}`, { camera_ids: orderedCams.map((c) => c.id) });
      toast.success("Disposition enregistrée — conservée après une mise à jour");
      setEditingLayout(false);
    } catch (e) { toast.error("Échec de l'enregistrement de la disposition"); }
    finally { setSavingLayout(false); }
  };

  const resetLayout = async () => {
    setSavingLayout(true);
    try {
      await api.put(`/live/layout/${layout}`, { camera_ids: [] });
      setSavedOrder((prev) => ({ ...prev, [layout]: [] }));
      toast.success("Disposition réinitialisée (ordre par défaut)");
    } catch (e) { toast.error("Échec"); }
    finally { setSavingLayout(false); }
  };

  // Liste des caméras naviguables (celles présentes dans la mosaïque, dans l'ordre affiché)
  const gridCams = useMemo(() => {
    if (!focusedId) return orderedCams;
    // Slice à la taille du layout courant (les slots vides ne comptent pas)
    return orderedCams.slice(0, Math.max(layout, orderedCams.length));
  }, [orderedCams, focusedId, layout]);
  const focusedIndex = focusedId ? gridCams.findIndex((c) => c?.id === focusedId) : -1;
  const gotoDelta = (delta) => {
    if (focusedIndex < 0 || !gridCams.length) return;
    const n = gridCams.length;
    let next = (focusedIndex + delta + n) % n;
    // Skip les slots null (cams undefined si le tableau contient moins d'entrées que le layout)
    let safety = n;
    while (!gridCams[next]?.id && safety > 0) { next = (next + delta + n) % n; safety--; }
    if (gridCams[next]?.id) setFocusedId(gridCams[next].id);
  };

  // Raccourcis clavier en mode focus : ESC (sortie), ← (précédent), → (suivant), T (toggle timeline).
  useEffect(() => {
    if (!focusedId) return;
    const onKey = (e) => {
      // Ignore si l'utilisateur est en train de taper dans un champ
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (e.key === "Escape") { setFocusedId(null); setPreviewEvent(null); }
      else if (e.key === "ArrowRight") { e.preventDefault(); gotoDelta(+1); }
      else if (e.key === "ArrowLeft")  { e.preventDefault(); gotoDelta(-1); }
      else if (e.key.toLowerCase() === "t") { setShowTimeline((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, focusedIndex, gridCams.length]);

  const goFull = () => { const el = document.getElementById("live-grid"); if (el?.requestFullscreen) el.requestFullscreen(); };
  const focusedCam = focusedId ? cams.find((c) => c.id === focusedId) : null;
  const toggleFocus = (id) => { if (!id) return; setFocusedId((cur) => cur === id ? null : id); setPreviewEvent(null); };

  // Grille rectangulaire (16:9 par tuile) — pas d'étirement/rognage.
  const cols = focusedCam ? 1 : Math.ceil(Math.sqrt(layout));
  const gridStyle = focusedCam
    ? { display: "grid", gridTemplateColumns: "1fr", gap: 2 }
    : { display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 2 };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("live.title")}</h1>
        <div className="flex items-center gap-2">
          {focusedCam && (
            <>
              <button onClick={() => gotoDelta(-1)} data-testid="focus-prev" title={t("lv.prev_camera")}
                      className="p-1.5 border border-border hover:bg-secondary">
                <ChevronLeft size={14} />
              </button>
              <span className="text-[10px] mono text-muted-foreground px-1">
                {focusedIndex + 1}/{gridCams.filter((c) => c?.id).length}
              </span>
              <button onClick={() => gotoDelta(+1)} data-testid="focus-next" title={t("lv.next_camera")}
                      className="p-1.5 border border-border hover:bg-secondary">
                <ChevronRight size={14} />
              </button>
              <button onClick={() => setShowTimeline((v) => !v)} data-testid="focus-timeline-toggle"
                      title={t("lv.toggle_timeline")}
                      className={`px-2.5 py-1.5 text-xs border flex items-center gap-1 ${showTimeline ? "bg-[#00E5FF]/20 border-[#00E5FF] text-[#00E5FF]" : "border-border hover:bg-secondary"}`}>
                Timeline
              </button>
              <button onClick={() => { setFocusedId(null); setPreviewEvent(null); }} data-testid="exit-focus"
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF] hover:text-black">
                <X size={13} /> Fermer le focus
              </button>
            </>
          )}
          <button onClick={() => setShowOverlay((v) => !v)} data-testid="toggle-ai-overlay"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs border ${showOverlay ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}
            title={t("lv.toggle_ai")}>
            {showOverlay ? <Eye size={13} /> : <EyeOff size={13} />} Overlay IA
          </button>
          <button onClick={() => setHd(!hd)} data-testid="hd-toggle" className={`px-2.5 py-1.5 text-xs border ${hd ? "bg-[#00E676] text-black border-[#00E676]" : "border-border"} hover:opacity-80`}>{hd ? "HD" : "SD"}</button>
          {!focusedCam && LAYOUTS.map((n) => (
            <button key={n} onClick={() => setLayout(n)} data-testid={`layout-${n}`}
              className={`px-2.5 py-1.5 text-xs mono ${layout === n ? "bg-[#0044FF] text-white" : "border border-border hover:bg-secondary"}`}>{n}</button>
          ))}
          {!focusedCam && pageCount > 1 && (
            <span className="text-[10px] mono text-muted-foreground px-1" data-testid="live-page-indicator">
              page {page + 1}/{pageCount}
            </span>
          )}
          {!focusedCam && canEditLayout && (
            editingLayout ? (
              <>
                <button onClick={saveLayout} disabled={savingLayout} data-testid="live-layout-save"
                        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10">
                  <Save size={13} /> Enregistrer la disposition
                </button>
                <button onClick={resetLayout} disabled={savingLayout} data-testid="live-layout-reset"
                        className="p-1.5 border border-border hover:bg-secondary" title="Réinitialiser (ordre par défaut)">
                  <RotateCcw size={13} />
                </button>
                <button onClick={() => setEditingLayout(false)} data-testid="live-layout-cancel"
                        className="p-1.5 border border-border hover:bg-secondary" title="Annuler">
                  <X size={13} />
                </button>
              </>
            ) : (
              <button onClick={() => setEditingLayout(true)} data-testid="live-layout-edit"
                      title="Glisser-déposer les tuiles pour choisir quelles caméras apparaissent ici"
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border hover:bg-secondary">
                <LayoutGrid size={13} /> Organiser
              </button>
            )
          )}
          <button onClick={goFull} data-testid="fullscreen-btn" className="px-2.5 py-1.5 text-xs border border-border hover:bg-secondary flex items-center gap-1"><Maximize2 size={13} /> {t("live.fullscreen")}</button>
        </div>
      </div>

      <div id="live-grid" className="bg-background relative" style={gridStyle}>
        {focusedCam ? (
          <>
            <Feed cam={focusedCam} idx={0} canPtz={canPtz} hd={hd} showOverlay={showOverlay}
                  aiState={aiDetections[focusedCam.id]} focused={true} onToggleFocus={toggleFocus} />
            {showTimeline && <FocusTimeline cameraId={focusedCam.id} onSelect={setPreviewEvent} />}
          </>
        ) : (
          Array.from({ length: layout }).map((_, i) => {
            const cam = pageCamsRaw[i];
            const tile = (
              <Feed key={cam?.id || `slot-${i}`} cam={cam} idx={i} canPtz={canPtz} hd={hd}
                    showOverlay={showOverlay} focused={false}
                    aiState={cam ? aiDetections[cam.id] : null}
                    onToggleFocus={editingLayout ? undefined : toggleFocus} />
            );
            if (!editingLayout) return tile;
            return (
              <div key={cam?.id || `slot-${i}`}
                   draggable={!!cam}
                   onDragStart={() => setDragFrom(i)}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={() => { if (dragFrom !== null) { swapPositions(dragFrom, i); setDragFrom(null); } }}
                   className="relative outline outline-2 outline-dashed outline-[#0044FF]/50 cursor-grab active:cursor-grabbing"
                   data-testid={`live-drag-slot-${i}`}>
                <div className="absolute top-1 left-1 z-10 bg-[#0044FF] text-white p-1 pointer-events-none">
                  <GripVertical size={12} />
                </div>
                {tile}
              </div>
            );
          })
        )}
        {!focusedCam && pageCount > 1 && (
          <>
            <button onClick={() => gotoPage(-1)} data-testid="live-page-prev" title="Page précédente"
                    className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 z-20 p-2 bg-black/60 text-white border border-white/20 hover:bg-black/80">
              <ChevronLeft size={18} />
            </button>
            <button onClick={() => gotoPage(+1)} data-testid="live-page-next" title="Page suivante"
                    className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 z-20 p-2 bg-black/60 text-white border border-white/20 hover:bg-black/80">
              <ChevronRight size={18} />
            </button>
          </>
        )}
      </div>

      {previewEvent && (
        <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-8"
             onClick={() => { setPreviewEvent(null); setPreviewVideo(null); setPreviewVideoError(""); }}
             data-testid="event-preview-modal">
          <div className="max-w-5xl w-full" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-white font-head font-semibold text-lg">{previewEvent.type || previewEvent.label || "Événement"}</div>
                <div className="text-white/60 text-xs mono">
                  {previewEvent.timestamp ? new Date(previewEvent.timestamp).toLocaleString("fr-FR") : ""}
                  {previewEvent.camera_name ? ` · ${previewEvent.camera_name}` : ""}
                  {previewEvent.confidence ? ` · ${(previewEvent.confidence * 100).toFixed(0)}%` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {!previewVideo && (
                  <button
                    onClick={async () => {
                      if (!previewEvent.id) { setPreviewVideoError("Événement sans identifiant — vidéo indisponible"); return; }
                      setPreviewVideoLoading(true); setPreviewVideoError("");
                      try {
                        const { data } = await api.get(`/events/${previewEvent.id}/recording`);
                        const token = localStorage.getItem("mg_token");
                        const envBase = process.env.REACT_APP_BACKEND_URL || "";
                        setPreviewVideo({
                          url: `${envBase}/api${data.stream_url}?token=${encodeURIComponent(token || "")}&t=${Math.max(0, data.offset_sec || 0)}`,
                          offset_sec: Math.max(0, data.offset_sec || 0),
                        });
                      } catch (e) {
                        setPreviewVideoError(e.response?.status === 404 ? "Aucun enregistrement ne couvre cet événement" : "Échec de la lecture vidéo");
                      } finally { setPreviewVideoLoading(false); }
                    }}
                    disabled={previewVideoLoading} data-testid="event-preview-play-video"
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF]/10">
                    {previewVideoLoading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                    Lire la vidéo
                  </button>
                )}
                <button onClick={() => { setPreviewEvent(null); setPreviewVideo(null); setPreviewVideoError(""); }}
                        className="p-2 hover:bg-white/10 text-white" data-testid="event-preview-close">
                  <X size={18} />
                </button>
              </div>
            </div>
            {previewVideoError && <div className="text-[#FF6666] text-xs mb-2">{previewVideoError}</div>}
            {previewVideo ? (
              <video src={previewVideo.url} controls autoPlay className="w-full max-h-[80vh] bg-black" data-testid="event-preview-video"
                     onLoadedMetadata={(e) => { e.currentTarget.currentTime = previewVideo.offset_sec; e.currentTarget.play().catch(() => {}); }} />
            ) : previewEvent.thumbnail && (
              <img src={previewEvent.thumbnail} alt={previewEvent.type} className="w-full max-h-[80vh] object-contain bg-black" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
