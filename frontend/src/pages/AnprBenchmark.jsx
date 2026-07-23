import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Play, Save, Trash2, Zap, Cpu, Camera as CamIcon, Gauge } from "lucide-react";

function fmtMs(v) { return v == null ? "—" : `${Number(v).toFixed(1)} ms`; }

function ResultCard({ label, run, isBaseline }) {
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
        <Info label="Résolution" value={run.resolution_analyzed} />
        <Info label="FPS estimé" value={run.estimated_fps} highlight />
        <Info label="Cycle total (moy.)" value={fmtMs(run.avg_total_ms)} highlight />
        <Info label="YOLO (moy.)" value={fmtMs(run.avg_yolo_ms)} />
        <Info label="ALPR (moy.)" value={fmtMs(run.avg_alpr_ms)} />
        <Info label="Détections/frame" value={run.avg_detections_per_frame} />
        <Info label="Plaques trouvées" value={run.plates_detected_total} />
        <Info label="OCR réussi" value={run.plates_ocr_success} />
        <Info label="Taux OCR" value={`${run.ocr_success_rate}%`} highlight />
        <Info label="Torch" value={`${run.torch_version || "?"} · ${run.torch_backend}`} />
        <Info label="CUDA" value={run.cuda_version || "—"} />
        <Info label="Modèle YOLO" value={run.yolo_model} />
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
  const [cams, setCams] = useState([]);
  const [cameraId, setCameraId] = useState("");
  const [iterations, setIterations] = useState(5);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState(null);
  const [baseline, setBaseline] = useState(() => {
    try { return JSON.parse(localStorage.getItem("mg_anpr_baseline") || "null"); } catch { return null; }
  });

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data)).catch(() => setCams([]));
  }, []);

  const runBenchmark = async () => {
    setRunning(true);
    setCurrent(null);
    try {
      const params = new URLSearchParams({ iterations: String(iterations) });
      if (cameraId) params.set("camera_id", cameraId);
      const { data } = await api.post(`/system/anpr-benchmark?${params}`);
      setCurrent(data);
      toast.success(`Benchmark terminé : ${data.avg_total_ms} ms/cycle · ${data.estimated_fps} FPS estimés`);
    } catch (e) {
      toast.error("Benchmark échoué : " + (e.response?.data?.detail || e.message));
    } finally {
      setRunning(false);
    }
  };

  const saveBaseline = () => {
    if (!current) return;
    localStorage.setItem("mg_anpr_baseline", JSON.stringify(current));
    setBaseline(current);
    toast.success("Baseline enregistrée pour comparaison future");
  };

  const clearBaseline = () => {
    localStorage.removeItem("mg_anpr_baseline");
    setBaseline(null);
    toast.info("Baseline effacée");
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Gauge size={22} /> Performance ANPR — Benchmark & Comparaison
        </h1>
      </div>

      <p className="text-xs text-muted-foreground mb-4 max-w-3xl">
        Exécute le pipeline ANPR complet (YOLO + fast-alpr) sur un frame réel de caméra et mesure temps + taux de détection.
        Sauvegarde une <b>baseline</b> puis relance après un changement (nouveau modèle, GPU activé, config modifiée) pour visualiser la régression/amélioration.
      </p>

      {/* Configuration */}
      <div className="border border-border p-3 mb-4 flex items-center gap-3 flex-wrap" data-testid="benchmark-config">
        <div>
          <label className="text-[9px] uppercase tracking-wider text-muted-foreground">Caméra</label>
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}
                  className="block px-2 py-1 text-xs bg-card border border-input" data-testid="benchmark-camera">
            <option value="">Auto (première online)</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase tracking-wider text-muted-foreground">Itérations</label>
          <input type="number" min="1" max="30" value={iterations}
                  onChange={(e) => setIterations(Math.max(1, Math.min(30, Number(e.target.value) || 5)))}
                  className="block w-20 px-2 py-1 text-xs bg-card border border-input" data-testid="benchmark-iterations" />
        </div>
        <button onClick={runBenchmark} disabled={running} data-testid="benchmark-run"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E676] text-[#00E676] hover:bg-[#00E676] hover:text-black disabled:opacity-50">
          <Play size={13} className={running ? "animate-pulse" : ""} /> {running ? "En cours…" : "Lancer le benchmark"}
        </button>
        {current && (
          <button onClick={saveBaseline} data-testid="benchmark-save-baseline"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF] hover:text-black">
            <Save size={13} /> Enregistrer comme baseline
          </button>
        )}
        {baseline && (
          <button onClick={clearBaseline} data-testid="benchmark-clear-baseline"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
            <Trash2 size={13} /> Effacer baseline
          </button>
        )}
      </div>

      {/* Résultats côte à côte */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <ResultCard label="Baseline (ancienne version)" run={baseline} isBaseline={true} />
        <ResultCard label="Version actuelle" run={current} isBaseline={false} />
      </div>

      {/* Delta */}
      {baseline && current && (
        <div className="border border-border p-3 bg-card" data-testid="benchmark-delta">
          <div className="font-head font-semibold mb-2">Comparaison Baseline → Actuel</div>
          <CompareBar label="Cycle total" a={baseline.avg_total_ms} b={current.avg_total_ms} unit=" ms" better="lower" />
          <CompareBar label="YOLO" a={baseline.avg_yolo_ms} b={current.avg_yolo_ms} unit=" ms" better="lower" />
          <CompareBar label="ALPR" a={baseline.avg_alpr_ms} b={current.avg_alpr_ms} unit=" ms" better="lower" />
          <CompareBar label="FPS estimés" a={baseline.estimated_fps} b={current.estimated_fps} better="higher" />
          <CompareBar label="Plaques détectées (total)" a={baseline.plates_detected_total} b={current.plates_detected_total} better="higher" />
          <CompareBar label="Taux OCR" a={baseline.ocr_success_rate} b={current.ocr_success_rate} unit=" %" better="higher" />
          <CompareBar label="Détections/frame" a={baseline.avg_detections_per_frame} b={current.avg_detections_per_frame} better="higher" />
          <div className="mt-3 pt-3 border-t border-border text-[11px] text-muted-foreground space-y-1">
            <div>Baseline : <b className="text-foreground">{baseline.torch_backend.toUpperCase()}</b> · torch {baseline.torch_version}{baseline.cuda_version ? ` · CUDA ${baseline.cuda_version}` : ""} · {baseline.resolution_analyzed}</div>
            <div>Actuel : <b className="text-foreground">{current.torch_backend.toUpperCase()}</b> · torch {current.torch_version}{current.cuda_version ? ` · CUDA ${current.cuda_version}` : ""} · {current.resolution_analyzed}</div>
            {baseline.gpu_active !== current.gpu_active && (
              <div className="text-[#FFB800] mt-1">
                ⚠ Le backend d&apos;accélération a changé entre les 2 mesures ({baseline.gpu_active ? "GPU" : "CPU"} → {current.gpu_active ? "GPU" : "CPU"}) — c&apos;est probablement la cause principale de l&apos;écart de perf.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
