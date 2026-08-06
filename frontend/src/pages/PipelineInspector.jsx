/**
 * PipelineInspector — Diagnostic runtime du Pipeline v2, par caméra × stage.
 *
 * Consomme GET /api/diagnostics/pipeline-inspector :
 *   fetch → decode → motion → yolo → tracking → roi → anpr → dispatch
 *   → multi_anpr → scenarios → persist → websocket → downstream
 * Pour chaque stage : avg / max / last ms, appels, erreurs, timeouts.
 * Système : CPU, RAM, GPU, VRAM. FPS effectif par caméra.
 */
import React, { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Activity, Cpu, MemoryStick, Zap, RefreshCw, Gauge, AlertTriangle } from "lucide-react";

const STAGE_LABELS = {
  fetch: "Fetch RTSP", decode: "Decode", motion: "Motion", yolo: "YOLO",
  tracking: "Tracking", roi: "ROI cache", anpr: "FastALPR", dispatch: "PluginBus",
  multi_anpr: "Multi-ANPR", scenarios: "Scénarios", persist: "Mongo",
  websocket: "WebSocket", downstream: "Downstream",
};

const stageColor = (ms) => (ms > 500 ? "#FF3333" : ms > 150 ? "#FFB800" : "#00E676");

function SysCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="border border-border bg-card p-3 flex items-center gap-3" data-testid={`sys-${label}`}>
      <Icon size={18} className="text-primary shrink-0" />
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-bold mono truncate">{value}</div>
        {sub && <div className="text-[10px] text-muted-foreground truncate">{sub}</div>}
      </div>
    </div>
  );
}

function StageCell({ st }) {
  if (!st) return <td className="px-2 py-1.5 text-center text-muted-foreground/40 text-xs">—</td>;
  const c = stageColor(st.avg_ms_60s || st.avg_ms);
  return (
    <td className="px-2 py-1.5 text-center">
      <div className="mono text-xs font-bold" style={{ color: c }}>
        {(st.avg_ms_60s || st.avg_ms).toFixed(1)}<span className="text-[9px] opacity-60">ms</span>
      </div>
      <div className="text-[9px] text-muted-foreground mono">
        max {st.max_ms.toFixed(0)} · {st.calls} appels
        {st.errors > 0 && <span className="text-red-500"> · {st.errors} err</span>}
        {st.timeouts > 0 && <span className="text-amber-500"> · {st.timeouts} TO</span>}
      </div>
    </td>
  );
}

export default function PipelineInspector() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/diagnostics/pipeline-inspector");
      setData(r.data);
    } catch (e) {
      toast.error("Pipeline Inspector indisponible");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const sys = data?.system || {};
  const cameras = data?.cameras || {};
  const stageKeys = (data?.stage_order || Object.keys(STAGE_LABELS));

  return (
    <div className="p-6 space-y-6" data-testid="pipeline-inspector-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Gauge size={20} className="text-primary" /> Pipeline Inspector
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Pipeline v2 — CameraWorker → FrameContext → Stages → PluginBus · rafraîchi toutes les 5 s
          </p>
        </div>
        <button onClick={load} data-testid="inspector-refresh-btn"
          className="flex items-center gap-2 px-3 py-1.5 border border-border text-xs hover:bg-accent transition-colors">
          <RefreshCw size={13} /> Rafraîchir
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SysCard icon={Cpu} label="CPU" value={`${sys.cpu_percent ?? "—"}%`}
          sub={`process ${sys.process_cpu_percent ?? "—"}%`} />
        <SysCard icon={MemoryStick} label="RAM"
          value={sys.ram ? `${sys.ram.used_mb} / ${sys.ram.total_mb} Mo` : "—"}
          sub={sys.ram ? `backend ${sys.ram.process_rss_mb} Mo` : ""} />
        <SysCard icon={Zap} label="GPU"
          value={sys.gpu?.device || "Indisponible"}
          sub={sys.gpu?.vram_allocated_mb != null
            ? `VRAM ${sys.gpu.vram_allocated_mb} / ${sys.gpu.vram_total_mb} Mo` : "CPU only"} />
        <SysCard icon={Activity} label="Uptime" value={`${Math.round((sys.uptime_s || 0) / 60)} min`}
          sub={`${Object.keys(cameras).length} caméra(s) inspectée(s)`} />
      </div>

      {loading && <div className="text-sm text-muted-foreground">Chargement…</div>}

      {!loading && Object.keys(cameras).length === 0 && (
        <div className="border border-border p-8 text-center text-sm text-muted-foreground" data-testid="inspector-empty">
          <AlertTriangle size={20} className="mx-auto mb-2 text-amber-500" />
          Aucune caméra n'a encore traversé le pipeline. Activez la détection IA sur au moins une caméra.
        </div>
      )}

      {Object.entries(cameras).map(([cid, cam]) => (
        <div key={cid} className="border border-border bg-card" data-testid={`inspector-camera-${cid}`}>
          <div className="flex items-center justify-between px-4 py-2 border-b border-border">
            <div className="flex items-center gap-3">
              <span className="font-bold text-sm mono">{cid}</span>
              {cam.meta?.tracker && (
                <span className="text-[10px] px-2 py-0.5 border border-primary/40 text-primary uppercase tracking-wider">
                  tracker unique : {cam.meta.tracker}
                </span>
              )}
            </div>
            <span className="mono text-xs font-bold" style={{ color: cam.fps >= 0.4 ? "#00E676" : "#FFB800" }}>
              {cam.fps} FPS pipeline
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/60">
                  {stageKeys.filter((s) => cam.stages[s]).map((s) => (
                    <th key={s} className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                      {STAGE_LABELS[s] || s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {stageKeys.filter((s) => cam.stages[s]).map((s) => (
                    <StageCell key={s} st={cam.stages[s]} />
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
