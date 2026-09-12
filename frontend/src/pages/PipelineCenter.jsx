/**
 * PipelineCenter — Hub Pipeline v0.5.0.a
 *
 * Regroupe 9 sous-vues opérationnelles autour de l'exécution IA :
 *   Overview · AI · Tracking · Plugins · Workflows ·
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
import { useApp } from "@/context/AppContext";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";
import {
  Activity, GitBranch, Layers, LineChart, Puzzle,
  ScrollText, Server, Terminal, Workflow, RefreshCw, Zap,
} from "lucide-react";

import PipelineInspector from "./PipelineInspector";
import AIPipelineMonitor from "./AIPipelineMonitor";
import Hardware from "./Hardware";
import GPUStatus from "./GPUStatus";
import SshConsolePanel from "./SshConsolePanel";
import * as DiagnosticsRegistry from "@/tracking/DiagnosticsRegistry";

const TABS = [
  { id: "overview",    label: "Overview",    icon: Layers },
  { id: "tracking",    label: "Tracking",    icon: GitBranch },
  { id: "plugins",     label: "Plugins",     icon: Puzzle },
  { id: "workflows",   label: "Workflows",   icon: Workflow },
  { id: "inspector",   label: "Inspector",   icon: Activity },
  { id: "performance", label: "Performance", icon: LineChart },
  { id: "hardware",    label: "Hardware",    icon: Server },
  { id: "gpu",         label: "GPU",         icon: Zap },
  { id: "debug",       label: "Debug",       icon: Terminal },
];

export default function PipelineCenter() {
  const { t } = useApp();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const setTab = (v) => setParams({ tab: v });

  return (
    <div className="p-6 space-y-6" data-testid="pipeline-center">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("nav.pipeline_center")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("pcenter.subtitle")}
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
        <TabsContent value="tracking"><TrackingPanel /></TabsContent>
        <TabsContent value="plugins"><PluginsPanel /></TabsContent>
        <TabsContent value="workflows"><WorkflowsPanel /></TabsContent>
        <TabsContent value="inspector"><PipelineInspector /></TabsContent>
        <TabsContent value="performance"><AIPipelineMonitor /></TabsContent>
        <TabsContent value="hardware"><Hardware /></TabsContent>
        <TabsContent value="gpu"><GPUStatus embedded /></TabsContent>
        <TabsContent value="debug"><DebugPanel /></TabsContent>
      </Tabs>
    </div>
  );
}

// ───────── Overview : synthèse temps réel ─────────
function OverviewPanel() {
  const { t } = useApp();
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
        <Badge variant="outline">{t("pcenter.capture_mode_label")} : {capture.mode || "—"}</Badge>
        <Badge variant={capture.cuvid_available ? "default" : "secondary"}>
          NVDEC : {capture.cuvid_available ? "OK" : t("pcenter.unavailable")}
        </Badge>
        <Button size="sm" variant="ghost" onClick={refresh} data-testid="overview-refresh">
          <RefreshCw className="w-4 h-4 mr-2" />{t("pcenter.refresh_btn")}
        </Button>
      </div>
      {cams.length === 0 && !loading && (
        <Card className="p-6 text-sm text-muted-foreground" data-testid="pipeline-empty">
          {t("pcenter.empty_desc_1")} <code>detect_enabled</code> {t("pcenter.empty_desc_2")}
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
                  {w.alive ? t("pcenter.online") : t("pcenter.offline")}
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground">
                {w.resolution} · {w.codec} · GPU:{String(w.gpu)}
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <Stat label={t("pcenter.stat_fps_capture")} value={w.fps_capture_1min ?? "—"} />
                <Stat label={t("pcenter.stat_frame_age")} value={fmtMs(w.last_frame_age_ms)} />
                <Stat label={t("pcenter.stat_produced")} value={w.frames_produced ?? 0} />
                <Stat label={t("pcenter.stat_dropped")} value={w.frames_dropped ?? 0} />
                <Stat label={t("pcenter.stat_active_plugins")} value={nPlugins} />
                <Stat label={t("pcenter.stat_reconnect")} value={w.reconnect_count ?? 0} />
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

// ───────── AI, Tracking, Workflows, Plugins, Debug (panneaux légers) ─────────
function TrackingPanel() {
  const { t } = useApp();
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
        {t("pcenter.tracking_desc")}
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th>{t("pcenter.th_camera")}</th><th>Algo</th><th>{t("pcenter.th_tracked_objects")}</th>
          </tr>
        </thead>
        <tbody>
          {trackers.map((tr) => (
            <tr key={tr.camera_id} className="border-t border-border/40">
              <td className="py-2 font-mono">{tr.camera_id}</td>
              <td>{tr.algo || "bytetrack"}</td>
              <td className="font-mono">{tr.active_tracks ?? "—"}</td>
            </tr>
          ))}
          {trackers.length === 0 && (
            <tr><td colSpan={3} className="py-6 text-center text-muted-foreground">
              {t("pcenter.no_active_tracker")}
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

function PluginsPanel() {
  const { t } = useApp();
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
            <th>Plugin</th><th>{t("pcenter.th_state")}</th><th>Interface</th>
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
  const { t } = useApp();
  return (
    <Card className="p-4" data-testid="workflows-panel">
      <div className="text-sm text-muted-foreground">
        {t("pcenter.workflows_desc_1")}{" "}
        <a href="/workflows" className="underline">Workflows</a>{t("pcenter.workflows_desc_2")}
      </div>
    </Card>
  );
}

function DebugPanel() {
  return (
    <div className="space-y-4" data-testid="debug-panel">
      {/* v3.54 · "État des conteneurs" déplacé vers Réseau → Paramètres
          réseau (demande explicite) — voir ContainerStatusPanel.jsx,
          maintenant rendu depuis NetworkConfig.jsx. */}
      <TrackingDiagnosticsPanel />
      <SshConsolePanel />
    </div>
  );
}

