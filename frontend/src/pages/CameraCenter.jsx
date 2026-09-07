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
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import LivePlayer from "@/components/video/LivePlayer";
import RetailTrackingOverlay from "@/components/video/RetailTrackingOverlay";
import CameraControlOverlay from "@/pages/CameraControlOverlay";
import { AiDetectionSettings } from "@/pages/PluginPage";
import SpeedCalibrationEditor from "@/components/SpeedCalibrationEditor";
import {
  Camera, Wifi, Video, Layers, Cpu, Volume2, Sun, Bell, Move3d, Wrench,
  ScanLine, RefreshCw, AlertCircle, CircleCheck, ChevronLeft, ChevronRight,
  ArrowLeft, HardDrive, Activity, Download, Type, Loader2, Clock,
  Plus, Trash2, ArrowUp, ArrowDown, MapPin,
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
  { id: "osd",          label: "Incrustation", icon: Type },
  { id: "datetime",     label: "Date et heure", icon: Clock },
  { id: "alarm",        label: "Alarm",        icon: Bell },
  { id: "sdcard",       label: "Carte SD",     icon: HardDrive },
  { id: "ptz",          label: "PTZ",          icon: Move3d },
  { id: "maintenance",  label: "Maintenance",  icon: Wrench },
];

// v0.5.0.b · Bandeau santé global (GPU/CPU/RAM/VRAM/Mongo/go2rtc/Capture/Pipeline)
export default function CameraCenter() {
  const { t } = useApp();
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
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => navigate("/camera-center")}
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
              <div className="font-medium">{t("camc.caps_read_fail")}</div>
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
                  Astuce : cliquez sur <b>{t("camc.detect_caps")}</b> pour lancer la probe initiale.
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
        <TabsContent value="network"><NetworkTab info={info} cameraId={cameraId} /></TabsContent>
        <TabsContent value="streams"><StreamsTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="capabilities"><CapabilitiesTab caps={caps} /></TabsContent>
        <TabsContent value="ai"><AITab caps={caps} cameraId={cameraId} /></TabsContent>
        <TabsContent value="events"><EventsTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="audio"><AudioTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="lighting"><LightingTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="osd"><OsdTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="datetime"><DateTimeTab cameraId={cameraId} /></TabsContent>
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
  const { t } = useApp();
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
        <div className="text-sm text-muted-foreground">{t("camc.identity")}</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Nom</div><div className="font-mono truncate">{cam.name || "—"}</div>
          <div>{t("camc.state")}</div><div>{w.alive ? <Badge>en ligne</Badge> : <Badge variant="destructive">hors ligne</Badge>}</div>
          <div>Driver</div><div className="font-mono">{cam.driver || "onvif"}</div>
          <div>Fabricant</div><div className="font-mono">{info?.manufacturer || "—"}</div>
          <div>{t("camc.model")}</div><div className="font-mono">{info?.model || "—"}</div>
          <div>Firmware</div><div className="font-mono">{info?.firmware || "—"}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">{t("camc.video_capture")}</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>RTSP</div><div className="font-mono truncate text-xs">{cam.rtsp_url ? "configuré" : "—"}</div>
          <div>Codec</div><div className="font-mono">{w.codec || "—"}</div>
          <div>{t("cam.resolution")}</div><div className="font-mono">{w.resolution || "—"}</div>
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
  const { t, aiDetections } = useApp();
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
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("camc.video_engine")}</div>
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
            {/* Tracking anti-vol — uniquement si le plugin retail est actif sur
                cette caméra (plan Phase 1, léger : réutilise le flux WS
                ai_detections déjà diffusé, pas de requête supplémentaire). */}
            {(cam.enabled_plugins || []).includes("retail-suspicious-behavior") && (
              <RetailTrackingOverlay
                boxes={aiDetections[cameraId]?.boxes}
                retail={aiDetections[cameraId]?.retail}
              />
            )}
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

