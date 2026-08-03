import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import {
  X, ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw,
  Download, Copy, PlayCircle, Camera as CamIcon, MapPin, Clock, Puzzle, ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Visionneuse événements/plaques réutilisable.
 *
 * Props:
 *   - items: [{id, thumbnail (base64 or url), type/label, camera_name, camera_id,
 *             timestamp, confidence, plate?, list_status?, vehicle_color?, plugin?,
 *             track_id?, motion_pct?, vehicle_make?, vehicle_model?, vehicle_type?}]
 *   - index: index actif
 *   - onClose(): fermeture
 *   - onIndex(next): navigation
 *   - kind: "event" | "plate"  → pour titrage/actions
 */
export default function EventViewer({ items, index, onClose, onIndex, kind = "event" }) {
  const item = items[index];
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(null);
  const [recInfo, setRecInfo] = useState(null); // { stream_url, offset_sec }
  const [showVideo, setShowVideo] = useState(false);
  const [recLoading, setRecLoading] = useState(false);
  const imgRef = useRef(null);
  const containerRef = useRef(null);
  const videoRef = useRef(null);

  // Reset zoom on item change / close
  useEffect(() => { setScale(1); setPan({ x: 0, y: 0 }); setRecInfo(null); setShowVideo(false); }, [index]);

  // Escape + arrows
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { showVideo ? setShowVideo(false) : onClose(); }
      if (!showVideo) {
        if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
        if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onIndex, onClose, showVideo]);

  const zoomAt = useCallback((delta, cx, cy) => {
    setScale((s) => {
      const next = Math.max(1, Math.min(6, s + delta));
      // Zoom autour du point survolé
      if (containerRef.current && next !== s) {
        const rect = containerRef.current.getBoundingClientRect();
        const dx = (cx ?? rect.width / 2) - rect.width / 2 - pan.x;
        const dy = (cy ?? rect.height / 2) - rect.height / 2 - pan.y;
        const factor = next / s;
        setPan((p) => ({ x: p.x - dx * (factor - 1), y: p.y - dy * (factor - 1) }));
      }
      if (next === 1) setPan({ x: 0, y: 0 });
      return next;
    });
  }, [pan]);

  const onWheel = (e) => {
    e.preventDefault();
    zoomAt(e.deltaY < 0 ? 0.3 : -0.3, e.nativeEvent.offsetX, e.nativeEvent.offsetY);
  };
  const onMouseDown = (e) => { if (scale > 1) setDragging({ x: e.clientX - pan.x, y: e.clientY - pan.y }); };
  const onMouseMove = (e) => { if (dragging) setPan({ x: e.clientX - dragging.x, y: e.clientY - dragging.y }); };
  const onMouseUp = () => setDragging(null);

  const download = () => {
    if (!item?.thumbnail) return;
    const a = document.createElement("a");
    a.href = item.thumbnail;
    a.download = `${kind}-${item.id || Date.now()}.jpg`;
    a.click();
    toast.success("Image téléchargée");
  };
  const copyImg = async () => {
    if (!item?.thumbnail || !navigator.clipboard || !window.ClipboardItem) return toast.error("Copie non supportée par ce navigateur");
    try {
      const b = await (await fetch(item.thumbnail)).blob();
      await navigator.clipboard.write([new ClipboardItem({ [b.type]: b })]);
      toast.success("Image copiée dans le presse-papier");
    } catch { toast.error("Copie impossible"); }
  };
  const playAround = async () => {
    if (!item) return;
    setRecLoading(true);
    try {
      let data;
      if (item.id) {
        ({ data } = await api.get(`/events/${item.id}/recording`));
      } else if (item.camera_id && item.timestamp) {
        ({ data } = await api.get("/recording-context", { params: { camera_id: item.camera_id, at: item.timestamp } }));
      } else {
        throw new Error("Item sans identifiant");
      }
      const token = localStorage.getItem("mg_token");
      const url = `${process.env.REACT_APP_BACKEND_URL}/api${data.stream_url}?token=${encodeURIComponent(token || "")}`;
      setRecInfo({ ...data, url });
      setShowVideo(true);
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.currentTime = Math.max(0, data.offset_sec || 0);
          videoRef.current.play().catch(() => {});
        }
      }, 200);
    } catch (e) {
      const msg = e.response?.status === 404 ? "Aucun enregistrement ne couvre cet événement" : "Erreur";
      toast.error(msg);
    } finally { setRecLoading(false); }
  };

  const meta = useMemo(() => {
    if (!item) return [];
    // Traçabilité moteurs (P8+ CEO Feb 2026) : afficher les moteurs utilisés
    // (ANPR + détecteurs + trackers + segmenters). Les événements pipeline
    // exposent `detectors`, `trackers`, `segmenters` (listes) ; les plaques
    // exposent `engine` (moteur ANPR).
    const engineParts = [];
    if (kind === "plate" || item.plate) {
      engineParts.push(`ANPR: ${item.engine || "fast-alpr"}`);
    }
    if (item.detectors?.length) engineParts.push(`Détection: ${item.detectors.join(", ")}`);
    if (item.trackers?.length)  engineParts.push(`Tracking: ${item.trackers.join(", ")}`);
    if (item.segmenters?.length) engineParts.push(`Segmentation: ${item.segmenters.join(", ")}`);
    const pluginValue = engineParts.length
      ? engineParts.join(" · ")
      : (item.plugin || (kind === "plate" ? "ANPR (fast-alpr)" : item._bbox ? "YOLO" : "Détection"));
    return [
      { icon: CamIcon,     label: "Caméra",     value: item.camera_name || "—" },
      { icon: MapPin,      label: "Site",       value: item.site_name || "—" },
      { icon: Clock,       label: "Horodatage", value: new Date(item.timestamp).toLocaleString("fr-FR") },
      { icon: Puzzle,      label: "Moteurs",    value: pluginValue,
        testid: "viewer-engines" },
      { icon: ShieldAlert, label: "Type",       value: item.type || item.label || (item.plate ? "Plaque" : "—") },
    ];
  }, [item, kind]);

  if (!item) return null;

  return (
    <div className="fixed inset-0 z-[110] bg-black/90 flex" data-testid="event-viewer">
      {/* Bouton close */}
      <button onClick={onClose} className="absolute top-3 right-3 z-10 p-2 bg-black/60 hover:bg-black text-white" data-testid="viewer-close-btn"><X size={18} /></button>

      {/* Navigation */}
      {index > 0 && (
        <button onClick={() => onIndex(index - 1)} className="absolute left-3 top-1/2 -translate-y-1/2 z-10 p-3 bg-black/60 hover:bg-black text-white" data-testid="viewer-prev-btn"><ChevronLeft size={22} /></button>
      )}
      {index < items.length - 1 && (
        <button onClick={() => onIndex(index + 1)} className="absolute right-3 top-1/2 -translate-y-1/2 z-10 p-3 bg-black/60 hover:bg-black text-white" data-testid="viewer-next-btn"><ChevronRight size={22} /></button>
      )}

      {/* Zone image / vidéo */}
      <div ref={containerRef} className="flex-1 relative overflow-hidden select-none"
           onWheel={onWheel} onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}
           style={{ cursor: scale > 1 ? (dragging ? "grabbing" : "grab") : "default" }}>
        {showVideo && recInfo ? (
          <video ref={videoRef} src={recInfo.url} controls autoPlay className="w-full h-full bg-black" data-testid="viewer-video" />
        ) : item.thumbnail ? (
          <>
            <img ref={imgRef} src={item.thumbnail} alt=""
                 className="absolute top-1/2 left-1/2 select-none pointer-events-none max-w-none"
                 style={{ transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transition: dragging ? "none" : "transform .15s ease-out", maxHeight: "100%" }}
                 data-testid="viewer-image" />
            {/* Hybridation ANPR : la scène HD reste le visuel principal ; les crops
                nets (plaque + véhicule) sont épinglés en overlay bas-droit pour
                garantir la lisibilité OCR même quand la plaque est petite dans la scène. */}
            {(item.plate_crop || item.vehicle_crop) && (
              <div className="absolute bottom-16 right-3 flex flex-col gap-1.5 z-10" data-testid="viewer-crops">
                {item.vehicle_crop && (
                  <div className="bg-black/80 border border-white/20 p-1">
                    <div className="text-[8px] uppercase tracking-wider text-white/50 mb-0.5 mono">Véhicule</div>
                    <img src={item.vehicle_crop} alt="véhicule" className="max-w-[180px] max-h-[110px] object-contain block" data-testid="viewer-vehicle-crop" />
                  </div>
                )}
                {item.plate_crop && (
                  <div className="bg-black/80 border border-[#00E5FF] p-1">
                    <div className="text-[8px] uppercase tracking-wider text-[#00E5FF] mb-0.5 mono">Plaque OCR</div>
                    <img src={item.plate_crop} alt="plaque" className="max-w-[180px] max-h-[70px] object-contain block bg-black" data-testid="viewer-plate-crop" />
                    {item.plate && (
                      <div className="text-center text-[13px] mono font-bold text-white mt-0.5 tracking-widest">{item.plate}</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-white/40">Aucune image disponible</div>
        )}
        {/* Barre outils zoom */}
        {!showVideo && item.thumbnail && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-black/70 p-1" data-testid="viewer-tools">
            <button onClick={() => zoomAt(-0.3)} className="p-2 text-white hover:bg-white/10" title="Zoom -"><ZoomOut size={16} /></button>
            <span className="text-white text-xs mono w-12 text-center">{Math.round(scale * 100)}%</span>
            <button onClick={() => zoomAt(0.3)} className="p-2 text-white hover:bg-white/10" title="Zoom +"><ZoomIn size={16} /></button>
            <button onClick={() => { setScale(1); setPan({ x: 0, y: 0 }); }} className="p-2 text-white hover:bg-white/10" title="Réinitialiser"><RotateCcw size={16} /></button>
            <div className="w-px h-5 bg-white/20 mx-1" />
            <button onClick={download} className="p-2 text-white hover:bg-white/10" title="Télécharger" data-testid="viewer-download-btn"><Download size={16} /></button>
            <button onClick={copyImg} className="p-2 text-white hover:bg-white/10" title="Copier l'image" data-testid="viewer-copy-btn"><Copy size={16} /></button>
          </div>
        )}
      </div>

      {/* Panneau latéral */}
      <aside className="w-80 bg-[#0a0a0a] border-l border-white/10 text-white overflow-y-auto" data-testid="viewer-panel">
        <div className="p-4 border-b border-white/10">
          <div className="text-[10px] uppercase tracking-wider text-white/50 mb-1">{kind === "plate" ? "Plaque" : "Événement"}</div>
          <div className="text-lg font-head font-bold" data-testid="viewer-title">
            {item.plate ? item.plate : (item.type || item.label || "Détection")}
          </div>
          {item.confidence != null && (
            <div className="text-[11px] mono mt-1 text-[#00E676]">Confiance {(item.confidence * 100).toFixed(0)}%</div>
          )}
          {item.list_status && item.list_status !== "none" && (
            <span className="inline-block mt-2 text-[10px] uppercase tracking-wider px-1.5 py-0.5 border" style={{ borderColor: item.list_status === "black" ? "#FF3333" : "#00E676", color: item.list_status === "black" ? "#FF3333" : "#00E676" }}>
              {item.list_status === "black" ? "Liste noire" : "Liste blanche"}
            </span>
          )}
        </div>

        <div className="p-4 space-y-2">
          {meta.map((m, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <m.icon size={13} className="text-white/40 mt-0.5 shrink-0" />
              <div>
                <div className="text-[10px] uppercase tracking-wider text-white/40">{m.label}</div>
                <div className="mono">{m.value}</div>
              </div>
            </div>
          ))}
          {item.track_id && (
            <div className="flex items-start gap-2 text-xs">
              <ShieldAlert size={13} className="text-white/40 mt-0.5 shrink-0" />
              <div><div className="text-[10px] uppercase tracking-wider text-white/40">ByteTrack ID</div><div className="mono">#{item.track_id}</div></div>
            </div>
          )}
          {item.vehicle_color && (
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">Couleur véhicule</span><span className="mono">{item.vehicle_color}</span></div>
          )}
          {item.vehicle_make && (
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">Véhicule</span><span className="mono">{item.vehicle_make} {item.vehicle_model} ({item.vehicle_type})</span></div>
          )}
          {item.motion_pct != null && (
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">Mouvement</span><span className="mono">{item.motion_pct}%</span></div>
          )}
        </div>

        <div className="p-4 border-t border-white/10 space-y-2">
          <button onClick={playAround} disabled={recLoading || showVideo} data-testid="viewer-play-video-btn"
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[#0044FF] text-white hover:bg-[#0033cc] disabled:opacity-50">
            <PlayCircle size={16} /> {showVideo ? "Vidéo en cours" : "Lire la vidéo autour de cet événement"}
          </button>
          {showVideo && (
            <button onClick={() => setShowVideo(false)} className="w-full text-xs text-white/60 hover:text-white">← Retour à l&apos;image</button>
          )}
          <div className="text-[10px] text-white/40 text-center mono">
            {index + 1} / {items.length} · ← / → navigation · Échap fermer
          </div>
        </div>
      </aside>
    </div>
  );
}
