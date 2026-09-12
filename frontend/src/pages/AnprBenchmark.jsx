import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { Play, Save, Trash2, Zap, Cpu, Camera as CamIcon, Gauge } from "lucide-react";

function fmtMs(v) { return v == null ? "—" : `${Number(v).toFixed(1)} ms`; }

function ResultCard({ label, run, isBaseline }) {
  const { t } = useApp();
  if (!run) return null;
  return (
    <div className={`border p-3 bg-card ${isBaseline ? "border-[#00E5FF]" : "border-border"}`} data-testid={`benchmark-card-${label}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
          <div className="text-xs mono text-muted-foreground">{new Date(run.run_at).toLocaleString("fr-FR")}</div>
        </div>
        <div className={`text-[10px] mono font-bold px-2 py-1 ${run.gpu_active ? "bg-[#00E676] text-black" : "bg-[#FF3333] text-white"}`}>
          {run.gpu_active ? "GPU" : "CPU"}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <Info label={t("anprb.resolution")} value={run.resolution_analyzed} />
        <Info label={t("anprb.fps_estimated")} value={run.estimated_fps} highlight />
        <Info label={t("anprb.total_cycle_avg")} value={fmtMs(run.avg_total_ms)} highlight />
        <Info label={t("anprb.yolo_avg")} value={fmtMs(run.avg_yolo_ms)} />
        <Info label={t("anprb.alpr_avg")} value={fmtMs(run.avg_alpr_ms)} />
        <Info label={t("anprb.detections_per_frame")} value={run.avg_detections_per_frame} />
        <Info label={t("anprb.plates_found")} value={run.plates_detected_total} />
        <Info label={t("anprb.ocr_success")} value={run.plates_ocr_success} />
        <Info label={t("anprb.ocr_rate")} value={`${run.ocr_success_rate}%`} highlight />
        <Info label={t("anprb.torch")} value={`${run.torch_version || "?"} · ${run.torch_backend}`} />
        <Info label={t("anprb.cuda")} value={run.cuda_version || "—"} />
        <Info label={t("anprb.yolo_model")} value={run.yolo_model} />
      </div>
    </div>
  );
}

function Info({ label, value, highlight }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`mono ${highlight ? "font-bold text-sm text-foreground" : "text-xs"}`}>{String(value ?? "—")}</div>
    </div>
  );
}

function CompareBar({ label, a, b, unit = "", better = "lower" }) {
  if (a == null || b == null) return null;
  const av = Number(a) || 0, bv = Number(b) || 0;
  const delta = bv - av;
  const pct = av !== 0 ? (delta / av) * 100 : 0;
  const goodForB = better === "lower" ? bv < av : bv > av;
  const color = goodForB ? "#00E676" : (av === bv ? "#666" : "#FF3333");
  return (
    <div className="flex items-center gap-2 border-b border-border py-2">
      <span className="text-xs w-40">{label}</span>
      <span className="mono text-sm w-24 text-right">{av.toFixed(1)}{unit}</span>
      <span className="text-muted-foreground">→</span>
      <span className="mono text-sm w-24 text-right" style={{ color }}>{bv.toFixed(1)}{unit}</span>
      <span className="mono text-xs w-24 text-right" style={{ color }}>
        {delta > 0 ? "+" : ""}{delta.toFixed(1)}{unit} ({pct > 0 ? "+" : ""}{pct.toFixed(1)}%)
      </span>
    </div>
  );
}

export default function AnprBenchmark() {
  const { t } = useApp();
  const [cams, setCams] = useState([]);
  const [cameraId, setCameraId] = useState("");
  const [iterations, setIterations] = useState(5);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState(null);
  // v1.0-rc4 · Sélection multi-moteurs OCR + fusion
  const ENGINES = [
    { id: "yolo",       label: t("anprb.engine_yolo") },
    { id: "fast-alpr",  label: "FastALPR" },
    { id: "paddle-ocr", label: "PaddleOCR" },
    { id: "easyocr",    label: "EasyOCR" },
    { id: "opencv-ocr", label: "OpenCV OCR" },
    { id: "tesseract",  label: "Tesseract" },
  ];
  const [selEngines, setSelEngines] = useState(["yolo", "fast-alpr"]);
  const [fusionOcr, setFusionOcr] = useState(true);
  const [baseline, setBaseline] = useState(() => {
    try { return JSON.parse(localStorage.getItem("mg_anpr_baseline") || "null"); } catch { return null; }
  });

  const toggleEngine = (id) => setSelEngines((prev) =>
    prev.includes(id) ? prev.filter((e) => e !== id) : [...prev, id]);
  const allSelected = selEngines.length === ENGINES.length;
  const toggleAll = () => setSelEngines(allSelected ? [] : ENGINES.map((e) => e.id));

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data)).catch(() => setCams([]));
  }, []);

  const runBenchmark = async () => {
    setRunning(true);
    setCurrent(null);
    try {
      const params = new URLSearchParams({ iterations: String(iterations) });
      if (cameraId) params.set("camera_id", cameraId);
      const ocrEngines = selEngines.filter((e) => e !== "yolo");
      if (ocrEngines.length) params.set("engines", ocrEngines.join(","));
      if (fusionOcr && ocrEngines.length > 1) params.set("fusion", "true");
      const { data } = await api.post(`/system/anpr-benchmark?${params}`);
      setCurrent(data);
      toast.success(`${t("anprb.toast_done_prefix")} ${data.avg_total_ms} ms/cycle · ${data.estimated_fps} ${t("anprb.toast_done_suffix")}`);
    } catch (e) {
      toast.error(`${t("anprb.toast_failed_prefix")} ` + (e.response?.data?.detail || e.message));
    } finally {
      setRunning(false);
    }
  };

  const saveBaseline = () => {
    if (!current) return;
    localStorage.setItem("mg_anpr_baseline", JSON.stringify(current));
    setBaseline(current);
    toast.success(t("anprb.toast_baseline_saved"));
  };

  const clearBaseline = () => {
    localStorage.removeItem("mg_anpr_baseline");
    setBaseline(null);
    toast.info(t("anprb.toast_baseline_cleared"));
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Gauge size={22} /> {t("anprb.title")}
        </h1>
      </div>

      <p className="text-xs text-muted-foreground mb-4 max-w-3xl">
        {t("anprb.desc_p1")} <b>baseline</b> {t("anprb.desc_p2")}
      </p>

      {/* Configuration */}
      <div className="border border-border p-3 mb-4 flex items-center gap-3 flex-wrap" data-testid="benchmark-config">
        <div>
          <label className="text-[9px] uppercase tracking-wider text-muted-foreground">{t("anprb.camera_label")}</label>
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}
                  className="block px-2 py-1 text-xs bg-card border border-input" data-testid="benchmark-camera">
            <option value="">{t("anprb.camera_auto")}</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase tracking-wider text-muted-foreground">{t("anprb.iterations_label")}</label>
          <input type="number" min="1" max="30" value={iterations}
                  onChange={(e) => setIterations(Math.max(1, Math.min(30, Number(e.target.value) || 5)))}
                  className="block w-20 px-2 py-1 text-xs bg-card border border-input" data-testid="benchmark-iterations" />
        </div>
        <button onClick={runBenchmark} disabled={running} data-testid="benchmark-run"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E676] text-[#00E676] hover:bg-[#00E676] hover:text-black disabled:opacity-50">
          <Play size={13} className={running ? "animate-pulse" : ""} /> {running ? t("anprb.running") : t("anprb.run_benchmark")}
        </button>
        {current && (
          <button onClick={saveBaseline} data-testid="benchmark-save-baseline"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF] hover:text-black">
            <Save size={13} /> {t("anprb.save_baseline")}
          </button>
        )}
        {baseline && (
          <button onClick={clearBaseline} data-testid="benchmark-clear-baseline"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
            <Trash2 size={13} /> {t("anprb.clear_baseline")}
          </button>
        )}
      </div>

      {/* v1.0-rc4 · Sélection des moteurs à benchmarker */}
      <div className="border border-border p-3 mb-4" data-testid="benchmark-engines">
        <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">
          {t("anprb.engines_label")}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {ENGINES.map((e) => {
            const on = selEngines.includes(e.id);
            return (
              <button key={e.id} onClick={() => toggleEngine(e.id)}
                      data-testid={`benchmark-engine-${e.id}`}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs border transition-colors ${
                        on ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] font-medium"
                           : "border-border text-muted-foreground hover:border-[#0044FF]/60"
                      }`}>
                <span className={`inline-block w-3 h-3 border ${on ? "bg-[#0044FF] border-[#0044FF]" : "border-border"}`} />
                {e.label}
              </button>
            );
          })}
          <button onClick={toggleAll} data-testid="benchmark-engine-all"
                  className={`px-2.5 py-1.5 text-xs border ${allSelected ? "border-[#00E676] text-[#00E676]" : "border-border text-muted-foreground hover:border-[#00E676]/60"}`}>
            {t("anprb.all")}
          </button>
          <label className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-[#FFB800]/60 text-[#FFB800] cursor-pointer ml-auto" data-testid="benchmark-fusion-toggle">
            <input type="checkbox" checked={fusionOcr} onChange={(e) => setFusionOcr(e.target.checked)} className="accent-[#FFB800]" />
            {t("anprb.fusion_label")}
          </label>
        </div>
      </div>

      {/* v1.0-rc4 · Résultats par moteur OCR */}
      {current?.ocr_engines?.length > 0 && (
        <div className="border border-border p-3 mb-4 bg-card" data-testid="benchmark-ocr-results">
          <div className="font-head font-semibold mb-2 flex items-center gap-2"><Cpu size={15} /> {t("anprb.ocr_compare_heading")}</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[9px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="text-left py-1.5 pr-3">{t("anprb.col_engine")}</th>
                  <th className="text-left py-1.5 pr-3">{t("anprb.col_state")}</th>
                  <th className="text-right py-1.5 pr-3">{t("anprb.col_avg_time")}</th>
                  <th className="text-right py-1.5 pr-3">CPU</th>
                  <th className="text-right py-1.5 pr-3">{t("anprb.col_ram_delta")}</th>
                  <th className="text-right py-1.5 pr-3">{t("anprb.col_plates_read")}</th>
                  <th className="text-left py-1.5">{t("anprb.col_best_reading")}</th>
                </tr>
              </thead>
              <tbody>
                {current.ocr_engines.map((r) => (
                  <tr key={r.engine} className="border-b border-border/50" data-testid={`ocr-row-${r.engine}`}>
                    <td className="py-1.5 pr-3 mono font-semibold">{r.engine}</td>
                    <td className="py-1.5 pr-3">
                      {r.available ? (
                        <span className="text-[#00E676] text-[10px] uppercase">READY</span>
                      ) : (
                        <span className="text-[#FF3333] text-[10px] uppercase" title={r.message}>
                          {r.state === "missing_dependency" ? t("anprb.dep_missing") : (r.state || t("anprb.unavailable")).toUpperCase()}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-right mono">{r.avg_ms != null ? `${r.avg_ms} ms` : "—"}</td>
                    <td className="py-1.5 pr-3 text-right mono">{r.cpu_pct != null ? `${r.cpu_pct}%` : "—"}</td>
                    <td className="py-1.5 pr-3 text-right mono">{r.ram_delta_mb != null ? `${r.ram_delta_mb} Mo` : "—"}</td>
                    <td className="py-1.5 pr-3 text-right mono">{r.plates_read_total ?? "—"}</td>
                    <td className="py-1.5 mono">
                      {r.best_plate ? `${r.best_plate.text} (${Math.round(r.best_plate.confidence * 100)}%)` : (r.error || r.message || "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {current.fusion_result && (
            <div className="mt-3 border border-[#FFB800]/50 bg-[#FFB800]/5 p-2 text-xs" data-testid="benchmark-fusion-result">
              <div className="text-[9px] uppercase tracking-wider text-[#FFB800] mb-1">{t("anprb.fusion_result_label")}</div>
              <span className="mono font-bold text-base">{current.fusion_result.text}</span>
              <span className="mono text-muted-foreground ml-2">
                {t("anprb.confidence_avg_prefix")} {Math.round(current.fusion_result.avg_confidence * 100)}% · {t("anprb.engines_used_prefix")} {current.fusion_result.engines_used.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Résultats côte à côte */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <ResultCard label={t("anprb.baseline_label")} run={baseline} isBaseline={true} />
        <ResultCard label={t("anprb.current_label")} run={current} isBaseline={false} />
      </div>

      {/* Delta */}
      {baseline && current && (
        <div className="border border-border p-3 bg-card" data-testid="benchmark-delta">
          <div className="font-head font-semibold mb-2">{t("anprb.compare_heading")}</div>
          <CompareBar label={t("anprb.cb_total_cycle")} a={baseline.avg_total_ms} b={current.avg_total_ms} unit=" ms" better="lower" />
          <CompareBar label="YOLO" a={baseline.avg_yolo_ms} b={current.avg_yolo_ms} unit=" ms" better="lower" />
          <CompareBar label="ALPR" a={baseline.avg_alpr_ms} b={current.avg_alpr_ms} unit=" ms" better="lower" />
          <CompareBar label={t("anprb.cb_fps")} a={baseline.estimated_fps} b={current.estimated_fps} better="higher" />
          <CompareBar label={t("anprb.cb_plates_detected_total")} a={baseline.plates_detected_total} b={current.plates_detected_total} better="higher" />
          <CompareBar label={t("anprb.cb_ocr_rate")} a={baseline.ocr_success_rate} b={current.ocr_success_rate} unit=" %" better="higher" />
          <CompareBar label={t("anprb.cb_detections_per_frame")} a={baseline.avg_detections_per_frame} b={current.avg_detections_per_frame} better="higher" />
          <div className="mt-3 pt-3 border-t border-border text-[11px] text-muted-foreground space-y-1">
            <div>{t("anprb.baseline_prefix")} <b className="text-foreground">{baseline.torch_backend.toUpperCase()}</b> · torch {baseline.torch_version}{baseline.cuda_version ? ` · CUDA ${baseline.cuda_version}` : ""} · {baseline.resolution_analyzed}</div>
            <div>{t("anprb.current_prefix")} <b className="text-foreground">{current.torch_backend.toUpperCase()}</b> · torch {current.torch_version}{current.cuda_version ? ` · CUDA ${current.cuda_version}` : ""} · {current.resolution_analyzed}</div>
            {baseline.gpu_active !== current.gpu_active && (
              <div className="text-[#FFB800] mt-1">
                {t("anprb.backend_changed_prefix")} ({baseline.gpu_active ? "GPU" : "CPU"} → {current.gpu_active ? "GPU" : "CPU"}) {t("anprb.backend_changed_suffix")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