function NetworkTab({ info, cameraId }) {
  // v3.7 · Détails réseau constructeur (ports, protocoles, UID, WiFi) —
  // /api/devices/{id}/network. 501 si le driver ne l'implémente pas :
  // on garde alors uniquement les infos de base ci-dessous.
  const [net, setNet] = useState(null);
  const [unsupported, setUnsupported] = useState(false);
  useEffect(() => {
    let alive = true;
    api.get(`/devices/${cameraId}/network`)
       .then((r) => { if (alive) setNet(r.data || null); })
       .catch(() => { if (alive) setUnsupported(true); });
    return () => { alive = false; };
  }, [cameraId]);

  const yesNo = (v) => (v == null ? "—" : v ? "activé" : "désactivé");
  const color = (v) => (v == null ? "" : v ? "text-[#00E676]" : "text-muted-foreground");

  return (
    <Card className="p-4 space-y-4" data-testid="cam-network">
      <div className="grid grid-cols-2 gap-1 text-sm">
        <div>IP</div><div className="font-mono">{info?.ip || "—"}</div>
        <div>MAC</div><div className="font-mono">{net?.mac || info?.mac || "—"}</div>
        <div>Hardware</div><div className="font-mono">{info?.hardware || "—"}</div>
        {net?.uid && (<><div>UID</div><div className="font-mono">{net.uid}</div></>)}
        {net?.wifi != null && (
          <>
            <div>WiFi</div>
            <div className="font-mono">
              {net.wifi ? `connecté${net.wifi_signal != null ? ` (${net.wifi_signal}%)` : ""}` : "filaire (Ethernet)"}
            </div>
          </>
        )}
      </div>

      {net?.ports && Object.keys(net.ports).length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Ports</div>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(net.ports).map(([name, port]) => (
              <div key={name} className="border border-border px-2 py-1">
                <span className="text-muted-foreground mr-1.5">{name}</span>
                <span className="font-mono">{port || "—"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {net?.protocols && Object.keys(net.protocols).length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Protocoles</div>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(net.protocols).map(([name, enabled]) => (
              <div key={name} className="border border-border px-2 py-1">
                <span className="text-muted-foreground mr-1.5">{name}</span>
                <span className={`font-mono ${color(enabled)}`}>{yesNo(enabled)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {unsupported && (
        <div className="text-xs text-muted-foreground">
          Le driver de cette caméra ne remonte pas de paramètres réseau détaillés.
        </div>
      )}
    </Card>
  );
}

function StreamsTab({ cameraId }) {
  const { t } = useApp();
  const [streams, setStreams] = useState([]);
  useEffect(() => {
    api.get(`/devices/${cameraId}/streams`).then((r) => setStreams(r.data || []))
       .catch(() => setStreams([]));
  }, [cameraId]);
  return (
    <Card className="p-4" data-testid="cam-streams">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr><th>Nom</th><th>{t("cam.resolution")}</th><th>FPS</th><th>Codec</th><th>URL</th></tr>
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
              Aucun stream déclaré. Cliquer sur <b>{t("camc.detect_caps")}</b>.
            </td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

// v0.5.0.b · Capabilities catégorisées (jamais du JSON brut)
function CapabilitiesTab({ caps }) {
  const { t } = useApp();
  if (!caps) return <Card className="p-6 text-sm">{t("camc.caps_none")}</Card>;
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
          <div className="text-xs uppercase tracking-wider text-muted-foreground">{t("camc.ai_features")}</div>
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
  const { t } = useApp();
  const [ai, setAi] = useState({});
  const [tuning, setTuning] = useState(null);
  const [tuningRunning, setTuningRunning] = useState(false);
  // v3.27 · Auto-suspension qualité ANPR (v0.4.2, déjà en place côté
  // pipeline — "pas de plaque > fausse plaque") — jusqu'ici sans AUCUNE
  // trace côté interface : rien n'expliquait pourquoi les plaques
  // s'arrêtaient net à la tombée de la nuit sur une caméra non spécialisée.
  const [anprQuality, setAnprQuality] = useState(null);
  const [resettingAnprQuality, setResettingAnprQuality] = useState(false);
  // v3.37 · Vitesse calibrée (homographie) — voir set_speed_calibration
  const [showSpeedCal, setShowSpeedCal] = useState(false);
  const [clearingSpeedCal, setClearingSpeedCal] = useState(false);
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
  useEffect(() => {
    api.get(`/cameras/${cameraId}/anpr-tuning/history`).then((r) => setTuning(r.data)).catch(() => setTuning(null));
  }, [cameraId]);
  const loadAnprQuality = () => {
    api.get("/diagnostics/anpr-quality").then((r) => setAnprQuality(r.data)).catch(() => setAnprQuality(null));
  };
  useEffect(() => {
    loadAnprQuality();
    const iv = setInterval(loadAnprQuality, 15000);
    return () => clearInterval(iv);
  }, [cameraId]);
  const resetAnprQuality = async () => {
    setResettingAnprQuality(true);
    try {
      await api.post("/diagnostics/anpr-quality/reset", null, { params: { camera_id: cameraId } });
      loadAnprQuality();
      toast.success("Suspension ANPR réinitialisée — reprise immédiate");
    } catch (e) { toast.error("Échec de la réinitialisation"); }
    finally { setResettingAnprQuality(false); }
  };
  const runTuningNow = async () => {
    setTuningRunning(true);
    try {
      await api.post(`/cameras/${cameraId}/anpr-tuning/run`);
      const r = await api.get(`/cameras/${cameraId}/anpr-tuning/history`);
      setTuning(r.data);
      toast.success("Seuil ANPR réévalué");
    } catch (e) { toast.error(e.response?.data?.detail?.message || "Échec — pas assez de lectures récentes ?"); }
    finally { setTuningRunning(false); }
  };
  const plugins = ai.cam?.enabled_plugins || [];
  const stages = ai.stages || {};
  const speedCal = ai.cam?.pipeline_config?.ai?.speed_calibration;
  const clearSpeedCal = async () => {
    setClearingSpeedCal(true);
    try {
      await api.delete(`/cameras/${cameraId}/speed-calibration`);
      setAi((prev) => ({
        ...prev,
        cam: { ...prev.cam, pipeline_config: { ...prev.cam.pipeline_config, ai: { ...(prev.cam.pipeline_config?.ai || {}), speed_calibration: undefined } } },
      }));
      toast.success("Calibration vitesse supprimée");
    } catch (e) { toast.error("Échec de la suppression"); }
    finally { setClearingSpeedCal(false); }
  };
  return (
    <div className="space-y-3">
      {/* v3.27 · Réglage GLOBAL (toutes caméras/classes) — jusqu'ici visible
          seulement sous Plugins → IA détection, peu découvrable pour un
          réglage qui affecte directement la qualité des détections dont on
          discute justement ici. Rendu plus visible, demande explicite. */}
      <div data-testid="cam-ai-global-settings">
        <div className="text-xs uppercase tracking-wider text-[#FFB800] mb-1">
          Réglage global — s'applique à TOUTES les caméras et TOUTES les classes (pas seulement celle-ci)
        </div>
        <AiDetectionSettings />
      </div>
    <div className="grid gap-3 md:grid-cols-2" data-testid="cam-ai">
      <Card className="p-4 space-y-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Pipeline actif</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>{t("camc.detection")}</div><div className="font-mono">YOLO11</div>
          <div>Tracking</div><div className="font-mono">{ai.cam?.tracker_algo || "ByteTrack"}</div>
          <div>ANPR</div>
          <div>{plugins.includes("fast-alpr") ? <Badge>FastALPR</Badge> : <Badge variant="secondary">OFF</Badge>}</div>
          <div>{t("camc.onboard_ai")}</div>
          <div>{caps?.onboard_ai ? <Badge variant="secondary">dispo</Badge> : "—"}</div>
          <div>Plugins actifs</div><div className="font-mono">{plugins.length}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">{t("camc.latencies")}</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Decode</div><div className="font-mono">{fmtMs(stages.decode)}</div>
          <div>YOLO</div><div className="font-mono">{fmtMs(stages.detection)}</div>
          <div>Tracking</div><div className="font-mono">{fmtMs(stages.tracking)}</div>
          <div>ROI</div><div className="font-mono">{fmtMs(stages.roi)}</div>
          <div>ANPR</div><div className="font-mono">{fmtMs(stages.anpr)}</div>
          <div>Total</div><div className="font-mono">{fmtMs(stages.total)}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-2 md:col-span-2" data-testid="cam-speed-calibration">
        <div className="flex items-center justify-between">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            Vitesse calibrée (homographie)
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setShowSpeedCal(true)} data-testid="speed-cal-open">
              {speedCal?.enabled ? "Recalibrer" : "Calibrer"}
            </Button>
            {speedCal?.enabled && (
              <Button size="sm" variant="outline" onClick={clearSpeedCal} disabled={clearingSpeedCal} data-testid="speed-cal-clear">
                {clearingSpeedCal ? "…" : "Supprimer"}
              </Button>
            )}
          </div>
        </div>
        {speedCal?.enabled ? (
          <div className="text-sm">
            Zone calibrée : {speedCal.width_m}m × {speedCal.length_m}m — chaque véhicule suivi affiche sa vitesse
            réelle (km/h) sur le mur vidéo, à l'arrêt comme en mouvement.
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Non calibrée — tracez un rectangle de dimensions réelles connues au sol pour afficher la vitesse (km/h)
            de chaque véhicule suivi par cette caméra.
          </p>
        )}
      </Card>
      {showSpeedCal && (
        <SpeedCalibrationEditor
          camera={ai.cam}
          existing={speedCal}
          onClose={() => setShowSpeedCal(false)}
          onSaved={(cal) => {
            setShowSpeedCal(false);
            setAi((prev) => ({
              ...prev,
              cam: { ...prev.cam, pipeline_config: { ...prev.cam.pipeline_config, ai: { ...(prev.cam.pipeline_config?.ai || {}), speed_calibration: cal } } },
            }));
          }}
        />
      )}
      {tuning && (
        <Card className="p-4 space-y-2 md:col-span-2" data-testid="cam-anpr-tuning">
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Seuil de confiance ANPR (auto-réglé par IA)
            </div>
            <Button size="sm" variant="outline" onClick={runTuningNow} disabled={tuningRunning} data-testid="anpr-tuning-run">
              {tuningRunning ? "Analyse…" : "Réévaluer maintenant"}
            </Button>
          </div>
          <div className="text-2xl font-mono">{Math.round(tuning.current_min_confidence * 100)}%</div>
          <p className="text-xs text-muted-foreground">
            Les lectures de plaque sous ce seuil sont ignorées (pas stockées). Réévalué automatiquement une fois par semaine
            à partir des 14 derniers jours de lectures de cette caméra.
          </p>
          {tuning.history?.length > 0 && (
            <div className="text-xs text-muted-foreground border-t border-border pt-2 mt-1">
              Dernier ajustement : {Math.round(tuning.history[0].previous * 100)}% → {Math.round(tuning.history[0].new * 100)}%
              — {tuning.history[0].reason}
            </div>
          )}
        </Card>
      )}
      {(() => {
        const state = anprQuality?.cameras?.[cameraId];
        if (!state) return null;
        return (
          <Card className="p-4 space-y-2 md:col-span-2" data-testid="cam-anpr-quality">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wider text-muted-foreground">
                Qualité ANPR — auto-suspension ("pas de plaque &gt; fausse plaque")
              </div>
              {state.suspended && !state.is_specialized && (
                <Button size="sm" variant="outline" onClick={resetAnprQuality} disabled={resettingAnprQuality} data-testid="anpr-quality-reset">
                  {resettingAnprQuality ? "…" : "Forcer la reprise"}
                </Button>
              )}
            </div>
            {state.is_specialized ? (
              <div className="flex items-center gap-2">
                <Badge variant="secondary">Toujours actif</Badge>
                <span className="text-sm">{state.specialized_model} — caméra ANPR dédiée, l'auto-suspension ne s'applique pas.</span>
              </div>
            ) : state.suspended ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="destructive">ANPR suspendu</Badge>
                  <span className="text-sm">score qualité {Math.round((state.last_score || 0) * 100)}%</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {state.last_reason || "Conditions insuffisantes (luminosité/netteté/contraste)."}
                </p>
                <p className="text-xs text-muted-foreground">
                  Comportement normal sur une caméra standard hors des heures de jour — pour un fonctionnement 24/7,
                  il faut un modèle ANPR dédié (Dahua ITC413/ITC237/ITC215, Hikvision DeepInView…), conçu pour gérer
                  le bas éclairage lui-même. {state.total_suspensions > 1 && `${state.total_suspensions} suspensions au total.`}
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Badge variant="secondary">Actif</Badge>
                <span className="text-sm">score qualité {Math.round((state.last_score || 0) * 100)}%</span>
              </div>
            )}
          </Card>
        );
      })()}
    </div>
    </div>
  );
}

// v0.5.0.b · Events par caméra (plaques + alertes + erreurs)
function EventsTab({ cameraId }) {
  const { t } = useApp();
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
      <EventPanel title={t("camc.last_plates")} items={ev.plates}
             render={(p) => (
               <div className="flex justify-between">
                 <span className="font-mono">{p.plate || "—"}</span>
                 <span className="text-muted-foreground">{p.confidence != null ? `${Math.round(p.confidence * 100)}%` : ""}</span>
               </div>
             )} />
      <EventPanel title={t("camc.last_alerts")} items={ev.alerts}
             render={(a) => (
               <div>
                 <div className="font-medium">{a.title || a.type || "Alerte"}</div>
                 <div className="text-muted-foreground text-[10px]">{a.created_at?.slice(0, 19)?.replace("T", " ")}</div>
               </div>
             )} />
      <EventPanel title={t("camc.last_errors")} items={ev.errors}
             render={(e) => <div>{e.message || "—"}</div>} />
    </div>
  );
}

// ─── Audio (conditionnel) ───
function AudioTab({ cameraId, caps }) {
  const { t } = useApp();
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
            <Button onClick={start} data-testid="audio-start">{t("camc.start")}</Button>
            <Button variant="outline" onClick={stop} data-testid="audio-stop">{t("camc.stop")}</Button>
          </>
        )}
      </div>
    </Card>
  );
}

// ─── Lighting (conditionnel) ───
function LightingTab({ cameraId, caps }) {
  const { t } = useApp();
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
        <Button variant="outline" onClick={() => toggle(false)} data-testid="light-off">{t("camc.turn_off")}</Button>
      </div>
    </Card>
  );
}

// ─── Incrustation caméra (OSD — date/heure, nom) ───
// v3.19 · La caméra grave elle-même cette incrustation dans l'image —
// ce n'est PAS un overlay applicatif, donc jamais déplaçable depuis
// l'écran seul. Répond au signalement "informations superposées en
// haut de l'image" (l'incrustation caméra chevauchait nos propres infos).
const OSD_POSITIONS = ["Upper Left", "Upper Right", "Top Center", "Bottom Center", "Lower Left", "Lower Right"];
function OsdTab({ cameraId, caps }) {
  const [osd, setOsd] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!caps?.osd) return;
    api.get(`/devices/${cameraId}/osd`).then((r) => setOsd(r.data)).catch(() => setOsd(false));
  }, [cameraId, caps?.osd]);

  if (!caps?.osd) return <NotSupported what="Incrustation (OSD)" />;
  if (osd === null) return <Card className="p-4 text-sm text-muted-foreground">Chargement…</Card>;
  if (osd === false) return <Card className="p-4 text-sm text-muted-foreground">Lecture impossible sur cette caméra.</Card>;

  const save = (patch) => {
    const next = { ...osd, ...patch };
    setOsd(next);
    setSaving(true);
    api.post(`/devices/${cameraId}/osd`, {
      name_pos: next.name_enabled ? next.name_pos : "Off",
      date_pos: next.date_enabled ? next.date_pos : "Off",
    }).then(() => toast.success("Incrustation mise à jour"))
      .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"))
      .finally(() => setSaving(false));
  };

  const Row = ({ label, enabled, pos, onEnabled, onPos }) => (
    <div className="flex items-center gap-3">
      <label className="flex items-center gap-2 text-sm w-32 shrink-0">
        <input type="checkbox" checked={enabled} onChange={(e) => onEnabled(e.target.checked)} disabled={saving} />
        {label}
      </label>
      <select value={pos || "Upper Left"} onChange={(e) => onPos(e.target.value)} disabled={!enabled || saving}
              className="border border-border bg-card text-sm px-2 py-1.5 outline-none disabled:opacity-40">
        {OSD_POSITIONS.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
    </div>
  );

  return (
    <Card className="p-4 space-y-4" data-testid="cam-osd">
      <p className="text-xs text-muted-foreground">
        Position (ou désactivation) de la date/heure et du nom que la caméra grave elle-même dans l'image.
      </p>
      <Row label="Nom caméra" enabled={osd.name_enabled} pos={osd.name_pos}
           onEnabled={(v) => save({ name_enabled: v })} onPos={(v) => save({ name_pos: v })} />
      <Row label="Date / heure" enabled={osd.date_enabled} pos={osd.date_pos}
           onEnabled={(v) => save({ date_enabled: v })} onPos={(v) => save({ date_pos: v })} />
    </Card>
  );
}

// ─── Date et heure (v3.22) ───
// Horloge caméra à la demande (ONVIF GetSystemDateAndTime, générique
// quel que soit le constructeur) + configuration NTP. Remplace l'onglet
// équivalent retiré du formulaire d'ajout/édition caméra (le check
// obligatoire à l'ajout suffit là-bas) — ici c'est la vue persistante,
// consultable et actionnable à tout moment sans rouvrir le formulaire.
function DateTimeTab({ cameraId }) {
  const [state, setState] = useState(null); // null=chargement, false=erreur, objet=données
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [settingNtp, setSettingNtp] = useState(false);
  const [syncingNow, setSyncingNow] = useState(false);

  const load = () => {
    setRefreshing(true);
    api.get(`/cameras/${cameraId}/datetime`)
       .then((r) => { setState(r.data); setError(""); })
       .catch((e) => {
         setState(false);
         const d = e.response?.data?.detail;
         setError((typeof d === "string" ? d : d?.message) || "Lecture impossible sur cette caméra.");
       })
       .finally(() => setRefreshing(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [cameraId]);

  const setNtp = () => {
    setSettingNtp(true);
    api.post(`/cameras/${cameraId}/ntp`, { ntp_server: window.location.hostname })
       .then(() => { toast.success("Serveur de temps défini — MG-VMS resynchronisera cette caméra automatiquement toutes les 24h"); load(); })
       .catch((e) => toast.error(e.response?.data?.detail?.message || e.response?.data?.detail || "Échec"))
       .finally(() => setSettingNtp(false));
  };

  const syncNow = () => {
    setSyncingNow(true);
    api.post(`/cameras/${cameraId}/datetime/sync-now`)
       .then(() => { toast.success("Horloge caméra mise à l'heure du serveur"); load(); })
       .catch((e) => toast.error(e.response?.data?.detail?.message || e.response?.data?.detail || "Échec"))
       .finally(() => setSyncingNow(false));
  };

  if (state === null) return <Card className="p-4 text-sm text-muted-foreground" data-testid="cam-datetime">Chargement…</Card>;

  const drift = state ? Math.abs(state.drift_seconds ?? 0) : null;
  const driftOk = drift !== null && drift < 60;

  return (
    <Card className="p-4 space-y-4" data-testid="cam-datetime">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Horloge de la caméra, lue à la demande (ONVIF).</p>
        <Button size="sm" variant="outline" onClick={load} disabled={refreshing} data-testid="cam-datetime-refresh">
          {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
        </Button>
      </div>

      {state === false ? (
        <p className="text-sm text-[#FF3333]">{error}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Heure caméra</div>
              <div className="mono">{new Date(state.camera_time).toLocaleString("fr-FR")}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Heure serveur MG-VMS</div>
              <div className="mono">{new Date(state.server_time).toLocaleString("fr-FR")}</div>
            </div>
          </div>
          <div className={`text-sm ${driftOk ? "text-[#00E676]" : "text-[#FFB800]"}`}>
            Écart : {state.drift_seconds > 0 ? "+" : ""}{state.drift_seconds}s
            {driftOk ? " — horloge synchronisée" : " — dérive notable"}
          </div>
          <Button size="sm" variant="outline" onClick={syncNow} disabled={syncingNow} data-testid="cam-datetime-sync-now"
                  className="flex items-center gap-2">
            {syncingNow ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Synchroniser maintenant (à l'heure du serveur, ponctuel)
          </Button>
        </>
      )}

      <div className="border-t border-border pt-4">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Serveur de temps (NTP)</div>
        {state && state.ntp_managed ? (
          <p className="text-sm text-[#00E676]">
            Gérée par MG-VMS ({state.ntp_server}) — resynchronisation automatique toutes les 24h.
          </p>
        ) : (
          <>
            <p className="text-[11px] text-muted-foreground mb-2">
              Cette caméra n'est pas configurée pour se synchroniser sur MG-VMS — dérive possible avec le temps
              ou après un redémarrage caméra.
            </p>
            <Button onClick={setNtp} disabled={settingNtp} data-testid="cam-datetime-set-ntp"
                    className="flex items-center gap-2">
              {settingNtp ? <Loader2 className="w-4 h-4 animate-spin" /> : <Clock className="w-4 h-4" />}
              Configurer avec le serveur NTP local (MG-VMS) — fortement conseillé
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

// ─── Alarm (Siren) ───
function AlarmTab({ cameraId, caps }) {
  const { t } = useApp();
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
      <Label>{t("camc.duration_s")}</Label>
      <Input type="number" min={1} max={600} value={duration}
             onChange={(e) => setDuration(Number(e.target.value))}
             data-testid="siren-duration" />
      <div className="flex gap-2">
        <Button onClick={trigger} data-testid="siren-trigger">{t("camc.trigger")}</Button>
        <Button variant="outline" onClick={stop} data-testid="siren-stop">{t("camc.stop")}</Button>
      </div>
    </Card>
  );
}

const fmtGb = (bytes) => {
  if (!bytes || bytes <= 0) return "0 Go";
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 1 ? `${gb.toFixed(2)} Go` : `${(bytes / 1024 / 1024).toFixed(0)} Mo`;
};

// ─── Carte SD (v3.6) — vendor-agnostic, pilotée par caps.sdcard ───
// Lecture via /api/devices/{id}/recordings/stream (proxy ffmpeg côté
// backend) — jamais d'URL caméra brute (avec identifiants) exposée ici.
function SdCardTab({ cameraId, caps }) {
  const { t } = useApp();
  const [storage, setStorage] = useState(null);
  const [recordings, setRecordings] = useState(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(null);
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [start, setStart] = useState(toLocalInput(new Date(Date.now() - 24 * 3600 * 1000)));
  const [end, setEnd] = useState(toLocalInput(new Date()));
  // "main" = flux principal (HD), "sub" = sous-flux (SD, plus léger/rapide)
  const [quality, setQuality] = useState("main");

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
        params: {
          start: new Date(start).toISOString(),
          end: new Date(end).toISOString(),
          stream: quality,
        },
      });
      setRecordings(data.recordings || []);
      if (!(data.recordings || []).length) toast.info("Aucun enregistrement sur cette période");
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Recherche impossible");
    } finally { setLoading(false); }
  };

  const recUrl = (kind, fileName) => {
    const token = localStorage.getItem("mg_token");
    return `${process.env.REACT_APP_BACKEND_URL}/api/devices/${cameraId}/recordings/${kind}`
      + `?file=${encodeURIComponent(fileName)}&quality=${quality}`
      + `&token=${encodeURIComponent(token || "")}`;
  };
  const playUrl = (fileName) => recUrl("stream", fileName);
  const download = (fileName) => {
    const a = document.createElement("a");
    a.href = recUrl("download", fileName);
    a.download = fileName.split("/").pop() || "recording.mp4";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast.success("Téléchargement lancé");
  };

  return (
    <Card className="p-4 space-y-3" data-testid="cam-sdcard">
      {storage && storage.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="sdcard-storage">
          {storage.map((s, i) => (
            <div key={i} className="border border-border px-2 py-1.5 min-w-[220px]">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">{s.type || "SD"} #{s.index}</span>
                <span className={s.available ? "text-[#00E676]" : "text-[#FF3333]"}>
                  {s.available ? "OK" : "absente/erreur"}
                </span>
              </div>
              {s.available && s.total_bytes > 0 && (
                <>
                  <div className="mt-1 font-mono text-[11px]">
                    {fmtGb(s.total_bytes - s.free_bytes)} / {fmtGb(s.total_bytes)}
                    <span className="text-muted-foreground ml-1.5">({s.used_percent}% utilisé)</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-secondary overflow-hidden">
                    <div className="h-full bg-[#0044FF]"
                         style={{ width: `${Math.max(0, Math.min(100, s.used_percent))}%` }} />
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {storage && storage.length === 0 && (
        <div className="text-xs text-muted-foreground">{t("camc.no_storage")}</div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label>Depuis</Label>
          <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} data-testid="sdcard-start" />
        </div>
        <div>
          <Label>{t("camc.until")}</Label>
          <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="sdcard-end" />
        </div>
        <div>
          <Label>{t("camc.quality")}</Label>
          <div className="flex" data-testid="sdcard-quality">
            {[["main", "HD"], ["sub", "SD"]].map(([val, label]) => (
              <button key={val} type="button"
                      onClick={() => { setQuality(val); setPlaying(null); }}
                      data-testid={`sdcard-quality-${val}`}
                      className={`px-3 py-2 text-sm border ${quality === val
                        ? "bg-[#0044FF] text-white border-[#0044FF]"
                        : "border-border hover:bg-secondary"}`}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <Button onClick={search} disabled={loading} data-testid="sdcard-search">
          {loading ? "Recherche…" : "Rechercher"}
        </Button>
      </div>
      <div className="text-[11px] text-muted-foreground">
        HD = flux principal (qualité maximale) · SD = sous-flux (fichiers plus légers,
        lecture et téléchargement plus rapides).
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
                <Button size="sm" variant="outline" data-testid="sdcard-download-btn"
                        title={t("camc.download_local")}
                        onClick={(e) => { e.stopPropagation(); download(r.file_name); }}>
                  <Download className="w-3.5 h-3.5" />
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
  const [cam, setCam] = useState(null);
  const [presets, setPresets] = useState([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [addingPreset, setAddingPreset] = useState(false);
  const [patrol, setPatrol] = useState({ enabled: false, dwell_seconds: 8, preset_ids: [], running: false });
  const [patrolLoading, setPatrolLoading] = useState(true);
  const [patrolSaving, setPatrolSaving] = useState(false);

  // v3.45 · Visuel live indispensable pour placer un preset : sans lui
  // l'utilisateur devait deviner la position en jonglant avec l'onglet
  // "Live" séparé. Même pattern que LiveTab (GET /cameras/{id} + LivePlayer).
  useEffect(() => {
    let alive = true;
    api.get(`/cameras/${cameraId}`).then((r) => { if (alive) setCam(r.data); }).catch(() => {});
    return () => { alive = false; };
  }, [cameraId]);

  const loadPresets = () => {
    setPresetsLoading(true);
    api.get(`/devices/${cameraId}/ptz/presets`)
       .then((r) => setPresets(r.data.presets || []))
       .catch(() => setPresets([]))
       .finally(() => setPresetsLoading(false));
  };
  const loadPatrol = () => {
    setPatrolLoading(true);
    api.get(`/devices/${cameraId}/ptz/patrol`)
       .then((r) => setPatrol({
         enabled: !!r.data.enabled, dwell_seconds: r.data.dwell_seconds || 8,
         preset_ids: r.data.preset_ids || [], running: !!r.data.running,
       }))
       .catch(() => {})
       .finally(() => setPatrolLoading(false));
  };

  useEffect(() => {
    if (!caps?.ptz) return;
    loadPresets();
    loadPatrol();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, caps?.ptz]);

  if (!caps?.ptz) return <NotSupported what="PTZ" />;

  const move = (direction) =>
    api.post(`/devices/${cameraId}/ptz/move`, { direction, speed: 0.5 })
       .then(() => {})
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const zoom = (value) =>
    api.post(`/devices/${cameraId}/ptz/zoom`, { value })
       .then(() => {})
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  const gotoPreset = (id) =>
    api.post(`/devices/${cameraId}/ptz/preset`, { id: Number(id) })
       .then(() => toast.success(`Preset ${id}`))
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));

  const addPreset = () => {
    const name = window.prompt("Nom du preset (optionnel) — sera créé à la position actuelle de la caméra :", "");
    if (name === null) return; // annulé
    setAddingPreset(true);
    api.post(`/devices/${cameraId}/ptz/presets`, { name: name.trim() || undefined })
       .then((r) => {
         toast.success(`Preset "${r.data.name}" ajouté`);
         loadPresets();
       })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"))
       .finally(() => setAddingPreset(false));
  };

  const deletePreset = (preset) => {
    if (!window.confirm(`Supprimer le preset "${preset.name}" ?`)) return;
    api.delete(`/devices/${cameraId}/ptz/presets/${preset.id}`)
       .then(() => {
         toast.success("Preset supprimé");
         loadPresets();
         setPatrol((p) => ({ ...p, preset_ids: p.preset_ids.filter((id) => id !== preset.id) }));
       })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"));
  };

  const savePatrol = (next) => {
    setPatrolSaving(true);
    api.put(`/devices/${cameraId}/ptz/patrol`, {
      enabled: next.enabled, dwell_seconds: next.dwell_seconds, preset_ids: next.preset_ids,
    }).then((r) => {
      setPatrol({ ...next, running: !!r.data.running });
    }).catch((e) => toast.error(e.response?.data?.detail?.message || "Erreur"))
      .finally(() => setPatrolSaving(false));
  };

  const toggleInPatrol = (presetId) => {
    const inList = patrol.preset_ids.includes(presetId);
    const preset_ids = inList
      ? patrol.preset_ids.filter((id) => id !== presetId)
      : [...patrol.preset_ids, presetId];
    savePatrol({ ...patrol, preset_ids });
  };

  const movePatrolStep = (idx, dir) => {
    const target = idx + dir;
    if (target < 0 || target >= patrol.preset_ids.length) return;
    const preset_ids = [...patrol.preset_ids];
    [preset_ids[idx], preset_ids[target]] = [preset_ids[target], preset_ids[idx]];
    savePatrol({ ...patrol, preset_ids });
  };

  const presetName = (id) => presets.find((p) => p.id === id)?.name || id;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_260px] gap-4 items-start">
        <Card className="p-3 space-y-2" data-testid="cam-ptz-live">
          <div className="text-sm text-muted-foreground">
            Vue live — positionne la caméra ici, puis "Ajouter preset ici" à droite
          </div>
          <div className="relative aspect-video bg-black">
            {cam ? (
              <LivePlayer key={cameraId} camera={cam} hd={false}
                          className="w-full h-full" dataTestId="ptz-live-player" />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                <Loader2 size={20} className="animate-spin" />
              </div>
            )}
          </div>
        </Card>

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
          <Button variant="outline" size="sm" onClick={addPreset} disabled={addingPreset}
                  className="w-full" data-testid="ptz-preset-add-inline">
            {addingPreset ? <Loader2 size={14} className="animate-spin mr-1" /> : <Plus size={14} className="mr-1" />}
            Ajouter preset ici
          </Button>
        </Card>
      </div>

      <Card className="p-4 space-y-3" data-testid="cam-ptz-presets">
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Presets — positionne la caméra puis "Ajouter" (aucune limite)
          </div>
          <Button variant="outline" size="sm" onClick={addPreset} disabled={addingPreset}
                  data-testid="ptz-preset-add">
            {addingPreset ? <Loader2 size={14} className="animate-spin mr-1" /> : <Plus size={14} className="mr-1" />}
            Ajouter preset ici
          </Button>
        </div>
        {presetsLoading ? (
          <div className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Chargement…
          </div>
        ) : presets.length === 0 ? (
          <div className="text-sm text-muted-foreground">Aucun preset enregistré pour cette caméra.</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <div key={p.id} className="flex items-center border border-border overflow-hidden"
                   data-testid={`ptz-preset-row-${p.id}`}>
                <button onClick={() => gotoPreset(p.id)}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm hover:bg-secondary"
                        title={`Aller au preset ${p.name}`}>
                  <MapPin size={12} /> {p.name}
                </button>
                <button onClick={() => deletePreset(p)}
                        className="px-2 py-1.5 text-muted-foreground hover:bg-destructive hover:text-destructive-foreground"
                        title="Supprimer ce preset" data-testid={`ptz-preset-delete-${p.id}`}>
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-4 space-y-3" data-testid="cam-ptz-patrol">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium flex items-center gap-2">
              Patrouille automatique
              {patrol.enabled && (
                <Badge variant={patrol.running ? "default" : "secondary"} className="text-[10px]">
                  {patrol.running ? "en cours" : "en pause"}
                </Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Enchaîne les presets cochés ci-dessous, dans l'ordre choisi, en boucle.
            </div>
          </div>
          <Switch checked={patrol.enabled} disabled={patrolLoading || patrolSaving}
                  onCheckedChange={(enabled) => savePatrol({ ...patrol, enabled })}
                  data-testid="ptz-patrol-toggle" />
        </div>

        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground whitespace-nowrap">Temps par preset (s)</Label>
          <Input type="number" min={2} max={600} value={patrol.dwell_seconds}
                 className="w-20 h-8 text-xs"
                 onChange={(e) => setPatrol((p) => ({ ...p, dwell_seconds: Number(e.target.value) || 8 }))}
                 onBlur={() => savePatrol(patrol)}
                 data-testid="ptz-patrol-dwell" />
        </div>

        {presets.length === 0 ? (
          <div className="text-xs text-muted-foreground">Ajoute d'abord au moins un preset ci-dessus.</div>
        ) : (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">Presets disponibles — coche pour inclure dans la patrouille :</div>
            <div className="flex flex-wrap gap-2">
              {presets.map((p) => (
                <label key={p.id}
                       className="flex items-center gap-1.5 text-xs px-2 py-1 border border-border cursor-pointer">
                  <input type="checkbox" checked={patrol.preset_ids.includes(p.id)}
                         onChange={() => toggleInPatrol(p.id)}
                         data-testid={`ptz-patrol-include-${p.id}`} />
                  {p.name}
                </label>
              ))}
            </div>
            {patrol.preset_ids.length > 0 && (
              <div>
                <div className="text-xs text-muted-foreground mt-2 mb-1">
                  Ordre de la tournée (défini manuellement — flèches pour réordonner) :
                </div>
                <div className="space-y-1">
                  {patrol.preset_ids.map((id, idx) => (
                    <div key={id} className="flex items-center gap-2 text-xs bg-secondary/50 px-2 py-1"
                         data-testid={`ptz-patrol-order-${idx}`}>
                      <span className="mono text-muted-foreground w-4">{idx + 1}.</span>
                      <span className="flex-1">{presetName(id)}</span>
                      <button onClick={() => movePatrolStep(idx, -1)} disabled={idx === 0}
                              className="disabled:opacity-30 hover:text-[#0044FF]" title="Monter">
                        <ArrowUp size={12} />
                      </button>
                      <button onClick={() => movePatrolStep(idx, 1)} disabled={idx === patrol.preset_ids.length - 1}
                              className="disabled:opacity-30 hover:text-[#0044FF]" title="Descendre">
                        <ArrowDown size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function MaintenanceTab({ cameraId }) {
  const { t } = useApp();
  const [status, setStatus] = useState(null);
  useEffect(() => {
    api.get(`/devices/${cameraId}/status`).then((r) => setStatus(r.data))
       .catch(() => setStatus(null));
  }, [cameraId]);
  if (!status) return <Card className="p-6 text-sm">{t("camc.no_status")}</Card>;
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
