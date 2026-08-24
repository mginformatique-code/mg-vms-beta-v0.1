/**
 * CameraCenter — Hub caméra unique v0.5.0.a
 *
 * URL : /camera-center/:cameraId?tab=overview
 *
 * Regroupe 11 onglets par caméra. Toutes les commandes physiques passent
 * par /api/devices/{id}/* (device layer v0.4.6). Les widgets sont
 * conditionnels selon capabilities — jamais de bouton pour une fonction
 * que la caméra ne supporte pas.
 *
 * Règle absolue :
 *   Ne JAMAIS deviner les capacités depuis le modèle de caméra.
 *   Toujours lire depuis GET /api/devices/{id}/capabilities.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import LivePlayer from "@/components/video/LivePlayer";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import {
  Camera, Wifi, Video, Layers, Cpu, Volume2, Sun, Bell, Move3d, Wrench,
  ScanLine, RefreshCw, AlertCircle, CircleCheck, ChevronLeft, ChevronRight,
  ArrowLeft, HardDrive, Activity,
} from "lucide-react";

const TABS = [
  { id: "overview",     label: "Overview",     icon: Camera },
  { id: "live",         label: "Live",         icon: Video },
  { id: "network",      label: "Network",      icon: Wifi },
  { id: "streams",      label: "Streams",      icon: Video },
  { id: "capabilities", label: "Capabilities", icon: Layers },
  { id: "ai",           label: "AI",           icon: Cpu },
  { id: "events",       label: "Events",       icon: Activity },
  { id: "audio",        label: "Audio",        icon: Volume2 },
  { id: "lighting",     label: "Lighting",     icon: Sun },
  { id: "alarm",        label: "Alarm",        icon: Bell },
  { id: "sdcard",       label: "Carte SD",     icon: HardDrive },
  { id: "ptz",          label: "PTZ",          icon: Move3d },
  { id: "maintenance",  label: "Maintenance",  icon: Wrench },
];

// v0.5.0.b · Bandeau santé global (GPU/CPU/RAM/VRAM/Mongo/go2rtc/Capture/Pipeline)
function HealthBanner() {
  const [h, setH] = useState({});
  useEffect(() => {
    const load = async () => {
      const [sys, cap] = await Promise.all([
        api.get("/system-health").catch(() => ({ data: {} })),
        api.get("/diagnostics/capture/stats").catch(() => ({ data: {} })),
      ]);
      setH({ ...(sys.data || {}), capture: cap.data || {} });
    };
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, []);
  const items = [
    { label: "CPU", value: h.cpu_percent != null ? `${h.cpu_percent}%` : "—" },
    { label: "RAM", value: h.ram_percent != null ? `${h.ram_percent}%` : "—" },
    { label: "GPU", value: h.gpu_percent != null ? `${h.gpu_percent}%` : "—" },
    { label: "VRAM", value: h.vram_percent != null ? `${h.vram_percent}%` : "—" },
    { label: "Mongo", value: h.mongo_ok ? "OK" : (h.mongo_ok === false ? "KO" : "—") },
    { label: "go2rtc", value: h.go2rtc_ok ? "OK" : (h.go2rtc_ok === false ? "KO" : "—") },
    { label: "Capture", value: h.capture?.cuvid_available ? "NVDEC" : (h.capture?.mode || "—") },
    { label: "Pipeline", value: h.pipeline_ok ? "OK" : "—" },
  ];
  return (
    <div className="flex flex-wrap gap-2 py-2 px-3 border-b border-border bg-secondary/30 text-xs"
         data-testid="health-banner">
      {items.map((it) => (
        <div key={it.label} className="flex gap-1 items-center">
          <span className="text-muted-foreground">{it.label}</span>
          <span className="font-mono">{it.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function CameraCenter() {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const setTab = (t) => setParams({ tab: t });
  const { caps, info, loading, error, refresh, discover } = useDeviceCapabilities(cameraId);

  // v0.5.0.b · Navigation prev/next entre caméras sans revenir à la liste
  const [allCams, setAllCams] = useState([]);
  useEffect(() => {
    api.get("/cameras").then((r) => setAllCams(r.data || [])).catch(() => setAllCams([]));
  }, []);
  const { prevId, nextId } = useMemo(() => {
    const idx = allCams.findIndex((c) => c.id === cameraId);
    if (idx < 0) return { prevId: null, nextId: null };
    return {
      prevId: idx > 0 ? allCams[idx - 1].id : null,
      nextId: idx < allCams.length - 1 ? allCams[idx + 1].id : null,
    };
  }, [allCams, cameraId]);
  const go = (id) => id && navigate(`/camera-center/${id}?tab=${tab}`);

  return (
    <div data-testid="camera-center">
      <HealthBanner />
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => navigate("/cameras")}
                    data-testid="back-to-cameras">
              <ArrowLeft className="w-4 h-4 mr-1" />Liste
            </Button>
            <Button variant="outline" size="icon" disabled={!prevId}
                    onClick={() => go(prevId)} data-testid="cam-prev">
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button variant="outline" size="icon" disabled={!nextId}
                    onClick={() => go(nextId)} data-testid="cam-next">
              <ChevronRight className="w-4 h-4" />
            </Button>
            <div>
              <h1 className="text-3xl font-bold tracking-tight" data-testid="cam-title">
                {info?.model || info?.manufacturer || cameraId}
              </h1>
              <div className="flex gap-2 items-center text-sm text-muted-foreground">
                <span className="font-mono">{cameraId}</span>
                {info?.manufacturer && <Badge variant="outline">{info.manufacturer}</Badge>}
                {info?.firmware && <span>FW {info.firmware}</span>}
                {info?.ip && <span>· {info.ip}</span>}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={refresh} data-testid="cam-refresh">
              <RefreshCw className="w-4 h-4 mr-2" />Rafraîchir
            </Button>
            <Button onClick={() => discover().then(() => toast.success("Capacités détectées"))
                                       .catch((e) => toast.error(e.response?.data?.detail?.message || "Échec probe"))}
                    data-testid="cam-discover">
              <ScanLine className="w-4 h-4 mr-2" />Détecter capacités
            </Button>
          </div>
        </div>

      {error && (
        <Card className="p-4 border-destructive/40" data-testid="cam-error">
          <div className="flex gap-2 items-start">
            <AlertCircle className="w-4 h-4 mt-1 text-destructive" />
            <div>
              <div className="font-medium">Impossible de lire les capacités</div>
              {/* v1.0-rc4.5 · error.label est un message français ciblé par code
                  (authentication_failed / device_locked / device_unreachable /
                  command_timeout / ...) — voir useDeviceCapabilities.js.
                  Fallback sur message brut si code inconnu. */}
              <div className="text-sm text-muted-foreground" data-testid="cam-error-label">
                {error.label || error.message}
              </div>
              {error.code && (
                <div className="text-[10px] mt-1 uppercase tracking-wider text-muted-foreground/70 mono">
                  code : {error.code}{error.status ? ` · HTTP ${error.status}` : ""}
                </div>
              )}
              {error.status === 404 && (
                <div className="text-xs mt-1">
                  Astuce : cliquez sur <b>Détecter capacités</b> pour lancer la probe initiale.
                </div>
              )}
              {error.code === "authentication_failed" && (
                <div className="text-xs mt-1 text-[#FFAA00]">
                  Éditez la caméra pour corriger l'identifiant/mot de passe ONVIF. Aucune nouvelle tentative n'est déclenchée automatiquement.
                </div>
              )}
              {error.code === "device_locked" && (
                <div className="text-xs mt-1 text-[#FF6666]">
                  Attendez le déverrouillage par la caméra (souvent 5-15 min) — aucune tentative automatique n'est effectuée pendant cette période.
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      <Tabs value={tab} onValueChange={setTab} className="space-y-4">
        <TabsList className="flex flex-wrap h-auto justify-start"
                  data-testid="camera-center-tabs">
          {TABS.map(({ id, label, icon: Icon }) => (
            <TabsTrigger key={id} value={id} data-testid={`cam-tab-${id}`} className="gap-2">
              <Icon className="w-4 h-4" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview"><OverviewTab info={info} caps={caps} cameraId={cameraId} /></TabsContent>
        <TabsContent value="live"><LiveTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="network"><NetworkTab info={info} /></TabsContent>
        <TabsContent value="streams"><StreamsTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="capabilities"><CapabilitiesTab caps={caps} /></TabsContent>
        <TabsContent value="ai"><AITab caps={caps} cameraId={cameraId} /></TabsContent>
        <TabsContent value="events"><EventsTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="audio"><AudioTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="lighting"><LightingTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="alarm"><AlarmTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="sdcard"><SdCardTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="ptz"><PTZTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="maintenance"><MaintenanceTab cameraId={cameraId} /></TabsContent>
      </Tabs>
      </div>
    </div>
  );
}

// ─── helpers ───
const CapField = ({ ok, label }) => (
  <div className="flex items-center gap-2 text-sm">
    {ok ? <CircleCheck className="w-4 h-4 text-green-500" />
        : <span className="w-4 h-4 rounded-full border border-muted-foreground/40 inline-block" />}
    <span className={ok ? "" : "text-muted-foreground line-through"}>{label}</span>
  </div>
);

const NotSupported = ({ what }) => (
  <Card className="p-6 text-sm text-muted-foreground" data-testid="cap-not-supported">
    Cette caméra ne supporte pas cette fonction <b>{what}</b>. Onglet masqué
    apres un <i>discover</i> est effectué (fail-safe côté capabilities).
  </Card>
);

const fmtMs = (v) => (v == null ? "—" : `${v} ms`);

const EventPanel = ({ title, items, render }) => (
  <Card className="p-3 space-y-2">
    <div className="text-xs uppercase tracking-wider text-muted-foreground">{title}</div>
    <div className="space-y-1 max-h-64 overflow-auto">
      {items.length === 0 && <div className="text-xs text-muted-foreground py-3 text-center">Aucun</div>}
      {items.map((it, i) => (
        <div key={i} className="text-xs border-b border-border/40 pb-1">{render(it)}</div>
      ))}
    </div>
  </Card>
);

// ─── Overview ─── v0.5.0.b · tableau de bord complet
function OverviewTab({ info, caps, cameraId }) {
  const [rt, setRt] = useState({});
  useEffect(() => {
    const load = async () => {
      const [cap, pipe, cam] = await Promise.all([
        api.get("/diagnostics/capture/stats").catch(() => ({ data: {} })),
        api.get("/diagnostics/pipeline-v2/stats").catch(() => ({ data: {} })),
        api.get(`/cameras/${cameraId}`).catch(() => ({ data: {} })),
      ]);
      const w = (cap.data.workers || {})[cameraId] || {};
      const p = ((pipe.data.per_camera || {})[cameraId]) || {};
      setRt({ capture: w, pipeline: p, cam: cam.data || {} });
    };
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [cameraId]);
  const w = rt.capture || {};
  const cam = rt.cam || {};
  const aiActive = !!(cam.enabled_plugins && cam.enabled_plugins.length);
  return (
    <div className="grid gap-3 md:grid-cols-3" data-testid="cam-overview">
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">Identité</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Nom</div><div className="font-mono truncate">{cam.name || "—"}</div>
          <div>État</div><div>{w.alive ? <Badge>en ligne</Badge> : <Badge variant="destructive">hors ligne</Badge>}</div>
          <div>Driver</div><div className="font-mono">{cam.driver || "onvif"}</div>
          <div>Fabricant</div><div className="font-mono">{info?.manufacturer || "—"}</div>
          <div>Modèle</div><div className="font-mono">{info?.model || "—"}</div>
          <div>Firmware</div><div className="font-mono">{info?.firmware || "—"}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">Vidéo · Capture</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>RTSP</div><div className="font-mono truncate text-xs">{cam.rtsp_url ? "configuré" : "—"}</div>
          <div>Codec</div><div className="font-mono">{w.codec || "—"}</div>
          <div>Résolution</div><div className="font-mono">{w.resolution || "—"}</div>
          <div>FPS capture</div><div className="font-mono">{w.fps_capture_1min ?? "—"}</div>
          <div>Frames dropped</div><div className="font-mono">{w.frames_dropped ?? 0}</div>
          <div>Warmup</div><div className="font-mono">{fmtMs(w.warmup_ms)}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">IA · ANPR · Stockage</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>IA active</div>
          <div>{aiActive ? <Badge>ON</Badge> : <Badge variant="secondary">OFF</Badge>}</div>
          <div>ANPR</div>
          <div>{(cam.enabled_plugins || []).includes("fast-alpr") ? <Badge>ON</Badge> : <Badge variant="secondary">OFF</Badge>}</div>
          <div>Plugins actifs</div><div className="font-mono">{(cam.enabled_plugins || []).length}</div>
          <div>Enregistrement</div><div>{cam.record_enabled ? "actif" : "inactif"}</div>
          <div>Batterie</div><div className="font-mono">—</div>
          <div>Temp°</div><div className="font-mono">—</div>
        </div>
      </Card>
    </div>
  );
}

function LiveTab({ cameraId }) {
  // video-pipeline-v2 · UN SEUL choix de pipeline par caméra :
  //   ○ Direct RTSP  ○ MJPEG  ○ MediaMTX
  // + bandeau statut (Pipeline / État / FPS / latence) via /video-status.
  const [cam, setCam] = React.useState(null);
  const [vs, setVs] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    api.get(`/cameras/${cameraId}`).then((r) => { if (alive) setCam(r.data); }).catch(() => {});
    const loadVs = () => api.get(`/cameras/${cameraId}/video-status`)
      .then((r) => { if (alive) setVs(r.data); }).catch(() => { if (alive) setVs(null); });
    loadVs();
    const t = setInterval(loadVs, 10000);
    return () => { alive = false; clearInterval(t); };
  }, [cameraId, reloadKey]);

  // video-engine-v3 · UN SEUL moteur vidéo, plus de sélecteur pipeline.
  const stateColor = vs?.status === "online" ? "text-[#00E676]" : "text-[#FF3333]";
  return (
    <Card className="p-3 space-y-2" data-testid="cam-live">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Moteur vidéo</div>
        <div className="text-[10px] mono uppercase tracking-wider px-2.5 py-1 border border-[#00E5FF]/60 bg-[#00E5FF]/15 text-[#00E5FF]"
              data-testid="video-engine-badge">WEBRTC → MJPEG (auto)</div>
      </div>
      <div className="flex items-center gap-3 text-[10px] mono border border-border px-2 py-1" data-testid="pipeline-status-band">
        <span className={stateColor} data-testid="pipeline-status-state">
          État : <b>{vs ? (vs.status === "online" ? "CONNECTÉ" : (vs.status || "?").toUpperCase()) : "…"}</b>
        </span>
        {vs?.fps != null && <span>FPS : <b>{vs.fps}</b></span>}
        {vs?.width != null && vs?.height != null && <span>{vs.width}×{vs.height}</span>}
        {vs?.codec && <span className="text-muted-foreground">{String(vs.codec).toUpperCase()}</span>}
        {vs?.viewers != null && <span>Viewers : <b>{vs.viewers}</b></span>}
        {vs?.last_error && <span className="text-[#FF3333] truncate max-w-[280px]" title={vs.last_error} data-testid="pipeline-status-error">{vs.last_error}</span>}
      </div>
      <div className="relative aspect-video bg-black">
        {cam && (
          <>
            <LivePlayer key={`${cameraId}-${reloadKey}`} camera={cam} hd={true}
                        className="w-full h-full" dataTestId="center-player" />
            {/* v3.6 · Overlay pied de visualisation — lumière/IR/sirène pilotées
                par les capacités réelles de la caméra (device layer), peu
                importe le constructeur. Voir CameraControlOverlay.jsx. */}
            <CameraControlOverlay cam={cam} footer />
          </>
        )}
      </div>
    </Card>
  );
}

function NetworkTab({ info }) {
  return (
    <Card className="p-4 space-y-1" data-testid="cam-network">
      <div className="grid grid-cols-2 gap-1 text-sm">
        <div>IP</div><div className="font-mono">{info?.ip || "—"}</div>
        <div>MAC</div><div className="font-mono">{info?.mac || "—"}</div>
        <div>Hardware</div><div className="font-mono">{info?.hardware || "—"}</div>
      </div>
    </Card>
  );
}

function StreamsTab({ cameraId }) {
  const [streams, setStreams] = useState([]);
  useEffect(() => {
    api.get(`/devices/${cameraId}/streams`).then((r) => setStreams(r.data || []))
       .catch(() => setStreams([]));
  }, [cameraId]);
  return (
    <Card className="p-4" data-testid="cam-streams">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr><th>Nom</th><th>Résolution</th><th>FPS</th><th>Codec</th><th>URL</th></tr>
        </thead>
        <tbody>
          {streams.map((s, i) => (
            <tr key={i} className="border-t border-border/40">
              <td className="py-2 font-mono">{s.name}</td>
              <td>{s.resolution?.join("×")}</td>
              <td>{s.fps || "—"}</td>
              <td>{s.codec}</td>
              <td className="font-mono text-xs truncate max-w-md">{s.url}</td>
            </tr>
          ))}
          {streams.length === 0 && (
            <tr><td colSpan={5} className="py-6 text-center text-muted-foreground">
              Aucun stream déclaré. Cliquer sur <b>Détecter capacités</b>.
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

// v0.5.0.b · Capabilities catégorisées (jamais du JSON brut)
function CapabilitiesTab({ caps }) {
  if (!caps) return <Card className="p-6 text-sm">Capabilités non détectées. Lancez un discover.</Card>;
  const groups = [
    { title: "VIDEO", fields: [
      { key: "onvif", label: "RTSP (ONVIF)" },
      { key: "isapi", label: "ISAPI" },
      { key: "cgi", label: "CGI" },
      { key: "reolink_api", label: "Reolink API" },
    ]},
    { title: "PTZ", fields: [
      { key: "ptz", label: "PTZ" },
      { key: "zoom", label: "Zoom" },
      { key: "focus", label: "Focus" },
    ]},
    { title: "AUDIO", fields: [
      { key: "audio_input", label: "Micro" },
      { key: "audio_output", label: "Speaker" },
      { key: "two_way_audio", label: "Talk-back" },
    ]},
    { title: "LUMIÈRE", fields: [
      { key: "spotlight", label: "Spotlight" },
      { key: "white_light", label: "White light" },
      { key: "ir_control", label: "IR" },
      { key: "ir_cut_filter", label: "IR cut filter" },
    ]},
    { title: "ALARME", fields: [
      { key: "siren", label: "Sirène" },
      { key: "alarm_output", label: "Relais alarme" },
    ]},
    { title: "CAPTEURS", fields: [
      { key: "pir_sensor", label: "PIR" },
      { key: "battery", label: "Batterie" },
    ]},
    { title: "IA EMBARQUÉE", fields: [{ key: "onboard_ai", label: "Détection embarquée" }]},
  ];
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="cam-capabilities">
      {groups.map((g) => (
        <Card key={g.title} className="p-4 space-y-2">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">{g.title}</div>
          {g.fields.map((f) => (
            <div key={f.key} className="flex items-center justify-between text-sm">
              <span className={caps[f.key] ? "" : "text-muted-foreground"}>{f.label}</span>
              <span className={caps[f.key] ? "text-green-500 font-mono" : "text-muted-foreground font-mono"}>
                {caps[f.key] ? "✓" : "✗"}
              </span>
            </div>
          ))}
        </Card>
      ))}
      {caps.onboard_ai_features?.length > 0 && (
        <Card className="p-4 space-y-1 md:col-span-2 xl:col-span-3">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Features IA embarquées</div>
          <div className="flex flex-wrap gap-1 pt-1">
            {caps.onboard_ai_features.map((f) => <Badge key={f} variant="secondary">{f}</Badge>)}
          </div>
        </Card>
      )}
    </div>
  );
}

// v0.5.0.b · AI enrichi (état plugins + latence inférence live)
function AITab({ caps, cameraId }) {
  const [ai, setAi] = useState({});
  useEffect(() => {
    const load = async () => {
      const [cam, insp] = await Promise.all([
        api.get(`/cameras/${cameraId}`).catch(() => ({ data: {} })),
        api.get("/diagnostics/pipeline-inspector").catch(() => ({ data: {} })),
      ]);
      const stages = ((insp.data.per_camera || {})[cameraId]) || {};
      setAi({ cam: cam.data || {}, stages });
    };
    load();
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, [cameraId]);
  const plugins = ai.cam?.enabled_plugins || [];
  const stages = ai.stages || {};
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="cam-ai">
      <Card className="p-4 space-y-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Pipeline actif</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Détection</div><div className="font-mono">YOLO11</div>
          <div>Tracking</div><div className="font-mono">{ai.cam?.tracker_algo || "ByteTrack"}</div>
          <div>ANPR</div>
          <div>{plugins.includes("fast-alpr") ? <Badge>FastALPR</Badge> : <Badge variant="secondary">OFF</Badge>}</div>
          <div>IA embarquée</div>
          <div>{caps?.onboard_ai ? <Badge variant="secondary">dispo</Badge> : "—"}</div>
          <div>Plugins actifs</div><div className="font-mono">{plugins.length}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Latences (dernière frame)</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Decode</div><div className="font-mono">{fmtMs(stages.decode)}</div>
          <div>YOLO</div><div className="font-mono">{fmtMs(stages.detection)}</div>
          <div>Tracking</div><div className="font-mono">{fmtMs(stages.tracking)}</div>
          <div>ROI</div><div className="font-mono">{fmtMs(stages.roi)}</div>
          <div>ANPR</div><div className="font-mono">{fmtMs(stages.anpr)}</div>
          <div>Total</div><div className="font-mono">{fmtMs(stages.total)}</div>
        </div>
      </Card>
    </div>
  );
}

// v0.5.0.b · Events par caméra (plaques + alertes + erreurs)
function EventsTab({ cameraId }) {
  const [ev, setEv] = useState({ plates: [], alerts: [], errors: [] });
  useEffect(() => {
    const load = async () => {
      const [plates, alerts] = await Promise.all([
        api.get(`/plates?camera_id=${cameraId}&limit=20`).catch(() => ({ data: [] })),
        api.get(`/alerts?camera_id=${cameraId}&limit=20`).catch(() => ({ data: [] })),
      ]);
      setEv({
        plates: (plates.data || []).slice(0, 20),
        alerts: (alerts.data || []).slice(0, 20),
        errors: [],
      });
    };
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [cameraId]);
  return (
    <div className="grid gap-3 md:grid-cols-3" data-testid="cam-events">
      <EventPanel title="Dernières plaques" items={ev.plates}
             render={(p) => (
               <div className="flex justify-between">
                 <span className="font-mono">{p.plate || "—"}</span>
                 <span className="text-muted-foreground">{p.confidence != null ? `${Math.round(p.confidence * 100)}%` : ""}</span>
               </div>
             )} />
      <EventPanel title="Dernières alertes" items={ev.alerts}
             render={(a) => (
               <div>
                 <div className="font-medium">{a.title || a.type || "Alerte"}</div>
                 <div className="text-muted-foreground text-[10px]">{a.created_at?.slice(0, 19)?.replace("T", " ")}</div>
               </div>
             )} />
      <EventPanel title="Dernières erreurs" items={ev.errors}
             render={(e) => <div>{e.message || "—"}</div>} />
    </div>
  );
}

// ─── Audio (conditionnel) ───
function AudioTab({ cameraId, caps }) {
  if (!caps?.audio_input && !caps?.audio_output) return <NotSupported what="Audio" />;
  const start = () => api.post(`/devices/${cameraId}/audio/start`).then(() => toast.success("Audio démarré"))
                          .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const stop = () => api.post(`/devices/${cameraId}/audio/stop`).then(() => toast.success("Audio arrêté"))
                         .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  return (
    <Card className="p-4 space-y-2" data-testid="cam-audio">
      <div className="text-sm text-muted-foreground">
        {caps.two_way_audio ? "Talk-back disponible" : "Audio one-way"}
      </div>
      <div className="flex gap-2">
        {caps.audio_output && (
          <>
            <Button onClick={start} data-testid="audio-start">Démarrer</Button>
            <Button variant="outline" onClick={stop} data-testid="audio-stop">Arrêter</Button>
          </>
        )}
      </div>
    </Card>
  );
}

// ─── Lighting (conditionnel) ───
function LightingTab({ cameraId, caps }) {
  const supported = caps?.spotlight || caps?.white_light;
  const [brightness, setBrightness] = useState(80);
  if (!supported) return <NotSupported what="Lumière (spotlight / white light)" />;
  const toggle = (enabled) =>
    api.post(`/devices/${cameraId}/light`, { enabled, brightness, mode: "on" })
       .then(() => toast.success(enabled ? "Lumière ON" : "Lumière OFF"))
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  return (
    <Card className="p-4 space-y-3" data-testid="cam-lighting">
      <Label>Brightness ({brightness}%)</Label>
      <Input type="range" min={0} max={100} value={brightness}
             onChange={(e) => setBrightness(Number(e.target.value))}
             data-testid="light-brightness" />
      <div className="flex gap-2">
        <Button onClick={() => toggle(true)} data-testid="light-on">Allumer</Button>
        <Button variant="outline" onClick={() => toggle(false)} data-testid="light-off">Éteindre</Button>
      </div>
    </Card>
  );
}

// ─── Alarm (Siren) ───
function AlarmTab({ cameraId, caps }) {
  const [duration, setDuration] = useState(10);
  if (!caps?.siren) return <NotSupported what="Sirène" />;
  const trigger = () =>
    api.post(`/devices/${cameraId}/siren`, { enabled: true, duration })
       .then(() => toast.success(`Sirène déclenchée (${duration}s)`))
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const stop = () =>
    api.post(`/devices/${cameraId}/siren`, { enabled: false })
       .then(() => toast.success("Sirène arrêtée"))
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  return (
    <Card className="p-4 space-y-3" data-testid="cam-alarm">
      <Label>Durée (s)</Label>
      <Input type="number" min={1} max={600} value={duration}
             onChange={(e) => setDuration(Number(e.target.value))}
             data-testid="siren-duration" />
      <div className="flex gap-2">
        <Button onClick={trigger} data-testid="siren-trigger">Déclencher</Button>
        <Button variant="outline" onClick={stop} data-testid="siren-stop">Arrêter</Button>
      </div>
    </Card>
  );
}

// ─── Carte SD (v3.6) — vendor-agnostic, pilotée par caps.sdcard ───
// Lecture via /api/devices/{id}/recordings/stream (proxy ffmpeg côté
// backend) — jamais d'URL caméra brute (avec identifiants) exposée ici.
function SdCardTab({ cameraId, caps }) {
  const [storage, setStorage] = useState(null);
  const [recordings, setRecordings] = useState(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(null);
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [start, setStart] = useState(toLocalInput(new Date(Date.now() - 24 * 3600 * 1000)));
  const [end, setEnd] = useState(toLocalInput(new Date()));

  useEffect(() => {
    if (!caps?.sdcard) return;
    let alive = true;
    api.get(`/devices/${cameraId}/storage`)
       .then((r) => { if (alive) setStorage(r.data?.storage || []); })
       .catch(() => { if (alive) setStorage([]); });
    return () => { alive = false; };
  }, [cameraId, caps?.sdcard]);

  if (!caps?.sdcard) return <NotSupported what="Carte SD / stockage local" />;

  const search = async () => {
    setLoading(true); setRecordings(null); setPlaying(null);
    try {
      const { data } = await api.get(`/devices/${cameraId}/recordings`, {
        params: { start: new Date(start).toISOString(), end: new Date(end).toISOString() },
      });
      setRecordings(data.recordings || []);
      if (!(data.recordings || []).length) toast.info("Aucun enregistrement sur cette période");
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Recherche impossible");
    } finally { setLoading(false); }
  };

  const playUrl = (fileName) => {
    const token = localStorage.getItem("mg_token");
    return `${process.env.REACT_APP_BACKEND_URL}/api/devices/${cameraId}/recordings/stream`
      + `?file=${encodeURIComponent(fileName)}&token=${encodeURIComponent(token || "")}`;
  };

  return (
    <Card className="p-4 space-y-3" data-testid="cam-sdcard">
      {storage && storage.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="sdcard-storage">
          {storage.map((s, i) => (
            <div key={i} className="border border-border px-2 py-1">
              <span className="text-muted-foreground mr-1.5">{s.type || "SD"} #{s.index}</span>
              <span className={s.available ? "text-[#00E676]" : "text-[#FF3333]"}>
                {s.available ? "OK" : "absente/erreur"}
              </span>
              {s.available && s.free_percent != null && (
                <span className="ml-2 font-mono">{s.free_percent}% libre</span>
              )}
            </div>
          ))}
        </div>
      )}
      {storage && storage.length === 0 && (
        <div className="text-xs text-muted-foreground">Aucun support de stockage détecté sur cette caméra.</div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label>Depuis</Label>
          <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} data-testid="sdcard-start" />
        </div>
        <div>
          <Label>Jusqu&apos;à</Label>
          <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="sdcard-end" />
        </div>
        <Button onClick={search} disabled={loading} data-testid="sdcard-search">
          {loading ? "Recherche…" : "Rechercher"}
        </Button>
      </div>

      {playing && (
        <div className="aspect-video bg-black">
          <video key={playing} src={playUrl(playing)} controls autoPlay
                 className="w-full h-full" data-testid="sdcard-player" />
        </div>
      )}

      {recordings && recordings.length > 0 && (
        <div className="border border-border divide-y divide-border max-h-96 overflow-y-auto" data-testid="sdcard-list">
          {recordings.map((r, i) => (
            <div key={i}
                 className="flex items-center justify-between px-3 py-2 text-xs hover:bg-secondary/50 cursor-pointer"
                 onClick={() => setPlaying(r.file_name)} data-testid="sdcard-row">
              <div>
                <div className="font-mono">{r.start_time ? new Date(r.start_time).toLocaleString("fr-FR") : "—"}</div>
                {r.end_time && (
                  <div className="text-muted-foreground">→ {new Date(r.end_time).toLocaleTimeString("fr-FR")}</div>
                )}
              </div>
              <div className="flex items-center gap-2 text-muted-foreground">
                {r.duration_s != null && <span>{Math.round(r.duration_s)}s</span>}
                {r.size_bytes != null && <span>{(r.size_bytes / 1024 / 1024).toFixed(1)} Mo</span>}
                <Button size="sm" variant="outline" data-testid="sdcard-play-btn"
                        onClick={(e) => { e.stopPropagation(); setPlaying(r.file_name); }}>
                  Lire
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── PTZ ───
function PTZTab({ cameraId, caps }) {
  if (!caps?.ptz) return <NotSupported what="PTZ" />;
  const move = (direction) =>
    api.post(`/devices/${cameraId}/ptz/move`, { direction, speed: 0.5 })
       .then(() => {})
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const zoom = (value) =>
    api.post(`/devices/${cameraId}/ptz/zoom`, { value })
       .then(() => {})
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const preset = (id) =>
    api.post(`/devices/${cameraId}/ptz/preset`, { id })
       .then(() => toast.success(`Preset ${id}`))
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  return (
    <Card className="p-4 space-y-4" data-testid="cam-ptz">
      <div>
        <div className="text-sm text-muted-foreground mb-2">Directions</div>
        <div className="grid grid-cols-3 gap-1 w-48">
          <Button variant="outline" onClick={() => move("upleft")}>↖</Button>
          <Button variant="outline" onClick={() => move("up")} data-testid="ptz-up">↑</Button>
          <Button variant="outline" onClick={() => move("upright")}>↗</Button>
          <Button variant="outline" onClick={() => move("left")} data-testid="ptz-left">←</Button>
          <Button variant="outline" onClick={() => move("stop")} data-testid="ptz-stop">■</Button>
          <Button variant="outline" onClick={() => move("right")} data-testid="ptz-right">→</Button>
          <Button variant="outline" onClick={() => move("downleft")}>↙</Button>
          <Button variant="outline" onClick={() => move("down")} data-testid="ptz-down">↓</Button>
          <Button variant="outline" onClick={() => move("downright")}>↘</Button>
        </div>
      </div>
      {caps.zoom && (
        <div>
          <div className="text-sm text-muted-foreground mb-2">Zoom</div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => zoom(-0.5)} data-testid="ptz-zoom-out">−</Button>
            <Button variant="outline" onClick={() => zoom(0.5)} data-testid="ptz-zoom-in">+</Button>
          </div>
        </div>
      )}
      <div>
        <div className="text-sm text-muted-foreground mb-2">Presets</div>
        <div className="flex gap-2 flex-wrap">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <Button key={n} variant="outline" size="sm" onClick={() => preset(n)}
                    data-testid={`ptz-preset-${n}`}>{n}</Button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function MaintenanceTab({ cameraId }) {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    api.get(`/devices/${cameraId}/status`).then((r) => setStatus(r.data))
       .catch(() => setStatus(null));
  }, [cameraId]);
  if (!status) return <Card className="p-6 text-sm">Aucune donnée de statut.</Card>;
  return (
    <Card className="p-4 space-y-1" data-testid="cam-maintenance">
      <div className="grid grid-cols-2 gap-1 text-sm">
        <div>En ligne</div><div>{status.online ? "Oui" : "Non"}</div>
        <div>Batterie</div><div>{status.battery_percent ?? "—"}%</div>
        <div>SD card</div><div>{status.sd_card_status || "—"}</div>
        <div>SD usage</div><div>{status.sd_card_used_percent ?? "—"}%</div>
        <div>Uptime</div><div>{status.uptime_s ?? "—"} s</div>
      </div>
    </Card>
  );
}
