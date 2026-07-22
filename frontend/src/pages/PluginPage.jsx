import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import {
  Puzzle, CheckCircle2, XCircle, AlertTriangle, Loader2, Save, Wifi, Info, ArrowLeft, BrainCircuit, Radio,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Page générique pour un plugin — dispatche vers un formulaire spécifique
 * quand un plugin a une vraie config à exposer, sinon affiche un rappel honnête
 * de ce qui manque pour l'activer (aucune donnée fictive).
 */
export default function PluginPage() {
  const { pluginId } = useParams();
  const [plugin, setPlugin] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get("/plugins").then((r) => {
      const p = (r.data || []).find((x) => x.id === pluginId);
      setPlugin(p || null);
    }).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [pluginId]);

  if (loading) return <div className="p-8 text-center text-muted-foreground"><Loader2 size={20} className="animate-spin inline mr-2" />Chargement…</div>;
  if (!plugin) return <div className="p-8"><Link to="/plugins" className="text-[#0044FF] text-sm flex items-center gap-1"><ArrowLeft size={14} /> Retour aux plugins</Link><p className="mt-4 text-muted-foreground">Plugin introuvable.</p></div>;

  return (
    <div className="p-4 max-w-5xl">
      <Link to="/plugins" className="text-[#0044FF] text-xs flex items-center gap-1 mb-3"><ArrowLeft size={12} /> Retour</Link>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Puzzle size={22} /> {plugin.name}</h1>
          <p className="text-sm text-muted-foreground mt-1">{plugin.description}</p>
          <p className="text-[10px] mono text-muted-foreground mt-1">v{plugin.version} · {plugin.category}</p>
        </div>
        <StatusBadge status={plugin.status} />
      </div>

      <HealthChecklist health={plugin.health} />

      <div className="mt-6">
        {plugin.id === "ai_detection" && <AiDetectionSettings onSaved={load} />}
        {plugin.id === "mqtt" && <MqttSettings onSaved={load} />}
        {!(["ai_detection", "mqtt"].includes(plugin.id)) && (
          <RoadmapNote plugin={plugin} />
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    ok:             { color: "#00E676", label: "Opérationnel",  Ic: CheckCircle2 },
    error:          { color: "#FF3333", label: "Erreur",        Ic: XCircle },
    not_configured: { color: "#FFB800", label: "À configurer",  Ic: AlertTriangle },
    disabled:       { color: "#666",    label: "Désactivé",     Ic: Info },
  };
  const m = map[status] || map.not_configured;
  const Ic = m.Ic;
  return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 border text-sm" style={{ borderColor: m.color, color: m.color }} data-testid="plugin-page-status"><Ic size={14} /> {m.label}</span>;
}

function HealthChecklist({ health }) {
  if (!health || !health.checks?.length) return null;
  return (
    <div className="border border-border p-3 bg-card">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">État du plugin</div>
      <ul className="space-y-1">
        {health.checks.map((c, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            {c.ok ? <CheckCircle2 size={14} className="text-[#00E676] mt-0.5" /> : <XCircle size={14} className="text-[#FF3333] mt-0.5" />}
            <span>{c.name}</span>
            <span className="ml-auto text-xs mono text-muted-foreground">{c.detail}</span>
          </li>
        ))}
      </ul>
      {health.warning && <p className="mt-2 text-[11px] text-[#FFB800] border-l-2 border-[#FFB800] pl-2">{health.warning}</p>}
      {(health.events_total > 0 || health.last_event_at) && (
        <div className="mt-3 grid grid-cols-3 gap-2 pt-2 border-t border-border">
          <Stat label="Total" value={health.events_total} />
          <Stat label="24 h" value={health.events_24h || 0} />
          <Stat label="Dernier" value={health.last_event_at ? new Date(health.last_event_at).toLocaleTimeString("fr-FR") : "—"} small />
        </div>
      )}
    </div>
  );
}
const Stat = ({ label, value, small }) => (
  <div className="text-center">
    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
    <div className={small ? "mono text-xs" : "mono text-lg font-bold"}>{value}</div>
  </div>
);

function AiDetectionSettings({ onSaved }) {
  const { can } = useApp();
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api.get("/ai/config").then((r) => setCfg(r.data)).catch(() => {}); }, []);
  if (!cfg) return <p className="text-muted-foreground">Chargement de la config IA…</p>;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/ai/config", {
        interval_seconds: Number(cfg.interval_seconds),
        confidence: Number(cfg.confidence),
        min_plate_px: Number(cfg.min_plate_px),
        plate_cache_seconds: Number(cfg.plate_cache_seconds),
        device: cfg.device,
      });
      setCfg(data); toast.success("Config IA appliquée à chaud"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec sauvegarde"); }
    finally { setSaving(false); }
  };

  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center gap-2 mb-3"><BrainCircuit size={18} className="text-[#0044FF]" /><span className="font-head font-semibold">Paramètres YOLO + ALPR</span></div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Intervalle d'analyse (secondes)" hint="0.2 → 60 · plus bas = analyse plus fréquente">
          <input type="number" min="0.2" max="60" step="0.1" value={cfg.interval_seconds} onChange={(e) => setCfg({ ...cfg, interval_seconds: e.target.value })} className="inp mono" data-testid="ai-cfg-interval" />
        </Field>
        <Field label="Seuil de confiance YOLO" hint="0.1 → 0.95">
          <input type="number" min="0.1" max="0.95" step="0.05" value={cfg.confidence} onChange={(e) => setCfg({ ...cfg, confidence: e.target.value })} className="inp mono" data-testid="ai-cfg-conf" />
        </Field>
        <Field label="Taille min. plaque (px)" hint="8 → 200 · filtre les plaques trop petites pour l'OCR">
          <input type="number" min="8" max="200" value={cfg.min_plate_px} onChange={(e) => setCfg({ ...cfg, min_plate_px: e.target.value })} className="inp mono" data-testid="ai-cfg-plate" />
        </Field>
        <Field label="Cache plaques (secondes)" hint="0 → 300 · évite l'OCR répété">
          <input type="number" min="0" max="300" value={cfg.plate_cache_seconds} onChange={(e) => setCfg({ ...cfg, plate_cache_seconds: e.target.value })} className="inp mono" data-testid="ai-cfg-cache" />
        </Field>
        <Field label="Cible d'inférence" hint="`auto` détecte automatiquement CUDA si dispo">
          <select value={cfg.device} onChange={(e) => setCfg({ ...cfg, device: e.target.value })} className="inp" data-testid="ai-cfg-device">
            <option value="auto">Auto (CUDA si dispo, sinon CPU)</option>
            <option value="cpu">CPU forcé</option>
            <option value="cuda">CUDA forcé (erreur si absent)</option>
          </select>
        </Field>
        <Field label="Device utilisé actuellement">
          <input value={cfg.device_effective} readOnly className="inp mono text-[#00E676]" />
        </Field>
      </div>
      <button onClick={save} disabled={saving || !can("admin")} data-testid="ai-cfg-save"
              className="mt-4 flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc] disabled:opacity-50">
        {saving && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> Appliquer
      </button>
      <p className="text-[10px] text-muted-foreground mt-2">Les modifications sont persistées en base et appliquées immédiatement au moteur IA sans redémarrage.</p>
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function MqttSettings({ onSaved }) {
  const { can } = useApp();
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => { api.get("/settings/mqtt").then((r) => setCfg(r.data)).catch(() => {}); }, []);
  if (!cfg) return <p className="text-muted-foreground">Chargement de la config MQTT…</p>;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/settings/mqtt", {
        ...cfg, port: Number(cfg.port) || 1883,
      });
      setCfg(data); toast.success("Config MQTT enregistrée"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec sauvegarde"); }
    finally { setSaving(false); }
  };

  const testConnection = async () => {
    if (!cfg.host) return toast.error("Host requis");
    setTesting(true); setTestResult(null);
    try {
      // Test TCP simple via l'endpoint générique test-connectivity RTSP
      // (validation IP + port), en attendant un endpoint MQTT dédié.
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/cameras/test-connectivity`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("mg_token") || ""}` },
        body: JSON.stringify({ mode: "rtsp", ip: cfg.host, rtsp_port: Number(cfg.port) || 1883, rtsp_url: "" }),
      });
      const d = await r.json();
      const port_ok = (d.steps || []).find((s) => s.name === "ping")?.status === "ok";
      setTestResult({ ok: port_ok, message: port_ok ? `Broker ${cfg.host}:${cfg.port} joignable (TCP)` : `Broker ${cfg.host}:${cfg.port} injoignable` });
    } catch (e) { setTestResult({ ok: false, message: "Erreur test connexion" }); }
    finally { setTesting(false); }
  };

  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center gap-2 mb-3"><Radio size={18} className="text-[#A855F7]" /><span className="font-head font-semibold">Configuration du broker MQTT</span></div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Host / adresse du broker">
          <input value={cfg.host} onChange={(e) => setCfg({ ...cfg, host: e.target.value })} placeholder="broker.mgvms.local" className="inp mono" data-testid="mqtt-host" />
        </Field>
        <Field label="Port">
          <input type="number" value={cfg.port} onChange={(e) => setCfg({ ...cfg, port: e.target.value })} className="inp mono" data-testid="mqtt-port" />
        </Field>
        <Field label="Utilisateur">
          <input value={cfg.username} onChange={(e) => setCfg({ ...cfg, username: e.target.value })} className="inp" autoComplete="off" data-testid="mqtt-user" />
        </Field>
        <Field label="Mot de passe">
          <input type="password" value={cfg.password} onChange={(e) => setCfg({ ...cfg, password: e.target.value })} className="inp" autoComplete="new-password" data-testid="mqtt-password" />
        </Field>
        <Field label="Préfixe de topic" hint="Ex: mgvms → mgvms/events/plate">
          <input value={cfg.topic_prefix} onChange={(e) => setCfg({ ...cfg, topic_prefix: e.target.value })} className="inp mono" data-testid="mqtt-prefix" />
        </Field>
        <Field label="TLS">
          <label className="flex items-center gap-2 text-sm mt-2">
            <input type="checkbox" checked={cfg.tls} onChange={(e) => setCfg({ ...cfg, tls: e.target.checked })} data-testid="mqtt-tls" />
            Activer TLS (port 8883 conseillé)
          </label>
        </Field>
      </div>
      <div className="mt-4 flex gap-2">
        <button onClick={save} disabled={saving || !can("admin")} data-testid="mqtt-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm">
          {saving && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> Enregistrer
        </button>
        <button onClick={testConnection} disabled={testing || !cfg.host} data-testid="mqtt-test" className="flex items-center gap-2 px-4 py-2 border border-border text-sm hover:bg-secondary">
          {testing && <Loader2 size={14} className="animate-spin" />}<Wifi size={14} /> Tester la connexion (TCP)
        </button>
      </div>
      {testResult && (
        <p className="mt-2 text-sm" style={{ color: testResult.ok ? "#00E676" : "#FF3333" }} data-testid="mqtt-test-result">
          {testResult.ok ? "✓" : "✗"} {testResult.message}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground mt-3 border-l-2 border-border pl-2">
        Note : la publication effective d'événements sur MQTT est prévue dès l'installation de <span className="mono">paho-mqtt</span> côté serveur (voir Health-check). Cette page prépare la configuration.
      </p>
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function RoadmapNote({ plugin }) {
  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center gap-2 mb-3"><Info size={18} className="text-[#FFB800]" /><span className="font-head font-semibold">Fonctionnalité en développement</span></div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        Le plugin <b>{plugin.name}</b> est présent dans le catalogue mais son interface dédiée n&apos;est pas encore livrée.
        Les prérequis d&apos;activation sont listés dans l&apos;état ci-dessus. Aucun comportement fictif n&apos;est simulé — l&apos;interface complète (menus, statistiques, actions) sera ajoutée dans une prochaine version.
      </p>
      <p className="text-[10px] mono text-muted-foreground mt-3">
        Roadmap :
        {plugin.id === "tracking" && " ByteTrack persistant + trajectoires overlay (P2)"}
        {plugin.id === "face_recognition" && " Import de visages · groupes · alertes (P2/P3, sous réserve légale)"}
        {plugin.id === "parking" && " Zones dessinées sur flux · comptage occupation · durée moyenne (P2)"}
        {plugin.id === "thermal" && " Décodage flux radiométrique · seuils de température · alertes (P3, matériel requis)"}
        {plugin.id === "radar" && " Intégration radar Doppler · limites de vitesse · infractions (P3, matériel requis)"}
        {plugin.id === "drone" && " Flux vidéo drone · plan de patrouille · retour au home (P3, matériel requis)"}
        {plugin.id === "access_control" && " Portes / lecteurs Wiegand & OSDP · badges · journal (P2/P3)"}
      </p>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground mt-0.5">{hint}</p>}
    </div>
  );
}
