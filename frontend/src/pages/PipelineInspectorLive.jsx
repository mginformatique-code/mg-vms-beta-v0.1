/**
 * PipelineInspectorLive.jsx — v0.7.g · Wave H · Axe 1+2 · Pipeline Inspector complet.
 *
 * Consomme en direct :
 *   • GET /api/diagnostics/pipeline-inspector  → stages par caméra avec p50/p95/p99
 *   • GET /api/diagnostics/hot-reload          → compteurs Wave A
 *   • GET /api/diagnostics/plate-quality       → seuils Wave C + poids moteurs
 *
 * Toutes les métriques temps réel demandées par l'audit :
 * mean/p50/p95/p99/max/calls/errors/timeouts par stage × caméra, FPS effectif,
 * CPU/RAM/GPU/VRAM, uptime, signaux Hot Reload.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import {
  Activity, ArrowLeft, Cpu, HardDrive, Zap, RefreshCw, AlertTriangle,
  CheckCircle2, TrendingUp, Server, Layers,
} from "lucide-react";

const REFRESH_MS = 2000;   // 2s — sans écraser le CPU
const STAGE_BUDGETS = {
  fetch: 20, decode: 20, motion: 5, yolo: 40, tracking: 5, roi: 5,
  anpr: 120, dispatch: 5, multi_anpr: 120, persist: 15, websocket: 5,
};

const Tile = ({ label, value, hint, tone = "muted", testid }) => {
  const toneMap = {
    ok: "text-[#00E676] border-[#00E676]/40 bg-[#00E676]/5",
    warn: "text-[#FFB800] border-[#FFB800]/40 bg-[#FFB800]/5",
    err: "text-[#FF3333] border-[#FF3333]/40 bg-[#FF3333]/5",
    muted: "text-foreground border-border bg-card",
    info: "text-[#0044FF] border-[#0044FF]/40 bg-[#0044FF]/5",
  };
  return (
    <div className={`border px-3 py-2 ${toneMap[tone]}`} data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.15em] opacity-70 mb-0.5">{label}</div>
      <div className="text-lg font-black mono tabular-nums">{value}</div>
      {hint && <div className="text-[10px] opacity-60 mt-0.5">{hint}</div>}
    </div>
  );
};

const StageRow = ({ stage, s }) => {
  const budget = STAGE_BUDGETS[stage] || 100;
  const overP95 = s.p95_60s > budget;
  const overP99 = s.p99_60s > budget * 1.5;
  const tone = overP99 ? "err" : overP95 ? "warn" : "ok";
  const bar = Math.min(100, (s.avg_ms_60s / budget) * 100);
  return (
    <tr className="border-b border-border/40" data-testid={`stage-row-${stage}`}>
      <td className="py-1.5 px-2 font-medium text-sm">{stage}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums">{s.avg_ms_60s}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums">{s.p50_60s}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums">{s.p95_60s}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums">{s.p99_60s}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums">{s.max_ms}</td>
      <td className="py-1.5 px-2 text-right mono text-xs opacity-60 tabular-nums">{s.calls}</td>
      <td className="py-1.5 px-2 text-right mono text-xs tabular-nums" style={{color: s.errors > 0 ? "#FF3333" : undefined}}>{s.errors}</td>
      <td className="py-1.5 px-2 w-32">
        <div className="h-2 bg-secondary/50 relative overflow-hidden border border-border/40">
          <div className={`h-full ${tone === "err" ? "bg-[#FF3333]" : tone === "warn" ? "bg-[#FFB800]" : "bg-[#00E676]"}`} style={{ width: `${bar}%` }} />
          <div className="absolute inset-y-0 right-0 border-l border-white/40" style={{ width: `${100 - Math.min(100, (budget/budget) * 100)}%`, display: "none" }} />
        </div>
        <div className="text-[9px] opacity-60 mt-0.5 mono">budget {budget}ms</div>
      </td>
    </tr>
  );
};

const CameraCard = ({ camId, snap, name }) => {
  const stages = snap.stages || {};
  const total = Object.values(stages).reduce((sum, s) => sum + (s.avg_ms_60s || 0), 0);
  const totalP95 = Math.max(0, ...Object.values(stages).map((s) => s.p95_60s || 0));
  const totalTone = total < 200 ? "ok" : total < 400 ? "warn" : "err";
  return (
    <div className="bg-card border border-border" data-testid={`pipe-cam-${camId}`}>
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          <Layers size={14} className="text-[#0044FF]" />
          <div className="min-w-0">
            <div className="font-medium text-sm truncate">{name || camId}</div>
            <div className="text-[10px] mono opacity-60 truncate">{camId}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Tile label="FPS" value={snap.fps || 0} tone={snap.fps >= 5 ? "ok" : "warn"} testid={`pipe-cam-fps-${camId}`} />
          <Tile label="Σ avg" value={`${total.toFixed(1)} ms`} tone={totalTone} hint={`budget 200ms`} testid={`pipe-cam-total-${camId}`} />
          <Tile label="max p95" value={`${totalP95.toFixed(1)} ms`} tone={totalP95 > 200 ? "warn" : "ok"} testid={`pipe-cam-maxp95-${camId}`} />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" data-testid={`pipe-cam-table-${camId}`}>
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-muted-foreground border-b border-border/60">
              <th className="text-left py-1.5 px-2">Étage</th>
              <th className="text-right py-1.5 px-2">avg 60s</th>
              <th className="text-right py-1.5 px-2">p50</th>
              <th className="text-right py-1.5 px-2">p95</th>
              <th className="text-right py-1.5 px-2">p99</th>
              <th className="text-right py-1.5 px-2">max</th>
              <th className="text-right py-1.5 px-2">calls</th>
              <th className="text-right py-1.5 px-2">err</th>
              <th className="text-right py-1.5 px-2">budget</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stages).map(([stage, s]) => (
              <StageRow key={stage} stage={stage} s={s} />
            ))}
            {Object.keys(stages).length === 0 && (
              <tr><td colSpan="9" className="text-center py-4 text-muted-foreground text-[11px]">Aucune donnée — la caméra est en démarrage.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {snap.meta && Object.keys(snap.meta).length > 0 && (
        <div className="px-3 py-1.5 border-t border-border/40 text-[10px] mono opacity-70 flex flex-wrap gap-3">
          {Object.entries(snap.meta).map(([k, v]) => (
            <span key={k}><span className="opacity-60">{k}:</span> {String(v)}</span>
          ))}
        </div>
      )}
    </div>
  );
};

export default function PipelineInspectorLive() {
  const [data, setData] = useState(null);
  const [hot, setHot] = useState(null);
  const [pq, setPq] = useState(null);
  const [cams, setCams] = useState({});
  const [paused, setPaused] = useState(false);
  const [err, setErr] = useState(null);

  const refresh = async () => {
    try {
      const [pi, hr, qq, cl] = await Promise.all([
        api.get("/diagnostics/pipeline-inspector"),
        api.get("/diagnostics/hot-reload"),
        api.get("/diagnostics/plate-quality"),
        api.get("/cameras"),
      ]);
      setData(pi.data); setHot(hr.data); setPq(qq.data);
      const m = {};
      (cl.data || []).forEach((c) => { m[c.id] = c.name || c.id; });
      setCams(m);
      setErr(null);
    } catch (e) { setErr(String(e.message || e)); }
  };
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (paused) return;
    const iv = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(iv);
  }, [paused]);

  if (!data) return <div className="p-8 text-muted-foreground" data-testid="pipe-loading">Chargement…</div>;

  const sys = data.system || {};
  const cameras = data.cameras || {};
  const camCount = Object.keys(cameras).length;

  return (
    <div className="p-4 space-y-4 max-w-[1600px] mx-auto" data-testid="pipeline-inspector-live">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-3">
        <div className="flex items-center gap-4">
          <Link to="/health-dashboard" className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1" data-testid="pipe-back">
            <ArrowLeft size={13}/> Health Dashboard
          </Link>
          <div>
            <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">Diagnostics · Pipeline IA</div>
            <h1 className="font-head font-black text-3xl tracking-tight">Pipeline Inspector <span className="text-muted-foreground mono text-lg">live</span></h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setPaused(!paused)} className="border border-border px-3 py-2 text-xs hover:bg-secondary/50 flex items-center gap-1" data-testid="pipe-pause">
            {paused ? <><Zap size={12}/> Reprendre</> : <><RefreshCw size={12}/> Pause auto-refresh</>}
          </button>
          <button onClick={refresh} className="border border-border px-3 py-2 text-xs hover:bg-secondary/50 flex items-center gap-1" data-testid="pipe-refresh">
            <RefreshCw size={12}/> Actualiser
          </button>
        </div>
      </div>

      {err && (
        <div className="border border-[#FF3333]/40 bg-[#FF3333]/10 text-[#FF3333] px-3 py-2 text-sm flex items-center gap-2" data-testid="pipe-error">
          <AlertTriangle size={14}/> {err}
        </div>
      )}

      {/* System */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2" data-testid="pipe-system">
        <Tile label="Caméras suivies" value={camCount} tone={camCount > 0 ? "ok" : "muted"} testid="pipe-cam-count" />
        <Tile label="CPU système" value={`${sys.cpu_percent ?? "—"}%`} tone={(sys.cpu_percent || 0) > 80 ? "warn" : "ok"} testid="pipe-cpu" />
        <Tile label="CPU process" value={`${sys.process_cpu_percent ?? "—"}%`} testid="pipe-cpu-proc" />
        <Tile label="RAM utilisée" value={`${sys.ram?.percent ?? "—"}%`} hint={`${sys.ram?.used_mb ?? "—"} / ${sys.ram?.total_mb ?? "—"} MB`} tone={(sys.ram?.percent || 0) > 85 ? "warn" : "ok"} testid="pipe-ram" />
        <Tile label="RSS process" value={`${sys.ram?.process_rss_mb ?? "—"} MB`} testid="pipe-rss" />
        <Tile label="GPU / VRAM" value={sys.gpu?.available === false ? "N/A" : `${sys.gpu?.vram_allocated_mb ?? "—"} MB`} hint={sys.gpu?.device || "aucun GPU"} tone={sys.gpu?.available === false ? "muted" : "info"} testid="pipe-gpu" />
      </div>

      {/* Hot Reload signals (Wave A) */}
      {hot && (
        <div className="bg-card border border-border p-3" data-testid="pipe-hot-reload">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
            <TrendingUp size={11}/> Hot Reload chirurgical (Wave A)
          </div>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
            <Tile label="Cycles IA" value={hot.cycles_since_boot} testid="pipe-hr-cycles" />
            <Tile label="Sync full" value={hot.topology_syncs_full} hint="TTL 30s (boot inclus)" testid="pipe-hr-full" />
            <Tile label="Sync partiel" value={hot.topology_syncs_partial} tone="info" hint="chirurgie ciblée" testid="pipe-hr-partial" />
            <Tile label="fs starts" value={hot.frame_source_starts} testid="pipe-hr-starts" />
            <Tile label="fs stops" value={hot.frame_source_stops} testid="pipe-hr-stops" />
            <Tile label="Config reloads" value={hot.config_reloads + hot.camera_config_reloads} hint="signal-driven" testid="pipe-hr-reloads" />
          </div>
        </div>
      )}

      {/* Plate quality (Wave C) */}
      {pq && (
        <div className="bg-card border border-border p-3" data-testid="pipe-plate-quality">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
            <CheckCircle2 size={11}/> Gate qualité crop plaque (Wave C)
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            <span><span className="opacity-60">min side:</span> <span className="mono">{pq.thresholds.min_plate_side_px}px</span></span>
            <span><span className="opacity-60">min sharpness:</span> <span className="mono">{pq.thresholds.min_sharpness}</span></span>
            <span><span className="opacity-60">good sharpness:</span> <span className="mono">{pq.thresholds.good_enough_sharpness}</span></span>
            <span><span className="opacity-60">good contrast:</span> <span className="mono">{pq.thresholds.good_enough_contrast}</span></span>
            <span><span className="opacity-60">max skew:</span> <span className="mono">{pq.thresholds.max_skew_deg}°</span></span>
            <span><span className="opacity-60">mode debug:</span> <span className={`mono ${pq.debug_mode.enabled ? "text-[#FFB800]" : "opacity-50"}`}>{pq.debug_mode.enabled ? "ON" : "OFF"}</span></span>
          </div>
          <details className="mt-2 text-[10px] mono opacity-70">
            <summary className="cursor-pointer">Poids moteurs OCR (fusion pondérée)</summary>
            <div className="flex flex-wrap gap-2 mt-1">
              {Object.entries(pq.engine_weights).map(([k, v]) => (
                <span key={k} className="border border-border px-1.5 py-0.5">{k}: <b>{v}</b></span>
              ))}
            </div>
          </details>
        </div>
      )}

      {/* Cameras */}
      <div className="space-y-3">
        {Object.entries(cameras).map(([cid, snap]) => (
          <CameraCard key={cid} camId={cid} snap={snap} name={cams[cid]} />
        ))}
        {camCount === 0 && (
          <div className="border border-border bg-card p-8 text-center text-muted-foreground text-sm" data-testid="pipe-cameras-empty">
            Aucune caméra n&apos;a encore émis de mesure pipeline. Le premier cycle IA arrivera d&apos;ici quelques secondes.
          </div>
        )}
      </div>

      <div className="text-[10px] text-muted-foreground text-center py-2" data-testid="pipe-footer">
        Auto-refresh {paused ? "en pause" : `toutes les ${REFRESH_MS/1000}s`} · uptime pipeline {sys.uptime_s}s ·
        endpoints <span className="mono">/api/diagnostics/pipeline-inspector</span> + <span className="mono">/hot-reload</span> + <span className="mono">/plate-quality</span>
      </div>
    </div>
  );
}