// v3.40 · Déplacé depuis le panneau debug app-level (Ctrl+Shift+D) — demande
// explicite : ce diagnostic (Detection FPS / Display FPS / lissage / âge
// dernière détection, par caméra) a plus sa place ici, dans Suivi des
// performances, qu'au niveau app. Même source (DiagnosticsRegistry.js) que
// le panneau app — chaque tuile de la mosaïque live enregistre un accès à
// son propre TrackInterpolator à son montage, retiré à son démontage.
function TrackingDiagnosticsPanel() {
  const { t } = useApp();
  const [snapshot, setSnapshot] = useState({});
  useEffect(() => {
    const poll = () => setSnapshot(DiagnosticsRegistry.snapshotAll());
    poll();
    const iv = setInterval(poll, 1000);
    return () => clearInterval(iv);
  }, []);
  const rows = Object.entries(snapshot);
  return (
    <Card className="p-4" data-testid="tracking-diagnostics-panel">
      <div className="text-sm font-medium mb-1">{t("pcenter.tracking_diag_title")}</div>
      <div className="text-xs text-muted-foreground mb-3">
        {t("pcenter.tracking_diag_desc")}
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground text-xs uppercase tracking-wider">
          <tr>
            <th className="pb-1">{t("pcenter.th_camera")}</th><th className="pb-1">{t("pcenter.th_detect_fps")}</th>
            <th className="pb-1">Display FPS</th><th className="pb-1">Prediction</th>
            <th className="pb-1">{t("pcenter.th_last_detection")}</th><th className="pb-1">{t("pcenter.th_tracks")}</th>
            <th className="pb-1">{t("pcenter.th_smoothing")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([camId, d]) => (
            <tr key={camId} className="border-t border-border/40 font-mono text-xs" data-testid={`tracking-diag-row-${camId}`}>
              <td className="py-1.5">{d.camName || camId}</td>
              <td className={d.detectionFps > 0 ? "text-[#00E676]" : "text-[#FF3333]"}>{d.detectionFps ?? "—"}</td>
              <td>{d.displayFps ?? "—"}</td>
              <td className={d.predictionActive ? "text-[#00E5FF]" : "text-muted-foreground"}>{d.predictionActive ? "YES" : "no"}</td>
              <td className={d.lastDetectionAgeMs != null && d.lastDetectionAgeMs > 5000 ? "text-[#FFB800]" : ""}>
                {d.lastDetectionAgeMs != null ? `${Math.round(d.lastDetectionAgeMs)}ms` : "—"}
              </td>
              <td>{d.trackedCount ?? "—"}</td>
              <td className={d.smoothingEnabled ? "text-[#00E5FF]" : "text-muted-foreground"}>{d.smoothingEnabled ? t("pcenter.value_active") : "off"}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={7} className="py-6 text-center text-muted-foreground">
              {t("pcenter.no_live_tile")}
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}
