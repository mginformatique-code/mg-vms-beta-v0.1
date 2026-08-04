/**
 * AIPipelineMonitor — Dashboard temps réel du pipeline IA MG-VMS vNext.
 *
 * Consomme :
 *   - GET /api/diagnostics/pipeline-metrics  (per-camera FPS, latences par étape, drops)
 *   - GET /api/plugins/config/tracking/config (ByteTrack config)
 *   - PUT /api/plugins/config/tracking/config (tuning à chaud)
 *
 * Objectifs affichés (seuils P0 Feb 2026) :
 *   - FPS ≥ 20 (idéal 20-30)
 *   - realtime_ms < 200 (chemin critique vidéo)
 *   - tracking_ms < 50
 *   - drops_5s = 0 (backpressure)
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Activity, Cpu, Zap, RefreshCw, Save, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Boxes, Radar } from "lucide-react";

const STAGE_META = {
  fetch_ms:       { label: "Fetch frame",  color: "#00B0FF", target: 100, hint: "Récupération frame (go2rtc / frame_source GPU)" },
  yolo_ms:        { label: "YOLO",         color: "#00E5FF", target: 80,  hint: "Inférence YOLOv11 (détection)" },
  tracking_ms:    { label: "ByteTrack",    color: "#00E676", target: 50,  hint: "Tracking persistant (association IDs)" },
  alpr_ms:        { label: "ANPR local",   color: "#FFB800", target: 300, hint: "fast-alpr ONNX (plaques)" },
  realtime_ms:    { label: "Live total",   color: "#FF9500", target: 200, hint: "Chemin critique vidéo (Phase A)" },
  downstream_ms:  { label: "Downstream",   color: "#B085FF", target: 2000, hint: "Plugins/Zones/Workflows/Events (Phase B — non bloquant)" },
};

function StatusPill({ ok, warn, label, value, unit = "" }) {
  const color = ok ? "#00E676" : warn ? "#FFB800" : "#FF3333";
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 border" style={{ borderColor: color, color }} data-testid={`pill-${label}`}>
      {ok ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
      <span className="text-[10px] uppercase tracking-wider">{label}</span>
      <span className="text-xs mono font-bold">{value}{unit}</span>
    </div>
  );
}

function StageBar({ stage, stats }) {
  const meta = STAGE_META[stage];
  if (!meta || !stats) return null;
  const avg = stats.avg || 0;
  const max = stats.max || 0;
  const target = meta.target;
  const pct = Math.min(100, (avg / (target * 1.5)) * 100);
  const overBudget = avg > target;
  return (
    <div className="border-b border-border/40 py-1.5" data-testid={`stage-${stage}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5" style={{ backgroundColor: meta.color }} />
          <span className="text-[11px] mono">{meta.label}</span>
        </div>
        <div className="flex items-center gap-2 mono text-[11px]">
          <span style={{ color: overBudget ? "#FF3333" : "#00E676" }}>{avg.toFixed(0)} ms</span>
          <span className="text-muted-foreground">max {max.toFixed(0)}</span>
          {stats.p95 != null && <span className="text-muted-foreground">p95 {stats.p95.toFixed(0)}</span>}
        </div>
      </div>
      <div className="h-1 bg-secondary/40 relative overflow-hidden">
        <div className="h-full transition-all" style={{ width: `${pct}%`, backgroundColor: overBudget ? "#FF3333" : meta.color }} />
        {/* target marker */}
        <div className="absolute top-0 h-full border-r border-white/40" style={{ left: `${(target / (target * 1.5)) * 100}%` }} title={`Cible ${target} ms`} />
      </div>
    </div>
  );
}

