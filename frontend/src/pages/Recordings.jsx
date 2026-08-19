import React, { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Film, Play, Calendar, Clock, HardDrive, Activity, Cctv, AlertTriangle, Circle, Scissors, Download, FileArchive, Loader2, X } from "lucide-react";
import { toast } from "sonner";

const MODE_COLORS = { continuous: "#0044FF", motion: "#FFB800", ai: "#00E676" };
const DAY_SEC = 86400;
const MIN_SPAN_SEC = 60; // zoom max : fenêtre d'1 minute

// Pas de graduation adapté à la largeur de fenêtre visible (vise ~6-12 graduations)
const TICK_STEPS = [60, 300, 600, 900, 1800, 3600, 2 * 3600, 4 * 3600, 6 * 3600, 12 * 3600, DAY_SEC];
function pickTickStep(spanSec) {
  for (const step of TICK_STEPS) if (spanSec / step <= 12) return step;
  return DAY_SEC;
}
function fmtTick(sec, step) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return step < 60 ? `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    : `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
}

function fmtDur(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m.toString().padStart(2, "0")}` : `${m} min`;
}
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function secToHHMM(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
}
function hhmmToSec(v) {
  const [h, m] = v.split(":").map(Number);
  return (h || 0) * 3600 + (m || 0) * 60;
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border border-border bg-card" data-testid={`rec-stat-${label}`}>
      <Icon size={16} className="text-[#0044FF]" strokeWidth={1.5} />
      <div className="leading-tight">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-head font-bold mono">{value}</div>
      </div>
    </div>
  );
}

export default function Recordings() {
  const { t, hasPerm } = useApp();
  const [searchParams] = useSearchParams();
  const [cams, setCams] = useState([]);
  const [cameraId, setCameraId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  // export
  const [selStart, setSelStart] = useState(8 * 3600);
  const [selEnd, setSelEnd] = useState(10 * 3600);
  const [hasSel, setHasSel] = useState(false);
  const [format, setFormat] = useState("zip");
  const [exporting, setExporting] = useState(false);
  const [exports, setExports] = useState([]);
  const [viewStart, setViewStart] = useState(0);
  const [viewEnd, setViewEnd] = useState(DAY_SEC);
  const timelineRef = useRef(null);
  const dragRef = useRef(null);
  const viewRef = useRef({ start: 0, end: DAY_SEC });
  viewRef.current = { start: viewStart, end: viewEnd };

  useEffect(() => {
    api.get("/cameras", { params: { status: "online" } })
      .then((r) => {
        setCams(r.data);
        const q = searchParams.get("camera");
        const pre = q && r.data.find((c) => c.id === q);
        setCameraId(pre ? q : (r.data[0]?.id || ""));
      })
      .catch(() => {});
  }, []);

  const loadExports = () => api.get("/recordings/exports").then((r) => setExports(r.data)).catch(() => {});
  useEffect(() => { loadExports(); }, []);

  useEffect(() => {
    if (!cameraId) return;
    setLoading(true);
    setSelected(null);
    setViewStart(0); setViewEnd(DAY_SEC); // reset zoom : nouvelle caméra/jour = nouvelle fenêtre
    api.get("/recordings/timeline", { params: { camera_id: cameraId, date } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [cameraId, date]);

  const segments = data?.segments || [];
  const viewSpan = viewEnd - viewStart;
  const zoomed = viewSpan < DAY_SEC - 1;

  const secToX = (sec) => ((sec - viewStart) / viewSpan) * 100;

  const segPos = (seg) => {
    const s = new Date(seg.start);
    const startSec = s.getHours() * 3600 + s.getMinutes() * 60 + s.getSeconds();
    const left = secToX(startSec);
    const width = (seg.duration_sec / viewSpan) * 100;
    return { left: `${left}%`, width: `${Math.max(width, 0.3)}%` };
  };

  const play = (seg) => {
    setSelected(seg);
    api.get(`/recordings/${seg.id}/playback`).catch(() => {});
  };

  const xToSec = (clientX) => {
    const el = timelineRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(viewStart + ratio * viewSpan);
  };
  const onDown = (e) => { dragRef.current = { x: e.clientX, sec: xToSec(e.clientX), moved: false }; };
  const onMove = (e) => {
    if (!dragRef.current) return;
    if (Math.abs(e.clientX - dragRef.current.x) < 4) return;
    dragRef.current.moved = true;
    const cur = xToSec(e.clientX);
    const a = Math.min(dragRef.current.sec, cur), b = Math.max(dragRef.current.sec, cur);
    setSelStart(a); setSelEnd(b); setHasSel(true);
  };
  const onUp = () => { dragRef.current = null; };
  const resetZoom = () => { setViewStart(0); setViewEnd(DAY_SEC); };

  // Zoom molette centré sur le curseur. Écouteur natif non-passif (obligatoire pour
  // pouvoir appeler preventDefault() sur "wheel" — React attache onWheel en passif
  // par défaut depuis la v17, ce qui bloquerait silencieusement le zoom sinon).
  useEffect(() => {
    const el = timelineRef.current;
    if (!el) return;
    const onWheelNative = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const { start, end } = viewRef.current;
      const span = end - start;
      const cursorSec = start + ratio * span;
      const factor = e.deltaY < 0 ? 0.8 : 1.25; // molette haut = zoom avant
      let newSpan = Math.min(DAY_SEC, Math.max(MIN_SPAN_SEC, span * factor));
      let newStart = cursorSec - ratio * newSpan;
      let newEnd = newStart + newSpan;
      if (newStart < 0) { newEnd -= newStart; newStart = 0; }
      if (newEnd > DAY_SEC) { newStart -= (newEnd - DAY_SEC); newEnd = DAY_SEC; }
      newStart = Math.max(0, newStart);
      setViewStart(newStart); setViewEnd(newEnd);
    };
    el.addEventListener("wheel", onWheelNative, { passive: false });
    return () => el.removeEventListener("wheel", onWheelNative);
  }, [cameraId, date]);

  const isoFromSec = (sec) => {
    const d = new Date(`${date}T00:00:00`);
    d.setSeconds(sec);
    return d.toISOString();
  };

  const doExport = async () => {
    if (selEnd <= selStart) return toast.error("La fin doit être après le début");
    setExporting(true);
    try {
      const { data: exp } = await api.post("/recordings/export", {
        camera_id: cameraId, start: isoFromSec(selStart), end: isoFromSec(selEnd), format,
      });
      if (exp.format === "zip" && exp.status === "ready") {
        toast.success(`Export ZIP prêt (${exp.segment_count} segments)`);
        await downloadExport(exp.id);
      } else {
        toast.info(t("rec.mp4_production"));
      }
      loadExports();
    } catch (e) { toast.error("Échec de l'export"); } finally { setExporting(false); }
  };

  const downloadExport = async (id) => {
    try {
      const r = await api.get(`/recordings/exports/${id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url; a.download = `mgvms_export_${id.slice(0, 8)}.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { toast.error("Téléchargement indisponible (MP4 = production)"); }
  };

  const selPct = { left: `${secToX(selStart)}%`, width: `${((selEnd - selStart) / viewSpan) * 100}%` };
  const tickStep = pickTickStep(viewSpan);
  const ticks = [];
  for (let t = Math.ceil(viewStart / tickStep) * tickStep; t <= viewEnd; t += tickStep) ticks.push(t);

  return (
    <div className="p-4 md:p-6 space-y-5" data-testid="recordings-page">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Film size={22} className="text-[#0044FF]" /> {t("rec.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">{t("rec.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 border border-border bg-card px-2">
            <Cctv size={15} className="text-muted-foreground" />
            <select data-testid="rec-camera-select" value={cameraId} onChange={(e) => setCameraId(e.target.value)}
              className="bg-transparent text-sm py-2 outline-none min-w-[180px]">
              {cams.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.site_name}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-1.5 border border-border bg-card px-2">
            <Calendar size={15} className="text-muted-foreground" />
            <input data-testid="rec-date-input" type="date" value={date} max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setDate(e.target.value)} className="bg-transparent text-sm py-2 outline-none" />
          </div>
        </div>
      </div>

      {!cameraId ? (
        <div className="text-muted-foreground text-sm py-20 text-center">{t("rec.no_camera")}</div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat icon={Clock} label={t("rec.coverage")} value={data ? fmtDur(data.coverage_sec) : "—"} />
            <Stat icon={HardDrive} label={t("rec.size")} value={data ? `${data.total_size_mb} MB` : "—"} />
            <Stat icon={Activity} label={t("rec.segments")} value={segments.length} />
            <Stat icon={AlertTriangle} label={t("rec.events")} value={data?.event_count ?? 0} />
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            {/* Player */}
            <div className="lg:col-span-2 space-y-3">
              <div className="relative bg-black aspect-video overflow-hidden border border-border" data-testid="rec-player">
                {selected ? (
                  <>
                    <video key={selected.id} controls autoPlay className="w-full h-full object-contain bg-black" data-testid="rec-video"
                      src={`${process.env.REACT_APP_BACKEND_URL}/api/recordings/${selected.id}/media?token=${encodeURIComponent(localStorage.getItem("mg_token") || "")}`}
                      onEnded={() => {
                        // v0.7.e · Wave E · Auto-passe au segment suivant à la
                        // fin de la lecture (comportement Reolink-like). Fixe
                        // le bug perçu de « boucle vidéo qui répète le même
                        // segment » : sans cet handler, la vidéo restait sur
                        // la dernière frame et l'utilisateur devait cliquer
                        // manuellement le segment suivant.
                        const idx = segments.findIndex((s) => s.id === selected.id);
                        if (idx >= 0 && idx < segments.length - 1) {
                          play(segments[idx + 1]);
                        }
                      }} />
                    <div className="absolute top-0 inset-x-0 flex items-center justify-between px-3 py-2 bg-gradient-to-b from-black/80 to-transparent pointer-events-none">
                      <span className="text-xs mono text-white">{data?.camera?.name}</span>
                      <span className="text-xs mono text-white">{fmtTime(selected.start)} – {fmtTime(selected.end)} · {fmtDur(selected.duration_sec)}</span>
                    </div>
                  </>
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-white/40">
                    <Film size={32} />
                    <span className="text-xs">{t("rec.select_segment")}</span>
                  </div>
                )}
              </div>

              {/* Timeline 24h — molette pour zoomer, glisser pour sélectionner un export */}
              <div className="border border-border bg-card p-3" data-testid="rec-timeline">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-muted-foreground">Molette : zoomer/dézoomer · glisser-déposer : sélectionner un export</span>
                  {zoomed && (
                    <button onClick={resetZoom} data-testid="rec-zoom-reset"
                      className="text-[10px] px-1.5 py-0.5 border border-border hover:bg-secondary text-muted-foreground">
                      Réinitialiser le zoom ({fmtDur(Math.round(viewSpan))})
                    </button>
                  )}
                </div>
                <div ref={timelineRef} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}
                  className="relative h-10 bg-secondary/50 overflow-hidden cursor-crosshair select-none">
                  {/* graduations (pas adapté au niveau de zoom) */}
                  {ticks.map((tk) => (
                    <div key={tk} className="absolute top-0 bottom-0 border-l border-border/40"
                      style={{ left: `${secToX(tk)}%` }} />
                  ))}
                  {/* selection overlay */}
                  {hasSel && (
                    <div className="absolute top-0 bottom-0 bg-[#0044FF]/25 border-x-2 border-[#0044FF] pointer-events-none z-20"
                      style={selPct} data-testid="rec-selection" />
                  )}
                  {/* segments */}
                  {segments.map((seg) => (
                    <button key={seg.id} data-testid={`rec-segment-${seg.id}`} title={`${fmtTime(seg.start)} · ${t(`rec.mode.${seg.mode}`)}`}
                      onClick={() => play(seg)} style={{ ...segPos(seg), backgroundColor: MODE_COLORS[seg.mode] }}
                      className={`absolute top-2 bottom-2 hover:brightness-125 transition-all ${selected?.id === seg.id ? "ring-2 ring-white z-10" : ""}`}>
                      {seg.has_event && <span className="absolute -top-1.5 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-[#FF3333]" />}
                    </button>
                  ))}
                </div>
                {/* graduations horaires */}
                <div className="relative h-4 mt-1">
                  {ticks.map((tk) => (
                    <span key={tk} className="absolute text-[9px] mono text-muted-foreground -translate-x-1/2"
                      style={{ left: `${secToX(tk)}%` }}>{fmtTick(tk, tickStep)}</span>
                  ))}
                </div>
                {/* legend */}
                <div className="flex items-center gap-4 mt-3 flex-wrap">
                  {Object.entries(MODE_COLORS).map(([k, c]) => (
                    <span key={k} className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <span className="w-3 h-2" style={{ backgroundColor: c }} /> {t(`rec.mode.${k}`)}
                    </span>
                  ))}
                  <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#FF3333]" /> {t("rec.event_marker")}
                  </span>
                </div>

                {/* Export controls */}
                {hasPerm("export_files") && (<>
                <div className="mt-4 pt-3 border-t border-border" data-testid="rec-export-panel">
                  <div className="flex items-center gap-2 mb-2">
                    <Scissors size={14} className="text-[#0044FF]" />
                    <span className="text-xs uppercase tracking-wider font-medium">{t("rec.export")}</span>
                    <span className="text-[10px] text-muted-foreground">— {t("rec.drag_hint")}</span>
                  </div>
                  <div className="flex items-end gap-2 flex-wrap">
                    <div>
                      <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rec.from")}</label>
                      <input type="time" data-testid="rec-export-from" value={secToHHMM(selStart)}
                        onChange={(e) => { setSelStart(hhmmToSec(e.target.value)); setHasSel(true); }}
                        className="bg-card border border-input text-sm px-2 py-1.5 outline-none mono" />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rec.to")}</label>
                      <input type="time" data-testid="rec-export-to" value={secToHHMM(selEnd)}
                        onChange={(e) => { setSelEnd(hhmmToSec(e.target.value)); setHasSel(true); }}
                        className="bg-card border border-input text-sm px-2 py-1.5 outline-none mono" />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rec.format")}</label>
                      <select data-testid="rec-export-format" value={format} onChange={(e) => setFormat(e.target.value)}
                        className="bg-card border border-input text-sm px-2 py-1.5 outline-none">
                        <option value="zip">ZIP</option>
                        <option value="mp4">MP4</option>
                      </select>
                    </div>
                    <button onClick={doExport} disabled={exporting} data-testid="rec-export-btn"
                      className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc] disabled:opacity-60">
                      {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} {t(exporting ? "rec.exporting" : "rec.export_btn")}
                    </button>
                    {hasSel && (
                      <button onClick={() => setHasSel(false)} data-testid="rec-clear-sel"
                        className="flex items-center gap-1 px-2 py-2 border border-border text-xs hover:bg-secondary">
                        <X size={13} /> {t("rec.clear_sel")}
                      </button>
                    )}
                    <span className="text-[11px] text-muted-foreground mono ml-auto">{secToHHMM(selStart)} → {secToHHMM(selEnd)} · {fmtDur(selEnd - selStart)}</span>
                  </div>
                </div>

                {/* Recent exports */}
                {exports.length > 0 && (
                  <div className="mt-3 space-y-1" data-testid="rec-exports-list">
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rec.recent_exports")}</div>
                    {exports.slice(0, 4).map((ex) => (
                      <div key={ex.id} className="flex items-center gap-2 text-xs border border-border px-2 py-1.5" data-testid={`rec-export-${ex.id}`}>
                        <FileArchive size={13} className="text-muted-foreground shrink-0" />
                        <span className="mono truncate">{ex.camera_name}</span>
                        <span className="text-muted-foreground">{fmtTime(ex.start)}–{fmtTime(ex.end)}</span>
                        <span className="text-[9px] uppercase px-1 py-0.5 border border-border">{ex.format}</span>
                        <span className="text-[9px] uppercase" style={{ color: ex.status === "ready" ? "#00E676" : "#FFB800" }}>
                          {t(ex.status === "ready" ? "rec.status.ready" : "rec.status.queued")}
                        </span>
                        <div className="ml-auto">
                          {ex.format === "zip" && ex.status === "ready" ? (
                            <button onClick={() => downloadExport(ex.id)} data-testid={`rec-dl-${ex.id}`} className="flex items-center gap-1 text-[#0044FF] hover:underline">
                              <Download size={12} /> {t("rec.download")}
                            </button>
                          ) : (
                            <span className="text-[9px] text-muted-foreground">{t("rec.mp4_production")}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                </>)}
              </div>
            </div>

            {/* Segment list */}
            <div className="border border-border bg-card flex flex-col max-h-[560px]" data-testid="rec-segment-list">
              <div className="px-3 py-2 border-b border-border text-xs uppercase tracking-wider text-muted-foreground font-medium">
                {t("rec.segments")} · {segments.length}
              </div>
              <div className="flex-1 overflow-y-auto divide-y divide-border">
                {loading ? (
                  <div className="p-4 text-sm text-muted-foreground">{t("common.loading")}</div>
                ) : segments.length === 0 ? (
                  <div className="p-4 text-sm text-muted-foreground">{t("rec.no_segments")}</div>
                ) : segments.map((seg) => (
                  <button key={seg.id} data-testid={`rec-listitem-${seg.id}`} onClick={() => play(seg)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-secondary transition-colors ${selected?.id === seg.id ? "bg-secondary" : ""}`}>
                    <div className="w-14 h-9 bg-black shrink-0 flex items-center justify-center"><Film size={14} className="text-white/40" /></div>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs mono">{fmtTime(seg.start)} – {fmtTime(seg.end)}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] uppercase tracking-wider px-1 py-0.5" style={{ color: MODE_COLORS[seg.mode] }}>{t(`rec.mode.${seg.mode}`)}</span>
                        <span className="text-[10px] text-muted-foreground mono">{seg.size_mb} MB</span>
                        {seg.has_event && <AlertTriangle size={11} className="text-[#FF3333]" />}
                      </div>
                    </div>
                    <Play size={14} className="text-muted-foreground shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
