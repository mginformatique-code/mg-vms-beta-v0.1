/**
 * PipelineCenter — Hub Pipeline v0.5.0.a
 *
 * Regroupe 10 sous-vues opérationnelles autour de l'exécution IA :
 *   Overview · Capture · AI · Tracking · Plugins · Workflows ·
 *   Designer · Inspector · Performance · Debug
 *
 * Consomme uniquement les APIs backend existantes :
 *   /api/diagnostics/capture/stats           (v0.4.5.a)
 *   /api/diagnostics/pipeline-v2/stats       (v0.4.1)
 *   /api/diagnostics/pipeline-inspector      (v0.4.2)
 *   /api/plugins/*                           (existant)
 *
 * Zéro modification backend.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";
import {
  Activity, Camera, Cpu, GitBranch, Layers, LineChart, Puzzle,
  ScrollText, Terminal, Workflow, RefreshCw,
} from "lucide-react";

import PipelineInspector from "./PipelineInspector";
import PipelineDesigner from "./PipelineDesigner";
import AIPipelineMonitor from "./AIPipelineMonitor";

const TABS = [
  { id: "overview",    label: "Overview",    icon: Layers },
  { id: "capture",     label: "Capture",     icon: Camera },
  { id: "ai",          label: "AI",          icon: Cpu },
  { id: "tracking",    label: "Tracking",    icon: GitBranch },
  { id: "plugins",     label: "Plugins",     icon: Puzzle },
  { id: "workflows",   label: "Workflows",   icon: Workflow },
  { id: "designer",    label: "Designer",    icon: GitBranch },
  { id: "inspector",   label: "Inspector",   icon: Activity },
  { id: "performance", label: "Performance", icon: LineChart },
  { id: "debug",       label: "Debug",       icon: Terminal },
];

export default function PipelineCenter() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const setTab = (t) => setParams({ tab: t });

  return (
    <div className="p-6 space-y-6" data-testid="pipeline-center">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Pipeline Center</h1>
          <p className="text-sm text-muted-foreground">
            Diagnostic complet du pipeline temps réel — capture, IA, tracking, plugins.
          </p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="space-y-6">
        <TabsList className="flex flex-wrap h-auto justify-start"
                  data-testid="pipeline-center-tabs">
          {TABS.map(({ id, label, icon: Icon }) => (
            <TabsTrigger key={id} value={id} data-testid={`tab-${id}`}
                          className="gap-2">
              <Icon className="w-4 h-4" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview"><OverviewPanel /></TabsContent>
        <TabsContent value="capture"><CapturePanel /></TabsContent>
        <TabsContent value="ai"><AIPanel /></TabsContent>
        <TabsContent value="tracking"><TrackingPanel /></TabsContent>
        <TabsContent value="plugins"><PluginsPanel /></TabsContent>
        <TabsContent value="workflows"><WorkflowsPanel /></TabsContent>
        <TabsContent value="designer"><PipelineDesigner /></TabsContent>
        <TabsContent value="inspector"><PipelineInspector /></TabsContent>
        <TabsContent value="performance"><AIPipelineMonitor /></TabsContent>
        <TabsContent value="debug"><DebugPanel /></TabsContent>
      </Tabs>
    </div>
  );
}

// ───────── Overview : synthèse temps réel ─────────
function OverviewPanel() {
  const [capture, setCapture] = useState({ workers: {}, mode: null });
  const [pipeline, setPipeline] = useState({ per_camera: {} });
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [c, p] = await Promise.all([
        api.get("/diagnostics/capture/stats").catch(() => ({ data: {} })),
        api.get("/diagnostics/pipeline-v2/stats").catch(() => ({ data: {} })),
      ]);
      setCapture(c.data || {});
      setPipeline(p.data || {});
    } finally { setLoading(false); }
  }, []);
  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 5000);
    return () => clearInterval(iv);
  }, [refresh]);

  const cams = Object.keys(capture.workers || {});

  return (
    <div className="space-y-4" data-testid="pipeline-overview">
      <div className="flex items-center gap-2">
        <Badge variant="outline">Mode capture : {capture.mode || "—"}</Badge>
        <Badge variant={capture.cuvid_available ? "default" : "secondary"}>
          NVDEC : {capture.cuvid_available ? "OK" : "indispo"}
        </Badge>
        <Button size="sm" variant="ghost" onClick={refresh} data-testid="overview-refresh">
          <RefreshCw className="w-4 h-4 mr-2" />Rafraîchir
        </Button>
      </div>
      {cams.length === 0 && !loading && (
        <Card className="p-6 text-sm text-muted-foreground" data-testid="pipeline-empty">
          Aucune caméra active. Activer <code>detect_enabled</code> sur une caméra
          pour voir le pipeline en action.
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {cams.map((camId) => {
          const w = capture.workers[camId] || {};
          const pc = (pipeline.per_camera || {})[camId] || {};
          const nPlugins = Object.keys(pc).length;
          return (
            <Card key={camId} className="p-4 space-y-2" data-testid={`cam-card-${camId}`}>
              <div className="flex items-center justify-between">
                <div className="font-mono text-sm truncate">{camId}</div>
                <Badge variant={w.alive ? "default" : "destructive"}>
                  {w.alive ? "en ligne" : "hors ligne"}
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground">
                {w.resolution} · {w.codec} · GPU:{String(w.gpu)}
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <Stat label="FPS capture" value={w.fps_capture_1min ?? "—"} />
                <Stat label="Age frame" value={fmtMs(w.last_frame_age_ms)} />
                <Stat label="Produites" value={w.frames_produced ?? 0} />
                <Stat label="Droppées" value={w.frames_dropped ?? 0} />
                <Stat label="Plugins actifs" value={nPlugins} />
                <Stat label="Reconnect" value={w.reconnect_count ?? 0} />
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="text-sm">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

const fmtMs = (v) => (v == null ? "—" : `${v} ms`);

// ───────── Capture ─────────
function CapturePanel() {
  const [data, setData] = useState({ workers: {} });
  useEffect(() => {
    const load = async () => {
      const r = await api.get("/diagnostics/capture/stats").catch(() => ({ data: {} }));
      setData(r.data || {});
    };
    load();
    const iv = setInterval(load, 3000);
    return () => clearInterval(iv);
  }, []);
  const rows = Object.entries(data.workers || {});
  return (
    <Card className="p-4" data-testid="capture-panel">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="pb-2">Caméra</th>
            <th>Codec</th>
            <th>Résolution</th>
            <th>FPS 1min</th>
            <th>Produites</th>
            <th>Droppées</th>
            <th>Warmup</th>
            <th>Reconnect</th>
            <th>État</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([id, w]) => (
            <tr key={id} className="border-t border-border/40">
              <td className="py-2 font-mono">{id}</td>
              <td>{w.codec}</td>
              <td>{w.resolution}</td>
              <td className="font-mono">{w.fps_capture_1min ?? "—"}</td>
              <td className="font-mono">{w.frames_produced ?? 0}</td>
              <td className="font-mono">{w.frames_dropped ?? 0}</td>
              <td className="font-mono">{fmtMs(w.warmup_ms)}</td>
              <td className="font-mono">{w.reconnect_count ?? 0}</td>
              <td>
                <Badge variant={w.alive ? "default" : "destructive"}>
                  {w.alive ? "ok" : "down"}
                </Badge>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={9} className="py-6 text-center text-muted-foreground"
                    data-testid="capture-empty">
              Aucun worker capture actif.
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

// ───────── AI, Tracking, Workflows, Plugins, Debug (panneaux légers) ─────────
function AIPanel() {
  const [snap, setSnap] = useState(null);
  useEffect(() => {
    const load = async () => {
      const r = await api.get("/diagnostics/pipeline-inspector").catch(() => ({ data: {} }));
      setSnap(r.data || {});
    };
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);
  if (!snap) return <Card className="p-6 text-sm">Chargement…</Card>;
  const runtime = snap.runtime || {};
  const sys = snap.system || {};
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="ai-panel">
      <Card className="p-4 space-y-2">
        <div className="text-sm text-muted-foreground">Modèle · Device</div>
        <div className="font-mono text-lg">{sys.device || "auto"}</div>
        <Stat label="Workers actifs" value={runtime.workers?.length ?? 0} />
      </Card>
      <Card className="p-4 space-y-2">
        <div className="text-sm text-muted-foreground">Système</div>
        <Stat label="CPU %" value={sys.cpu_percent ?? "—"} />
        <Stat label="RAM %" value={sys.ram_percent ?? "—"} />
        <Stat label="GPU %" value={sys.gpu_percent ?? "—"} />
        <Stat label="VRAM %" value={sys.vram_percent ?? "—"} />
      </Card>
    </div>
  );
}

function TrackingPanel() {
  const [snap, setSnap] = useState(null);
  useEffect(() => {
    api.get("/diagnostics/pipeline-inspector").then((r) => setSnap(r.data)).catch(() => setSnap({}));
  }, []);
  // v0.5.1.c fix : `runtime.trackers` peut être un dict {camera_id: {...}} ou
  // un array selon la version du backend. Normalise en array ici.
  const raw = snap?.runtime?.trackers;
  const trackers = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object"
      ? Object.entries(raw).map(([camera_id, v]) => ({
          camera_id,
          algo: v?.algo || v?.type,
          active_tracks: v?.active_tracks ?? v?.tracks ?? v?.count,
          ...v,
        }))
      : [];
  return (
    <Card className="p-4" data-testid="tracking-panel">
      <div className="text-sm text-muted-foreground mb-3">
        Un tracker par caméra active (v0.4.3). Algo par défaut : ByteTrack.
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th>Caméra</th><th>Algo</th><th>Objets suivis</th>
          </tr>
        </thead>
        <tbody>
          {trackers.map((t) => (
            <tr key={t.camera_id} className="border-t border-border/40">
              <td className="py-2 font-mono">{t.camera_id}</td>
              <td>{t.algo || "bytetrack"}</td>
              <td className="font-mono">{t.active_tracks ?? "—"}</td>
            </tr>
          ))}
          {trackers.length === 0 && (
            <tr><td colSpan={3} className="py-6 text-center text-muted-foreground">
              Aucun tracker actif.
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

function PluginsPanel() {
  const [stats, setStats] = useState({ per_plugin: [] });
  useEffect(() => {
    const load = async () => {
      const r = await api.get("/diagnostics/pipeline-v2/stats").catch(() => ({ data: {} }));
      setStats(r.data || { per_plugin: [] });
    };
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);
  return (
    <Card className="p-4" data-testid="plugins-panel">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th>Plugin</th><th>État</th><th>Interface</th>
            <th>Calls</th><th>Errors</th><th>Timeouts</th><th>Last ms</th>
          </tr>
        </thead>
        <tbody>
          {(stats.per_plugin || []).map((p) => (
            <tr key={p.name} className="border-t border-border/40">
              <td className="py-2 font-mono">{p.name}</td>
              <td>
                <Badge variant={p.state === "ready" ? "default" : "secondary"}>
                  {p.state || "?"}
                </Badge>
              </td>
              <td>{p.interface || "—"}</td>
              <td className="font-mono">{p.calls ?? 0}</td>
              <td className="font-mono">{p.errors ?? 0}</td>
              <td className="font-mono">{p.timeouts ?? 0}</td>
              <td className="font-mono">{p.last_ms ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function WorkflowsPanel() {
  return (
    <Card className="p-4" data-testid="workflows-panel">
      <div className="text-sm text-muted-foreground">
        Les workflows sont pilotés dans la page dédiée{" "}
        <a href="/workflows" className="underline">Workflows</a>. Cette vue affichera
        prochainement les compteurs d&apos;exécution par workflow.
      </div>
    </Card>
  );
}

function DebugPanel() {
  const [logs, setLogs] = useState("");
  const load = useCallback(async () => {
    try {
      const r = await api.get("/diagnostics/logs?tail=200").catch(() => ({ data: "" }));
      setLogs(typeof r.data === "string" ? r.data : JSON.stringify(r.data, null, 2));
    } catch (e) {
      setLogs("(endpoint indisponible sur ce backend)");
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <Card className="p-4 space-y-3" data-testid="debug-panel">
      <div className="flex justify-between items-center">
      <div className="text-sm text-muted-foreground">Logs récents (tail 200)</div>
        <Button size="sm" variant="ghost" onClick={load}>
          <RefreshCw className="w-4 h-4 mr-2" />Rafraîchir
        </Button>
      </div>
      <pre className="text-xs font-mono bg-black/40 p-3 rounded max-h-96 overflow-auto">
        {logs || "…"}
      </pre>
    </Card>
  );
}