function CameraCard({ id, cam, name }) {
  const [open, setOpen] = useState(false);
  const fps = cam.fps_5s || 0;
  const rt = cam.stages?.realtime_ms?.avg || 0;
  const drops = cam.drops_5s || 0;
  const errors = cam.error_count || 0;
  const fpsOk = fps >= 15;
  const fpsWarn = fps >= 5 && fps < 15;
  const rtOk = rt < 200;
  const rtWarn = rt < 500;
  const dropsOk = drops === 0;
  const plugins = cam.last_plugins || {};

  return (
    <div className="border border-border" data-testid={`cam-card-${id}`}>
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 hover:bg-secondary/40">
        <div className="flex items-center gap-3">
          <div className="text-left">
            <div className="text-sm font-medium truncate max-w-[280px]">{name || id}</div>
            <div className="text-[10px] mono text-muted-foreground">{id}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <StatusPill ok={fpsOk} warn={fpsWarn} label="FPS" value={fps} />
          <StatusPill ok={rtOk} warn={rtWarn} label="Live" value={rt.toFixed(0)} unit="ms" />
          <StatusPill ok={dropsOk} warn={false} label="Drops" value={drops} />
          {errors > 0 && <StatusPill ok={false} warn={false} label="Err" value={errors} />}
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>
      {open && (
        <div className="border-t border-border p-3 bg-background/30" data-testid={`cam-detail-${id}`}>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Latences par étape</div>
          {Object.keys(STAGE_META).map((stage) => (
            <StageBar key={stage} stage={stage} stats={cam.stages?.[stage]} />
          ))}
          {(plugins.detectors?.length > 0 || plugins.trackers?.length > 0 || plugins.business?.length > 0) && (
            <div className="mt-3 pt-3 border-t border-border/40">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Plugins actifs sur le dernier cycle</div>
              <div className="flex flex-wrap gap-1.5">
                {(plugins.detectors || []).map((p, i) => (
                  <span key={`d${i}`} className="text-[10px] mono px-1.5 py-0.5 border border-[#00E5FF]/40 text-[#00E5FF]">detect · {p}</span>
                ))}
                {(plugins.trackers || []).map((p, i) => (
                  <span key={`t${i}`} className="text-[10px] mono px-1.5 py-0.5 border border-[#00E676]/40 text-[#00E676]">track · {p}</span>
                ))}
                {(plugins.business || []).map((p, i) => (
                  <span key={`b${i}`} className="text-[10px] mono px-1.5 py-0.5 border border-[#B085FF]/40 text-[#B085FF]">biz · {p}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ByteTrackTuner({ cfg, onChange, onSave, saving }) {
  const set = (k, v) => onChange({ ...cfg, [k]: v });
  return (
    <div className="border border-border p-3" data-testid="bytetrack-tuner">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Boxes size={14} className="text-[#00E676]" />
          <span className="text-xs font-medium">ByteTrack · Tuning temps réel</span>
        </div>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} data-testid="bt-enabled" />
          <span>Activé</span>
        </label>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
        <div>
          <div className="text-[10px] uppercase text-muted-foreground mb-1">Track threshold</div>
          <input type="number" step="0.05" min="0.1" max="0.9" value={cfg.track_thresh || 0.25}
            onChange={(e) => set("track_thresh", parseFloat(e.target.value))}
            className="w-full px-2 py-1 bg-card border border-input mono" data-testid="bt-track-thresh" />
          <div className="text-[10px] text-muted-foreground mt-0.5">Bas = plus permissif (0.25 recommandé)</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted-foreground mb-1">Match threshold</div>
          <input type="number" step="0.05" min="0.5" max="0.95" value={cfg.match_thresh || 0.85}
            onChange={(e) => set("match_thresh", parseFloat(e.target.value))}
            className="w-full px-2 py-1 bg-card border border-input mono" data-testid="bt-match-thresh" />
          <div className="text-[10px] text-muted-foreground mt-0.5">Haut = matching strict (0.85)</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted-foreground mb-1">Track buffer (frames)</div>
          <input type="number" step="5" min="5" max="300" value={cfg.track_buffer || 60}
            onChange={(e) => set("track_buffer", parseInt(e.target.value))}
            className="w-full px-2 py-1 bg-card border border-input mono" data-testid="bt-track-buffer" />
          <div className="text-[10px] text-muted-foreground mt-0.5">Durée avant perte d&apos;ID (60 ≈ 30s @2FPS)</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted-foreground mb-1">Min box area (px²)</div>
          <input type="number" step="10" min="10" max="10000" value={cfg.min_box_area || 100}
            onChange={(e) => set("min_box_area", parseInt(e.target.value))}
            className="w-full px-2 py-1 bg-card border border-input mono" data-testid="bt-min-area" />
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted-foreground mb-1">ID persist (sec)</div>
          <input type="number" step="10" min="5" max="600" value={cfg.id_persist_seconds || 120}
            onChange={(e) => set("id_persist_seconds", parseInt(e.target.value))}
            className="w-full px-2 py-1 bg-card border border-input mono" data-testid="bt-id-persist" />
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button onClick={onSave} disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#00E676] text-black hover:opacity-90 disabled:opacity-50"
          data-testid="bt-save">
          <Save size={12} /> {saving ? "Enregistrement…" : "Appliquer"}
        </button>
        <span className="text-[10px] text-muted-foreground">La config est appliquée au prochain cycle IA (~2s).</span>
      </div>
    </div>
  );
}

export default function AIPipelineMonitor() {
  const [metrics, setMetrics] = useState({});
  const [cams, setCams] = useState([]);
  const [bt, setBt] = useState({});
  const [btLoaded, setBtLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const load = async () => {
    try {
      const [m, c] = await Promise.all([
        api.get("/diagnostics/pipeline-metrics"),
        api.get("/cameras"),
      ]);
      setMetrics(m.data?.cameras || m.data || {});
      setCams(c.data || []);
      setLastUpdate(new Date());
    } catch (e) {
      // silent
    }
  };

  const loadBt = async () => {
    try {
      const { data } = await api.get("/plugins/tracking/config");
      setBt(data);
      setBtLoaded(true);
    } catch (e) {
      // may not be admin
    }
  };

  const saveBt = async () => {
    setSaving(true);
    try {
      await api.put("/plugins/tracking/config", bt);
      toast.success("ByteTrack : config appliquée");
      await loadBt();
    } catch (e) {
      toast.error("Impossible d'enregistrer la config ByteTrack");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => { load(); loadBt(); }, []);
  useEffect(() => {
    if (!autoRefresh) return;
    const iv = setInterval(load, 2000);
    return () => clearInterval(iv);
  }, [autoRefresh]);

  const camMap = useMemo(() => {
    const m = {};
    for (const c of cams) m[c.id] = c;
    return m;
  }, [cams]);

  // Global aggregate
  const agg = useMemo(() => {
    const cids = Object.keys(metrics);
    if (cids.length === 0) return null;
    let fpsSum = 0, rtSum = 0, drops = 0, errors = 0, count = 0;
    let ytMax = 0, ttMax = 0;
    for (const cid of cids) {
      const m = metrics[cid];
      fpsSum += m.fps_5s || 0;
      rtSum += m.stages?.realtime_ms?.avg || 0;
      drops += m.drops_5s || 0;
      errors += m.error_count || 0;
      ytMax = Math.max(ytMax, m.stages?.yolo_ms?.max || 0);
      ttMax = Math.max(ttMax, m.stages?.tracking_ms?.max || 0);
      count++;
    }
    return {
      cams: count,
      fpsAvg: count ? (fpsSum / count) : 0,
      rtAvg: count ? (rtSum / count) : 0,
      drops, errors, ytMax, ttMax,
    };
  }, [metrics]);

  return (
    <div className="p-4" data-testid="ai-pipeline-monitor">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Activity size={22} className="text-[#00E676]" /> Pipeline IA · Monitoring temps réel
          </h1>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            Frame → YOLO → ByteTrack → Broadcast · Downstream: ANPR/Zones/Workflows/Plugins en workers séparés
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} data-testid="auto-refresh" />
            Auto (2s)
          </label>
          <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary" data-testid="reload-btn">
            <RefreshCw size={12} /> Actualiser
          </button>
          {lastUpdate && <span className="text-[10px] mono text-muted-foreground">MàJ {lastUpdate.toLocaleTimeString("fr-FR")}</span>}
        </div>
      </div>

      {/* Global stats */}
      {agg && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2 mb-4" data-testid="global-agg">
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">Caméras actives</div>
            <div className="text-lg font-bold mono">{agg.cams}</div>
          </div>
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">FPS moyen</div>
            <div className="text-lg font-bold mono" style={{ color: agg.fpsAvg >= 15 ? "#00E676" : agg.fpsAvg >= 5 ? "#FFB800" : "#FF3333" }}>{agg.fpsAvg.toFixed(1)}</div>
          </div>
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">Live avg</div>
            <div className="text-lg font-bold mono" style={{ color: agg.rtAvg < 200 ? "#00E676" : agg.rtAvg < 500 ? "#FFB800" : "#FF3333" }}>{agg.rtAvg.toFixed(0)} <span className="text-xs">ms</span></div>
          </div>
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">YOLO max</div>
            <div className="text-lg font-bold mono">{agg.ytMax.toFixed(0)} <span className="text-xs">ms</span></div>
          </div>
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">Tracking max</div>
            <div className="text-lg font-bold mono" style={{ color: agg.ttMax < 50 ? "#00E676" : "#FFB800" }}>{agg.ttMax.toFixed(0)} <span className="text-xs">ms</span></div>
          </div>
          <div className="border border-border p-2.5">
            <div className="text-[10px] uppercase text-muted-foreground">Drops · Errors</div>
            <div className="text-lg font-bold mono">
              <span style={{ color: agg.drops > 0 ? "#FFB800" : "#00E676" }}>{agg.drops}</span>
              <span className="text-muted-foreground"> · </span>
              <span style={{ color: agg.errors > 0 ? "#FF3333" : "#00E676" }}>{agg.errors}</span>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Camera list */}
        <div className="lg:col-span-2 space-y-2" data-testid="cameras-list">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Caméras · pipeline par instance</div>
          {Object.keys(metrics).length === 0 ? (
            <div className="border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              Aucune métrique. Assurez-vous qu&apos;au moins une caméra a <code>detect_enabled=true</code> et <code>status=online</code>.
            </div>
          ) : (
            Object.entries(metrics).map(([id, m]) => (
              <CameraCard key={id} id={id} cam={m} name={camMap[id]?.name} />
            ))
          )}
        </div>

        {/* Right side: ByteTrack tuner */}
        <div className="space-y-3" data-testid="right-panel">
          {btLoaded && <ByteTrackTuner cfg={bt} onChange={setBt} onSave={saveBt} saving={saving} />}

          <div className="border border-border p-3">
            <div className="flex items-center gap-2 mb-2">
              <Radar size={14} className="text-[#B085FF]" />
              <span className="text-xs font-medium">Objectifs P0 · 1080p</span>
            </div>
            <ul className="text-[11px] space-y-1.5 text-muted-foreground">
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>FPS caméra : <span className="text-foreground mono">20-30</span></span></li>
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>Tracking : <span className="text-foreground mono">&lt; 50 ms</span></span></li>
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>Live path : <span className="text-foreground mono">&lt; 200 ms</span></span></li>
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>Perte d&apos;ID : <span className="text-foreground mono">minimale</span></span></li>
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>Plugins simultanés indépendants</span></li>
              <li className="flex items-start gap-1.5"><Zap size={11} className="mt-0.5 text-[#00E676]" /> <span>ANPR anti-doublons (état Entrée/Présence/Sortie)</span></li>
            </ul>
          </div>

          <div className="border border-border p-3">
            <div className="flex items-center gap-2 mb-2">
              <Cpu size={14} className="text-[#00E5FF]" />
              <span className="text-xs font-medium">Architecture</span>
            </div>
            <pre className="text-[10px] mono leading-relaxed text-muted-foreground whitespace-pre-wrap">
Camera Stream
  ↓
Frame Pipeline (fetch → decode)
  ↓
Detection (YOLO) + ByteTrack   ← Phase A (SYNC, {'<'}200ms)
  ↓
Event Bus (asyncio.create_task)
  ↓
├── ANPR multi-engine
├── Smart Zones
├── Workflows
└── Plugin business events     ← Phase B (fire-and-forget)</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
