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
import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import api from "@/lib/api";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";
import {
  Camera, Wifi, Video, Layers, Cpu, Volume2, Sun, Bell, Move3d, Wrench,
  ScanLine, RefreshCw, AlertCircle, CircleCheck,
} from "lucide-react";

const TABS = [
  { id: "overview",     label: "Overview",     icon: Camera },
  { id: "live",         label: "Live",         icon: Video },
  { id: "network",      label: "Network",      icon: Wifi },
  { id: "streams",      label: "Streams",      icon: Video },
  { id: "capabilities", label: "Capabilities", icon: Layers },
  { id: "ai",           label: "AI",           icon: Cpu },
  { id: "audio",        label: "Audio",        icon: Volume2 },
  { id: "lighting",     label: "Lighting",     icon: Sun },
  { id: "alarm",        label: "Alarm",        icon: Bell },
  { id: "ptz",          label: "PTZ",          icon: Move3d },
  { id: "maintenance",  label: "Maintenance",  icon: Wrench },
];

export default function CameraCenter() {
  const { cameraId } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const setTab = (t) => setParams({ tab: t });
  const { caps, info, loading, error, refresh, discover } = useDeviceCapabilities(cameraId);

  return (
    <div className="p-6 space-y-4" data-testid="camera-center">
      <div className="flex items-center justify-between gap-4">
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
              <div className="text-sm text-muted-foreground">{error.message}</div>
              {error.status === 404 && (
                <div className="text-xs mt-1">
                  Astuce : cliquez sur <b>Détecter capacités</b> pour lancer la probe initiale.
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

        <TabsContent value="overview"><OverviewTab info={info} caps={caps} /></TabsContent>
        <TabsContent value="live"><LiveTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="network"><NetworkTab info={info} /></TabsContent>
        <TabsContent value="streams"><StreamsTab cameraId={cameraId} /></TabsContent>
        <TabsContent value="capabilities"><CapabilitiesTab caps={caps} /></TabsContent>
        <TabsContent value="ai"><AITab caps={caps} /></TabsContent>
        <TabsContent value="audio"><AudioTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="lighting"><LightingTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="alarm"><AlarmTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="ptz"><PTZTab cameraId={cameraId} caps={caps} /></TabsContent>
        <TabsContent value="maintenance"><MaintenanceTab cameraId={cameraId} /></TabsContent>
      </Tabs>
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

// ─── Overview ───
function OverviewTab({ info, caps }) {
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="cam-overview">
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">Identité</div>
        <div className="grid grid-cols-2 gap-1 text-sm">
          <div>Fabricant</div><div className="font-mono">{info?.manufacturer || "—"}</div>
          <div>Modèle</div><div className="font-mono">{info?.model || "—"}</div>
          <div>Firmware</div><div className="font-mono">{info?.firmware || "—"}</div>
          <div>Serial</div><div className="font-mono">{info?.serial || "—"}</div>
          <div>MAC</div><div className="font-mono">{info?.mac || "—"}</div>
          <div>IP</div><div className="font-mono">{info?.ip || "—"}</div>
        </div>
      </Card>
      <Card className="p-4 space-y-1">
        <div className="text-sm text-muted-foreground">Capacités clés</div>
        <div className="grid grid-cols-2 gap-1 mt-2">
          <CapField ok={caps?.ptz} label="PTZ" />
          <CapField ok={caps?.zoom} label="Zoom" />
          <CapField ok={caps?.spotlight || caps?.white_light} label="Lumière" />
          <CapField ok={caps?.siren} label="Sirène" />
          <CapField ok={caps?.two_way_audio} label="Talk-back" />
          <CapField ok={caps?.onboard_ai} label="IA embarquée" />
        </div>
      </Card>
    </div>
  );
}

function LiveTab({ cameraId }) {
  return (
    <Card className="p-6 text-sm text-muted-foreground" data-testid="cam-live">
      Live WebRTC : cette vue utilise la page{" "}
      <a className="underline" href={`/live?camera=${cameraId}`}>Live</a> existante.
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

function CapabilitiesTab({ caps }) {
  if (!caps) return <Card className="p-6 text-sm">Capabilités non détectées. Lancez un discover.</Card>;
  const groups = [
    { title: "PTZ / Optique", fields: ["ptz", "zoom", "focus"] },
    { title: "Audio", fields: ["audio_input", "audio_output", "microphone", "speaker", "two_way_audio"] },
    { title: "Lumière & IR", fields: ["spotlight", "white_light", "ir_control", "ir_cut_filter"] },
    { title: "Alarme", fields: ["siren", "alarm_output"] },
    { title: "Capteurs", fields: ["pir_sensor", "battery"] },
    { title: "IA embarquée", fields: ["onboard_ai"] },
    { title: "Protocoles", fields: ["onvif", "isapi", "cgi", "reolink_api"] },
  ];
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="cam-capabilities">
      {groups.map((g) => (
        <Card key={g.title} className="p-4 space-y-2">
          <div className="text-sm text-muted-foreground">{g.title}</div>
          {g.fields.map((f) => <CapField key={f} ok={!!caps[f]} label={f} />)}
        </Card>
      ))}
      {caps.onboard_ai_features?.length > 0 && (
        <Card className="p-4 space-y-1">
          <div className="text-sm text-muted-foreground">Features IA embarquées</div>
          <div className="flex flex-wrap gap-1 pt-1">
            {caps.onboard_ai_features.map((f) => <Badge key={f} variant="secondary">{f}</Badge>)}
          </div>
        </Card>
      )}
    </div>
  );
}

function AITab({ caps }) {
  if (!caps?.onboard_ai) return <NotSupported what="IA embarquée constructeur" />;
  return (
    <Card className="p-4" data-testid="cam-ai">
      <div className="text-sm">Features supportées :</div>
      <div className="flex flex-wrap gap-1 pt-2">
        {(caps.onboard_ai_features || []).map((f) => <Badge key={f}>{f}</Badge>)}
      </div>
    </Card>
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
