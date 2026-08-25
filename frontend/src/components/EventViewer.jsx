import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import {
  X, ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw,
  Download, Copy, PlayCircle, Camera as CamIcon, MapPin, Clock, Puzzle, ShieldAlert,
  ScanSearch, Loader2, History, GanttChartSquare, ThumbsUp, ThumbsDown, Pencil, Check,
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
 *   - onPlateUpdated(plateId, newPlate): appelé après correction manuelle
 *     du numéro d'une plaque (kind="plate") — laisse le parent rafraîchir
 *     sa liste sans recharger toute la page.
 */
export default function EventViewer({ items, index, onClose, onIndex, onOpenPlate, onPlateUpdated, kind = "event" }) {
  const { t } = useApp();
  const item = items[index];
  const navigate = useNavigate();
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(null);
  const [recInfo, setRecInfo] = useState(null); // { stream_url, offset_sec }
  const [showVideo, setShowVideo] = useState(false);
  const [recLoading, setRecLoading] = useState(false);
  // v1.0-rc3/v3.1.8 · "Analyser OCR" = sélection manuelle d'une zone (voir
  // plus bas) — plus d'analyse automatique pleine image en aveugle, qui
  // produisait des faux positifs silencieux avec les moteurs OCR sans
  // localisation de plaque dédiée.
  const [ocrResult, setOcrResult] = useState(null);
  // v3.6 · Correction manuelle du numéro de plaque (erreur OCR) — édition
  // en place du champ `plate` de la ligne db.plates courante (kind="plate").
  const [plateOverride, setPlateOverride] = useState(null);
  const [editingPlate, setEditingPlate] = useState(false);
  const [plateDraft, setPlateDraft] = useState("");
  const [savingPlate, setSavingPlate] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selectRect, setSelectRect] = useState(null); // {x, y, w, h} en px, relatif au container
  const [selectStart, setSelectStart] = useState(null);
  const [zoneLoading, setZoneLoading] = useState(false);
  // Boucle de feedback vrai/faux positif — events "retail.*" (plan anti-vol Phase 1)
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(item?.feedback || null);
  const imgRef = useRef(null);
  const containerRef = useRef(null);
  const videoRef = useRef(null);

  // Reset zoom/vidéo/OCR quand l'ITEM AFFICHÉ change (identité, pas position).
  // v3.1.8 · Dépendait de `index` (un simple numéro) — mais le parent (Events/
  // Alerts/Dashboard) peut recevoir un nouvel événement en temps réel (poll ou
  // websocket) et PRÉPENDRE/reconstruire son tableau `items` pendant que la
  // visionneuse est ouverte : `index` ne bouge pas, mais `items[index]` pointe
  // alors soudain sur un événement différent (celui qui a glissé à cette
  // position) — l'effet ne se redéclenchait donc jamais, laissant la vidéo/le
  // zoom/l'OCR de l'ANCIEN item affichés à côté des métadonnées du NOUVEAU.
  // Dépendre de `item?.id` (l'identité réelle affichée) au lieu de `index`
  // corrige ce désync, quel que soit le comportement du parent.
  useEffect(() => { setScale(1); setPan({ x: 0, y: 0 }); setRecInfo(null); setShowVideo(false); setOcrResult(null); setFeedbackSent(item?.feedback || null); setSelectMode(false); setSelectRect(null); setSelectStart(null); setPlateOverride(null); setEditingPlate(false); }, [item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sécurité : dès qu'une plaque est trouvée (par n'importe quel chemin), on
  // sort du mode sélection pour fermer proprement l'overlay de dessin.
  useEffect(() => { if (ocrResult?.plate) { setSelectMode(false); setSelectRect(null); setSelectStart(null); } }, [ocrResult]);

  // Escape + arrows
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        if (selectMode) { setSelectMode(false); setSelectRect(null); setSelectStart(null); }
        else if (showVideo) { setShowVideo(false); }
        else { onClose(); }
      }
      if (!showVideo && !selectMode) {
        if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
        if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onIndex, onClose, showVideo, selectMode]);

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
    if (selectMode) return;
    e.preventDefault();
    zoomAt(e.deltaY < 0 ? 0.3 : -0.3, e.nativeEvent.offsetX, e.nativeEvent.offsetY);
  };
  const onMouseDown = (e) => {
    if (selectMode) {
      const rect = containerRef.current.getBoundingClientRect();
      setSelectStart({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      setSelectRect(null);
      return;
    }
    if (scale > 1) setDragging({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };
  const onMouseMove = (e) => {
    if (selectMode && selectStart) {
      const rect = containerRef.current.getBoundingClientRect();
      const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      setSelectRect({
        x: Math.min(cx, selectStart.x), y: Math.min(cy, selectStart.y),
        w: Math.abs(cx - selectStart.x), h: Math.abs(cy - selectStart.y),
      });
      return;
    }
    if (dragging) setPan({ x: e.clientX - dragging.x, y: e.clientY - dragging.y });
  };
  const onMouseUp = () => {
    if (selectMode) { setSelectStart(null); return; }
    setDragging(null);
  };

  const runZoneAnalysis = async () => {
    if (!item?.id || !selectRect || !imgRef.current) return;
    const MIN_PX = 8;
    if (selectRect.w < MIN_PX || selectRect.h < MIN_PX) {
      toast.error("Zone trop petite — dessinez un rectangle autour de la plaque");
      return;
    }
    const imgRect = imgRef.current.getBoundingClientRect();
    const containerRect = containerRef.current.getBoundingClientRect();
    // Coordonnées de la sélection (relatives au container) → relatives à l'image affichée
    const selLeft = containerRect.left + selectRect.x;
    const selTop = containerRect.top + selectRect.y;
    const nx1 = (selLeft - imgRect.left) / imgRect.width;
    const ny1 = (selTop - imgRect.top) / imgRect.height;
    const nx2 = (selLeft + selectRect.w - imgRect.left) / imgRect.width;
    const ny2 = (selTop + selectRect.h - imgRect.top) / imgRect.height;
    const clamp = (v) => Math.max(0, Math.min(1, v));
    const bbox = [clamp(nx1), clamp(ny1), clamp(nx2), clamp(ny2)];
    if (bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) {
      toast.error("Zone hors de l'image — recommencez la sélection");
      return;
    }
    setZoneLoading(true);
    try {
      const { data } = await api.post(`/events/${item.id}/reanalyze`, { bbox });
      setOcrResult(data);
      if (data.plate) {
        toast.success(`Plaque détectée : ${data.plate} (${Math.round((data.confidence || 0) * 100)}%)${data.engine ? ` · ${data.engine}` : ""}`);
        setSelectMode(false);
        setSelectRect(null);
      } else {
        toast.info(data.message || "Aucune plaque détectée dans cette zone");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Analyse impossible");
    } finally { setZoneLoading(false); }
  };

  const savePlateEdit = async () => {
    const value = plateDraft.trim().toUpperCase();
    if (!value) { toast.error("Numéro de plaque requis"); return; }
    setSavingPlate(true);
    try {
      const { data } = await api.put(`/plates/${item.id}`, { plate: value });
      setPlateOverride(data.plate);
      setEditingPlate(false);
      toast.success(`Plaque corrigée : ${data.plate}`);
      onPlateUpdated?.(item.id, data.plate);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Correction impossible");
    } finally { setSavingPlate(false); }
  };

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
      const offset = Math.max(0, data.offset_sec || 0);
      // v3.1.1 · `t` en query : le seek côté serveur (ffmpeg -ss) est le seul
      // qui fonctionne quand la vidéo source est HEVC (transcodée à la volée,
      // pas de support HTTP Range sur un flux live) — video.currentTime plus
      // bas reste utile pour le cas H264 (FileResponse, Range natif).
      const url = `${process.env.REACT_APP_BACKEND_URL}/api${data.stream_url}?token=${encodeURIComponent(token || "")}&t=${offset}`;
      setRecInfo({ ...data, url });
      setShowVideo(true);
      // v3.1.9 · Le seek partait avant que le <video> ait chargé ses
      // métadonnées (délai fixe de 200ms) — sur un fichier de quelques Mo,
      // souvent pas encore prêt à ce moment-là, donc `currentTime` était
      // silencieusement ignoré et la lecture repartait de 0 au lieu de
      // l'instant de l'événement. Le seek se fait maintenant dans
      // `onLoadedMetadata` (voir l'élément <video>), déclenché quand le
      // navigateur a réellement les métadonnées, jamais avant.
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
    // v0.5.1.c · Priorité au champ `plugins_used` unifié (backend downstream).
    const engineParts = [];
    if (item.plugins_used?.length) {
      engineParts.push(item.plugins_used.join(", "));
    } else {
      if (kind === "plate" || item.plate) {
        engineParts.push(`ANPR: ${item.engine || "fast-alpr"}`);
      }
      if (item.detectors?.length) engineParts.push(`Détection: ${item.detectors.join(", ")}`);
      if (item.trackers?.length)  engineParts.push(`Tracking: ${item.trackers.join(", ")}`);
      if (item.segmenters?.length) engineParts.push(`Segmentation: ${item.segmenters.join(", ")}`);
    }
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
           style={{ cursor: selectMode ? "crosshair" : (scale > 1 ? (dragging ? "grabbing" : "grab") : "default") }}>
        {showVideo && recInfo ? (
          <video ref={videoRef} src={recInfo.url} controls autoPlay className="w-full h-full bg-black" data-testid="viewer-video"
                 onLoadedMetadata={(e) => {
                   e.currentTarget.currentTime = Math.max(0, recInfo.offset_sec || 0);
                   e.currentTarget.play().catch(() => {});
                 }} />
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
                    <div className="text-[8px] uppercase tracking-wider text-white/50 mb-0.5 mono">{t("ev.vehicle")}</div>
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
        {/* v3.1.7 · Overlay de sélection manuelle de zone (OCR) */}
        {selectMode && (
          <>
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 bg-black/80 text-white text-xs px-3 py-1.5 flex items-center gap-2" data-testid="viewer-select-hint">
              <ScanSearch size={14} /> Dessinez un rectangle autour de la plaque
            </div>
            {selectRect && (
              <div
                className="absolute border-2 border-[#00E5FF] bg-[#00E5FF]/10 z-20 pointer-events-none"
                style={{ left: selectRect.x, top: selectRect.y, width: selectRect.w, height: selectRect.h }}
                data-testid="viewer-select-rect"
              />
            )}
            {selectRect && !selectStart && (
              <div className="absolute z-20 flex items-center gap-1.5 bg-black/85 p-1"
                   style={{ left: selectRect.x, top: selectRect.y + selectRect.h + 6 }}
                   onMouseDown={(e) => e.stopPropagation()} onMouseUp={(e) => e.stopPropagation()}>
                <button onClick={runZoneAnalysis} disabled={zoneLoading}
                        data-testid="viewer-analyze-zone-btn"
                        className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#7C3AED] text-white hover:bg-[#6D28D9] disabled:opacity-50 text-xs">
                  {zoneLoading ? <Loader2 size={14} className="animate-spin" /> : <ScanSearch size={14} />}
                  {zoneLoading ? "Analyse…" : "Analyser cette zone"}
                </button>
                <button onClick={() => setSelectRect(null)} disabled={zoneLoading}
                        className="px-2.5 py-1.5 border border-white/30 text-white/80 hover:bg-white/10 text-xs">
                  Effacer
                </button>
              </div>
            )}
          </>
        )}
        {/* Barre outils zoom */}
        {!showVideo && item.thumbnail && !selectMode && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-black/70 p-1" data-testid="viewer-tools">
            <button onClick={() => zoomAt(-0.3)} className="p-2 text-white hover:bg-white/10" title="Zoom -"><ZoomOut size={16} /></button>
            <span className="text-white text-xs mono w-12 text-center">{Math.round(scale * 100)}%</span>
            <button onClick={() => zoomAt(0.3)} className="p-2 text-white hover:bg-white/10" title="Zoom +"><ZoomIn size={16} /></button>
            <button onClick={() => { setScale(1); setPan({ x: 0, y: 0 }); }} className="p-2 text-white hover:bg-white/10" title={t("ev.reset")}><RotateCcw size={16} /></button>
            <div className="w-px h-5 bg-white/20 mx-1" />
            <button onClick={download} className="p-2 text-white hover:bg-white/10" title={t("ev.download")} data-testid="viewer-download-btn"><Download size={16} /></button>
            <button onClick={copyImg} className="p-2 text-white hover:bg-white/10" title="Copier l'image" data-testid="viewer-copy-btn"><Copy size={16} /></button>
          </div>
        )}
      </div>

      {/* Panneau latéral */}
      <aside className="w-80 bg-[#0a0a0a] border-l border-white/10 text-white overflow-y-auto" data-testid="viewer-panel">
        <div className="p-4 border-b border-white/10">
          <div className="text-[10px] uppercase tracking-wider text-white/50 mb-1">{kind === "plate" ? "Plaque" : "Événement"}</div>
          {kind === "plate" && item.id && editingPlate ? (
            <div className="flex items-center gap-1.5" data-testid="viewer-plate-edit">
              <input
                autoFocus
                value={plateDraft}
                onChange={(e) => setPlateDraft(e.target.value.toUpperCase())}
                onKeyDown={(e) => { if (e.key === "Enter") savePlateEdit(); if (e.key === "Escape") setEditingPlate(false); }}
                className="flex-1 min-w-0 px-2 py-1 bg-black border border-[#00E676] text-lg font-head font-bold mono uppercase tracking-widest outline-none"
                data-testid="viewer-plate-edit-input"
              />
              <button onClick={savePlateEdit} disabled={savingPlate} data-testid="viewer-plate-edit-save"
                      className="p-1.5 bg-[#00E676] text-black hover:bg-[#00c766] disabled:opacity-50 shrink-0">
                {savingPlate ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              </button>
            </div>
          ) : (
            <div className="text-lg font-head font-bold flex items-center gap-2" data-testid="viewer-title">
              <span>{plateOverride || item.plate || (item.type || item.label || "Détection")}</span>
              {kind === "plate" && item.id && (
                <button
                  onClick={() => { setPlateDraft(plateOverride || item.plate || ""); setEditingPlate(true); }}
                  title={t("ev.fix_plate")}
                  data-testid="viewer-plate-edit-btn"
                  className="p-1 text-white/40 hover:text-white shrink-0"
                >
                  <Pencil size={14} />
                </button>
              )}
            </div>
          )}
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
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">{t("ev.vehicle_color")}</span><span className="mono">{item.vehicle_color}</span></div>
          )}
          {item.vehicle_make && (
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">{t("ev.vehicle")}</span><span className="mono">{item.vehicle_make} {item.vehicle_model} ({item.vehicle_type})</span></div>
          )}
          {item.motion_pct != null && (
            <div className="text-xs"><span className="text-[10px] uppercase tracking-wider text-white/40 mr-1">Mouvement</span><span className="mono">{item.motion_pct}%</span></div>
          )}
        </div>

        <div className="p-4 border-t border-white/10 space-y-2">
          {/* v3.1.8 · "Analyser OCR" = sélection de zone directe, plus d'analyse
              automatique pleine image en aveugle. Raison : les moteurs OCR sans
              localisation de plaque dédiée (easyocr/tesseract/opencv-ocr/
              paddle-ocr — tout sauf fast-alpr) lisaient parfois un texte
              quelconque dans tout le crop véhicule et le retournaient comme
              "plaque" à confiance moyenne (ex. observé en prod : "G57695" à 55%
              sur une plaque réelle "ED-241-LZ") — un faux positif silencieux,
              pire qu'aucune lecture. Tracer soi-même le rectangle sur la
              plaque élimine ce risque. Visible même si une plaque est déjà
              connue (`item.plate`) : permet de corriger/reconfirmer une
              lecture automatique douteuse — le résultat écrase `event.plate`
              en base (voir routers.py::reanalyze_event). */}
          {kind === "event" && item.thumbnail && (
            <button
              onClick={() => { setSelectMode((v) => !v); setSelectRect(null); setSelectStart(null); }}
              data-testid="viewer-select-zone-btn"
              className={`w-full flex items-center justify-center gap-2 px-3 py-2 border text-xs ${
                selectMode ? "border-[#00E5FF] text-[#00E5FF] bg-[#00E5FF]/10" : "border-white/20 text-white/80 hover:bg-white/10"
              }`}
            >
              <ScanSearch size={14} /> {selectMode ? "Annuler la sélection" : "Analyser OCR (sélectionner une zone)"}
            </button>
          )}
          {ocrResult?.plate && (
            <div className="p-2 border border-[#00E676]/30 bg-[#00E676]/5 text-xs">
              <div className="text-[10px] uppercase tracking-wider text-[#00E676] mb-1">Nouvelle lecture OCR</div>
              <div className="mono text-white font-bold text-base">{ocrResult.plate}</div>
              <div className="text-[10px] text-white/60 mono">
                Confiance {Math.round((ocrResult.confidence || 0) * 100)}%{ocrResult.engine ? ` · ${ocrResult.engine}` : ""}
              </div>
            </div>
          )}

          {/* Boucle de feedback vrai/faux positif — events plugin anti-vol
              (type préfixé "retail."), sert de point de collecte pour un
              futur ré-entraînement manuel du modèle. */}
          {kind === "event" && item.id && (item.type || "").startsWith("retail.") && (
            feedbackSent ? (
              <div className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-white/20 text-white/60 text-xs">
                {feedbackSent === "true_positive" ? <ThumbsUp size={14} /> : <ThumbsDown size={14} />}
                Marqué {feedbackSent === "true_positive" ? "vrai positif" : "faux positif"}
              </div>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={async () => {
                    setFeedbackLoading(true);
                    try {
                      await api.post(`/events/${item.id}/feedback`, { verdict: "true_positive" });
                      setFeedbackSent("true_positive");
                      toast.success("Marqué comme vrai positif");
                    } catch (e) {
                      toast.error(e.response?.data?.detail || "Feedback impossible");
                    } finally { setFeedbackLoading(false); }
                  }}
                  disabled={feedbackLoading}
                  data-testid="viewer-feedback-tp-btn"
                  className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-[#00E676]/50 text-[#00E676] hover:bg-[#00E676]/10 disabled:opacity-50 text-xs"
                >
                  <ThumbsUp size={14} /> Vrai positif
                </button>
                <button
                  onClick={async () => {
                    setFeedbackLoading(true);
                    try {
                      await api.post(`/events/${item.id}/feedback`, { verdict: "false_positive" });
                      setFeedbackSent("false_positive");
                      toast.success("Marqué comme faux positif");
                    } catch (e) {
                      toast.error(e.response?.data?.detail || "Feedback impossible");
                    } finally { setFeedbackLoading(false); }
                  }}
                  disabled={feedbackLoading}
                  data-testid="viewer-feedback-fp-btn"
                  className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-[#FF3B30]/50 text-[#FF3B30] hover:bg-[#FF3B30]/10 disabled:opacity-50 text-xs"
                >
                  <ThumbsDown size={14} /> Faux positif
                </button>
              </div>
            )
          )}

          <button onClick={playAround} disabled={recLoading || showVideo} data-testid="viewer-play-video-btn"
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[#0044FF] text-white hover:bg-[#0033cc] disabled:opacity-50">
            <PlayCircle size={16} /> {showVideo ? "Vidéo en cours" : "Lire la vidéo autour de cet événement"}
          </button>
          {/* v1.0-rc4 · Fusion : historique complet de la plaque / du véhicule */}
          {(plateOverride || item.plate || ocrResult?.plate) && onOpenPlate && (
            <button
              onClick={() => onOpenPlate(plateOverride || item.plate || ocrResult.plate)}
              data-testid="viewer-plate-history-btn"
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10"
            >
              <History size={15} /> Historique du véhicule ({plateOverride || item.plate || ocrResult.plate})
            </button>
          )}
          <button
            onClick={() => { onClose(); navigate(`/timeline${item.camera_id ? `?camera_id=${encodeURIComponent(item.camera_id)}` : ""}`); }}
            data-testid="viewer-timeline-btn"
            className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-white/20 text-white/80 hover:bg-white/10"
          >
            <GanttChartSquare size={15} /> Voir dans la Timeline
          </button>
          {showVideo && (
            <button onClick={() => setShowVideo(false)} className="w-full text-xs text-white/60 hover:text-white">{t("ev.back_to_image")}</button>
          )}
          <div className="text-[10px] text-white/40 text-center mono">
            {index + 1} / {items.length} · ← / → navigation · Échap fermer
          </div>
        </div>
      </aside>
    </div>
  );
}
