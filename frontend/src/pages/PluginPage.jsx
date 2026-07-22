import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import PolygonEditor from "@/components/PolygonEditor";
import {
  Puzzle, CheckCircle2, XCircle, AlertTriangle, Loader2, Save, Wifi, Info, ArrowLeft, BrainCircuit, Radio,
  ScanLine, Activity, ScanFace, Car, Thermometer, Radar as RadarIcon, Plane, DoorOpen, Plus, Trash2, Edit3, Waypoints, MapPin,
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
        {plugin.id === "anpr" && <AnprSettings onSaved={load} />}
        {plugin.id === "tracking" && <TrackingSettings onSaved={load} />}
        {plugin.id === "face_recognition" && <FaceRecognitionSettings onSaved={load} />}
        {plugin.id === "parking" && <ParkingSettings onSaved={load} />}
        {plugin.id === "access_control" && <AccessControlSettings onSaved={load} />}
        {plugin.id === "thermal" && <SensorSettings kind="thermal" label="thermique" Icon={Thermometer} onSaved={load} />}
        {plugin.id === "radar" && <SensorSettings kind="radar" label="radar" Icon={RadarIcon} onSaved={load} />}
        {plugin.id === "drone" && <SensorSettings kind="drone" label="drone" Icon={Plane} onSaved={load} />}
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
        Note : la publication effective d&apos;événements sur MQTT est prévue dès l&apos;installation de <span className="mono">paho-mqtt</span> côté serveur (voir Health-check). Cette page prépare la configuration.
      </p>
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
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

// ═══════════════════════════════════════════════════════════════════
// ANPR — Config globale + par caméra (ROI polygone, listes locales)
// ═══════════════════════════════════════════════════════════════════
const COUNTRIES = [
  { v: "fr", l: "France" }, { v: "de", l: "Allemagne" }, { v: "it", l: "Italie" },
  { v: "es", l: "Espagne" }, { v: "be", l: "Belgique" }, { v: "nl", l: "Pays-Bas" },
  { v: "uk", l: "Royaume-Uni" }, { v: "us", l: "États-Unis" }, { v: "eu", l: "Europe (générique)" },
  { v: "other", l: "Autre" },
];

function AnprSettings({ onSaved }) {
  const { can } = useApp();
  const [cfg, setCfg] = useState(null);
  const [cams, setCams] = useState([]);
  const [editing, setEditing] = useState(null); // { camera, config }
  const [saving, setSaving] = useState(false);

  const loadAll = async () => {
    try {
      const [c, l] = await Promise.all([api.get("/plugins/anpr/config"), api.get("/plugins/anpr/cameras")]);
      setCfg(c.data); setCams(l.data);
    } catch (e) { /* ignore */ }
  };
  useEffect(() => { loadAll(); }, []);

  if (!cfg) return <p className="text-muted-foreground">Chargement config ANPR…</p>;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/plugins/anpr/config", {
        ...cfg,
        min_plate_px: Number(cfg.min_plate_px),
        max_plate_px: Number(cfg.max_plate_px),
        ocr_confidence: Number(cfg.ocr_confidence),
        cache_seconds: Number(cfg.cache_seconds),
      });
      setCfg(data); toast.success("Config ANPR globale enregistrée"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec sauvegarde"); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-4">
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center gap-2 mb-3"><ScanLine size={18} className="text-[#0044FF]" /><span className="font-head font-semibold">Configuration ANPR globale</span></div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Field label="Pays des plaques" hint="Priorité de l'OCR par région">
            <select value={cfg.country} onChange={(e) => setCfg({ ...cfg, country: e.target.value })} className="inp" data-testid="anpr-country">
              {COUNTRIES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
            </select>
          </Field>
          <Field label="Taille min. plaque (px)"><input type="number" min="8" max="200" value={cfg.min_plate_px} onChange={(e) => setCfg({ ...cfg, min_plate_px: e.target.value })} className="inp mono" data-testid="anpr-min-px" /></Field>
          <Field label="Taille max. plaque (px)"><input type="number" min="50" max="1000" value={cfg.max_plate_px} onChange={(e) => setCfg({ ...cfg, max_plate_px: e.target.value })} className="inp mono" /></Field>
          <Field label="Confiance OCR mini." hint="0.1 → 0.95"><input type="number" step="0.05" min="0.1" max="0.95" value={cfg.ocr_confidence} onChange={(e) => setCfg({ ...cfg, ocr_confidence: e.target.value })} className="inp mono" /></Field>
          <Field label="Cache plaques (s)"><input type="number" min="0" max="300" value={cfg.cache_seconds} onChange={(e) => setCfg({ ...cfg, cache_seconds: e.target.value })} className="inp mono" /></Field>
          <Field label="Alertes">
            <label className="flex items-center gap-2 text-sm mt-1"><input type="checkbox" checked={cfg.alert_on_blacklist} onChange={(e) => setCfg({ ...cfg, alert_on_blacklist: e.target.checked })} data-testid="anpr-alert-bl" /> Liste noire</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.alert_on_unknown} onChange={(e) => setCfg({ ...cfg, alert_on_unknown: e.target.checked })} /> Plaques inconnues</label>
          </Field>
        </div>
        <button onClick={save} disabled={saving || !can("admin")} className="mt-3 flex items-center gap-1.5 px-3 py-1.5 bg-[#0044FF] text-white text-sm disabled:opacity-50" data-testid="anpr-cfg-save">
          {saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer
        </button>
      </div>

      <div className="border border-border p-4 bg-card">
        <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          <div className="flex items-center gap-2"><Waypoints size={18} className="text-[#00E676]" /><span className="font-head font-semibold">Configuration par caméra (ROI, listes locales)</span></div>
          <div className="flex items-center gap-2">
            <a href={`${process.env.REACT_APP_BACKEND_URL}/api/plugins/anpr/watchlist/export?token=${encodeURIComponent(localStorage.getItem("mg_token") || "")}`}
               className="text-xs px-2.5 py-1 border border-border hover:bg-secondary flex items-center gap-1" data-testid="wl-export-btn">
              <Save size={11} /> Exporter watchlist globale (CSV)
            </a>
            <label className="text-xs px-2.5 py-1 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10 flex items-center gap-1 cursor-pointer" data-testid="wl-import-btn">
              <Plus size={11} /> Importer CSV
              <input type="file" accept=".csv,.txt" className="hidden"
                     onChange={async (e) => {
                       const file = e.target.files?.[0]; if (!file) return;
                       const fd = new FormData(); fd.append("csv_file", file);
                       try {
                         const { data } = await api.post("/plugins/anpr/watchlist/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
                         toast.success(`Import OK : ${data.inserted} ajoutée(s), ${data.updated} mise(s) à jour · ${data.errors?.length || 0} erreur(s)`);
                         if (data.errors?.length) console.warn("CSV errors", data.errors);
                       } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Import échoué"); }
                       finally { e.target.value = ""; }
                     }} />
            </label>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
              <tr><th className="text-left py-2">Caméra</th><th className="text-left">Site</th><th>Détection IA</th><th>ROI</th><th>WL locale</th><th>BL locale</th><th></th></tr>
            </thead>
            <tbody>
              {cams.map((c) => (
                <tr key={c.id} className="border-b border-border/50">
                  <td className="py-2 font-medium">{c.name}</td>
                  <td className="text-muted-foreground">{c.site_name || "—"}</td>
                  <td className="text-center">{c.detect_enabled ? <CheckCircle2 size={14} className="inline text-[#00E676]" /> : <XCircle size={14} className="inline text-muted-foreground" />}</td>
                  <td className="text-center mono">{c.roi_points > 0 ? <span className="text-[#00E676]">{c.roi_points} pts</span> : <span className="text-muted-foreground">—</span>}</td>
                  <td className="text-center mono">{c.wl_count || <span className="text-muted-foreground">0</span>}</td>
                  <td className="text-center mono">{c.bl_count || <span className="text-muted-foreground">0</span>}</td>
                  <td className="text-right">
                    <button onClick={() => setEditing({ camera: c })} className="text-xs px-2 py-1 border border-border hover:bg-secondary flex items-center gap-1 ml-auto" data-testid={`anpr-edit-${c.id}`}>
                      <Edit3 size={11} /> Configurer
                    </button>
                  </td>
                </tr>
              ))}
              {cams.length === 0 && <tr><td colSpan={7} className="py-4 text-center text-muted-foreground">Aucune caméra.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {editing && <AnprCameraDialog camera={editing.camera} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); loadAll(); }} />}

      <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function LocalListImportButtons({ camId, target, onImported }) {
  const token = encodeURIComponent(localStorage.getItem("mg_token") || "");
  const [importing, setImporting] = useState(false);
  const handleImport = async (file) => {
    if (!file) return;
    setImporting(true);
    try {
      const fd = new FormData(); fd.append("csv_file", file);
      const { data } = await api.post(`/plugins/anpr/cameras/${camId}/lists/import?target=${target}`, fd,
        { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`${target} : ${data.added} plaque(s) ajoutée(s) (total ${data.total})`);
      onImported?.(data.added);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Import échoué"); }
    finally { setImporting(false); }
  };
  return (
    <div className="flex items-center gap-1.5 mt-1">
      <a href={`${process.env.REACT_APP_BACKEND_URL}/api/plugins/anpr/cameras/${camId}/lists/export?target=${target}&token=${token}`}
         className="text-[10px] px-2 py-0.5 border border-border hover:bg-secondary flex items-center gap-1" data-testid={`local-${target}-export`}>
        <Save size={10} /> Export CSV
      </a>
      <label className="text-[10px] px-2 py-0.5 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10 flex items-center gap-1 cursor-pointer" data-testid={`local-${target}-import`}>
        {importing ? <Loader2 size={10} className="animate-spin" /> : <Plus size={10} />} Import CSV
        <input type="file" accept=".csv,.txt" className="hidden"
                onChange={(e) => { handleImport(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
    </div>
  );
}


function AnprCameraDialog({ camera, onClose, onSaved }) {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [roiOpen, setRoiOpen] = useState(false);
  const [wlText, setWlText] = useState("");
  const [blText, setBlText] = useState("");
  const snapshotUrl = `${process.env.REACT_APP_BACKEND_URL}/api/plugins/_helpers/camera-snapshot/${camera.id}?_=${Date.now()}`;

  useEffect(() => {
    api.get(`/plugins/anpr/cameras/${camera.id}`).then((r) => {
      setCfg(r.data);
      setWlText((r.data.whitelist_local || []).join("\n"));
      setBlText((r.data.blacklist_local || []).join("\n"));
    }).catch(() => {});
  }, [camera.id]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...cfg,
        whitelist_local: wlText.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
        blacklist_local: blText.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
        min_confidence: Number(cfg.min_confidence),
      };
      await api.put(`/plugins/anpr/cameras/${camera.id}`, payload);
      toast.success("Configuration ANPR caméra enregistrée");
      onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec sauvegarde"); }
    finally { setSaving(false); }
  };

  if (!cfg) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4">
        <div className="bg-card border border-border w-full max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="anpr-cam-dialog">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div>
              <div className="font-head font-semibold">ANPR — {camera.name}</div>
              <div className="text-xs text-muted-foreground">{camera.site_name || "—"}</div>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="anpr-dialog-close"><XCircle size={16} /></button>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Activée pour cette caméra">
              <label className="flex items-center gap-2 mt-1"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="anpr-cam-enabled" /> Analyser les plaques</label>
            </Field>
            <Field label="Confiance mini. locale" hint="0 = utilise la config globale">
              <input type="number" step="0.05" min="0" max="0.95" value={cfg.min_confidence} onChange={(e) => setCfg({ ...cfg, min_confidence: e.target.value })} className="inp mono" />
            </Field>
            <Field label="Zone de lecture (ROI polygone)" hint="Vide = toute l'image. Sinon, seul l'intérieur du polygone est analysé.">
              <div className="flex items-center gap-2">
                <span className="mono text-xs">{cfg.roi_polygon?.length || 0} pts</span>
                <button onClick={() => setRoiOpen(true)} className="text-xs px-2 py-1 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10 flex items-center gap-1" data-testid="anpr-roi-open">
                  <Waypoints size={12} /> Dessiner la ROI
                </button>
                {cfg.roi_polygon?.length > 0 && (
                  <button onClick={() => setCfg({ ...cfg, roi_polygon: [] })} className="text-xs px-2 py-1 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10 flex items-center gap-1">
                    <Trash2 size={12} /> Effacer
                  </button>
                )}
              </div>
            </Field>
            <Field label="Pays (surcharge)" hint="Vide = config globale">
              <select value={cfg.country_override} onChange={(e) => setCfg({ ...cfg, country_override: e.target.value })} className="inp">
                <option value="">— Global —</option>
                {COUNTRIES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
              </select>
            </Field>
            <Field label="Whitelist locale (plaques autorisées)" hint="Une par ligne">
              <textarea rows={4} value={wlText} onChange={(e) => setWlText(e.target.value)} className="inp mono" placeholder="AB-123-CD&#10;XY-456-ZZ" data-testid="anpr-cam-wl" />
              <LocalListImportButtons camId={camera.id} target="whitelist" onImported={(added) => {
                if (added > 0) { setWlText((prev) => prev); toast.info("Rechargez la config pour voir les plaques importées"); }
              }} />
            </Field>
            <Field label="Blacklist locale (alerte immédiate)" hint="Une par ligne">
              <textarea rows={4} value={blText} onChange={(e) => setBlText(e.target.value)} className="inp mono" placeholder="FG-789-HI" data-testid="anpr-cam-bl" />
              <LocalListImportButtons camId={camera.id} target="blacklist" onImported={() => {}} />
            </Field>
          </div>
          <div className="p-4 border-t border-border flex justify-end gap-2">
            <button onClick={onClose} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">Annuler</button>
            <button onClick={save} disabled={saving} className="flex items-center gap-1.5 text-sm px-3 py-1.5 bg-[#0044FF] text-white disabled:opacity-50" data-testid="anpr-cam-save">
              {saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer
            </button>
          </div>
        </div>
      </div>
      {roiOpen && (
        <PolygonEditor
          imageSrc={snapshotUrl}
          initialPolygon={cfg.roi_polygon || []}
          title={`ROI ANPR — ${camera.name}`}
          onSave={(pts) => { setCfg({ ...cfg, roi_polygon: pts }); setRoiOpen(false); }}
          onCancel={() => setRoiOpen(false)} />
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════
// ByteTrack
// ═══════════════════════════════════════════════════════════════════
function TrackingSettings({ onSaved }) {
  const { can } = useApp();
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.get("/plugins/tracking/config").then((r) => setCfg(r.data)).catch(() => {}); }, []);
  if (!cfg) return <p className="text-muted-foreground">Chargement config tracking…</p>;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/plugins/tracking/config", {
        ...cfg,
        track_thresh: Number(cfg.track_thresh),
        match_thresh: Number(cfg.match_thresh),
        track_buffer: Number(cfg.track_buffer),
        min_box_area: Number(cfg.min_box_area),
        id_persist_seconds: Number(cfg.id_persist_seconds),
      });
      setCfg(data); toast.success("Config ByteTrack enregistrée"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec sauvegarde"); }
    finally { setSaving(false); }
  };
  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center gap-2 mb-3"><Activity size={18} className="text-[#0044FF]" /><span className="font-head font-semibold">Paramètres ByteTrack</span></div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Field label="Activer ByteTrack">
          <label className="flex items-center gap-2 mt-1"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="bt-enabled" /> Attribuer des IDs persistants</label>
        </Field>
        <Field label="Seuil d'activation (track_thresh)" hint="0.1 → 0.9"><input type="number" step="0.05" min="0.1" max="0.9" value={cfg.track_thresh} onChange={(e) => setCfg({ ...cfg, track_thresh: e.target.value })} className="inp mono" data-testid="bt-thresh" /></Field>
        <Field label="Seuil matching (match_thresh)" hint="0.5 → 0.95"><input type="number" step="0.05" min="0.5" max="0.95" value={cfg.match_thresh} onChange={(e) => setCfg({ ...cfg, match_thresh: e.target.value })} className="inp mono" /></Field>
        <Field label="Buffer trames (track_buffer)" hint="5 → 300"><input type="number" min="5" max="300" value={cfg.track_buffer} onChange={(e) => setCfg({ ...cfg, track_buffer: e.target.value })} className="inp mono" /></Field>
        <Field label="Aire mini bbox (px²)"><input type="number" min="10" max="10000" value={cfg.min_box_area} onChange={(e) => setCfg({ ...cfg, min_box_area: e.target.value })} className="inp mono" /></Field>
        <Field label="Persistance ID (s)" hint="Durée max de conservation d'un ID"><input type="number" min="5" max="600" value={cfg.id_persist_seconds} onChange={(e) => setCfg({ ...cfg, id_persist_seconds: e.target.value })} className="inp mono" data-testid="bt-persist" /></Field>
      </div>
      <button onClick={save} disabled={saving || !can("admin")} className="mt-3 flex items-center gap-1.5 px-3 py-1.5 bg-[#0044FF] text-white text-sm disabled:opacity-50" data-testid="bt-save">
        {saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Appliquer
      </button>
      <p className="text-[10px] text-muted-foreground mt-2">Les IDs sont attribués en temps réel par ByteTrack (via <span className="mono">supervision</span>) et attachés à chaque événement + overlay Live.</p>
      <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Face Recognition
// ═══════════════════════════════════════════════════════════════════
function FaceRecognitionSettings({ onSaved }) {
  const { can } = useApp();
  const [cfg, setCfg] = useState(null);
  const [faces, setFaces] = useState([]);
  const [avail, setAvail] = useState(null);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(null);
  const loadAll = async () => {
    const [c, l, a] = await Promise.all([
      api.get("/plugins/face_recognition/config"),
      api.get("/plugins/face_recognition/faces"),
      api.get("/plugins/face_recognition/availability"),
    ]);
    setCfg(c.data); setFaces(l.data); setAvail(a.data);
  };
  useEffect(() => { loadAll().catch(() => {}); }, []);
  if (!cfg) return <p className="text-muted-foreground">Chargement…</p>;

  const save = async () => {
    setSaving(true);
    try { const { data } = await api.put("/plugins/face_recognition/config", { ...cfg, distance_threshold: Number(cfg.distance_threshold) }); setCfg(data); toast.success("Config enregistrée"); onSaved?.(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
    finally { setSaving(false); }
  };
  const addFace = async () => {
    if (!newName.trim()) return;
    try { await api.post("/plugins/face_recognition/faces", { name: newName, watchlist: false }); setNewName(""); loadAll(); toast.success("Visage ajouté — cliquez sur 'Photo' pour importer une image"); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const delFace = async (id) => {
    if (!confirm("Supprimer ce visage ?")) return;
    try { await api.delete(`/plugins/face_recognition/faces/${id}`); loadAll(); toast.success("Visage supprimé"); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const uploadPhoto = async (faceId, file) => {
    if (!file) return;
    setUploading(faceId);
    try {
      const fd = new FormData(); fd.append("photo", file);
      const { data } = await api.post(`/plugins/face_recognition/faces/${faceId}/photo`, fd,
                                        { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Embedding ${data.embedding_dim}D extrait (det_score=${(data.meta?.det_score || 0).toFixed(2)})`);
      loadAll();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Extraction échouée"); }
    finally { setUploading(null); }
  };
  return (
    <div className="space-y-4">
      {/* État bibliothèque */}
      {avail && (
        <div className={"border p-3 text-xs " + (avail.installed ? "border-[#00E676] bg-[#00E676]/5" : "border-[#FFB800] bg-[#FFB800]/5")} data-testid="face-availability">
          <div className="flex items-center gap-2 font-head">
            {avail.installed ? <CheckCircle2 size={14} className="text-[#00E676]" /> : <AlertTriangle size={14} className="text-[#FFB800]" />}
            <b>{avail.installed ? `Bibliothèque installée : ${avail.provider}` : "Bibliothèque non installée"}</b>
          </div>
          <p className="mt-1 text-muted-foreground leading-relaxed">{avail.notes}</p>
        </div>
      )}
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center gap-2 mb-3"><ScanFace size={18} className="text-[#A855F7]" /><span className="font-head font-semibold">Reconnaissance faciale</span></div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Activer">
            <label className="flex items-center gap-2 mt-1"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} data-testid="face-enabled" disabled={!avail?.installed} /> Actif</label>
          </Field>
          <Field label="Seuil similarité (cosine)" hint="0.5 → 0.7 (plus haut = plus strict)"><input type="number" step="0.05" min="0.3" max="0.9" value={cfg.distance_threshold} onChange={(e) => setCfg({ ...cfg, distance_threshold: e.target.value })} className="inp mono" /></Field>
          <Field label="Modèle"><select value={cfg.model_name} onChange={(e) => setCfg({ ...cfg, model_name: e.target.value })} className="inp"><option value="hog">buffalo_s (CPU, léger)</option><option value="cnn">buffalo_l (CPU/GPU, précis)</option></select></Field>
          <Field label="Alertes">
            <label className="flex items-center gap-2 text-sm mt-1"><input type="checkbox" checked={cfg.alert_on_watchlist} onChange={(e) => setCfg({ ...cfg, alert_on_watchlist: e.target.checked })} /> Sur liste de surveillance</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.alert_on_unknown} onChange={(e) => setCfg({ ...cfg, alert_on_unknown: e.target.checked })} /> Sur visage inconnu</label>
          </Field>
        </div>
        <button onClick={save} disabled={saving || !can("admin")} className="mt-3 flex items-center gap-1.5 px-3 py-1.5 bg-[#0044FF] text-white text-sm disabled:opacity-50" data-testid="face-cfg-save">
          {saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer
        </button>
        <p className="text-[10px] text-[#FFB800] mt-2 border-l-2 border-[#FFB800] pl-2">
          Note légale : la reconnaissance faciale n&apos;est utilisable qu&apos;en accord avec le RGPD / cadre local.
        </p>
      </div>
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center gap-2 mb-3"><Activity size={18} /><span className="font-head font-semibold">Base de visages</span></div>
        <div className="flex gap-2 mb-3">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Nom du visage" className="inp flex-1" data-testid="face-new-name" />
          <button onClick={addFace} className="text-sm px-3 py-1.5 bg-[#0044FF] text-white flex items-center gap-1" data-testid="face-add"><Plus size={12} /> Ajouter</button>
        </div>
        <ul className="divide-y divide-border">
          {faces.map((f) => (
            <li key={f.id} className="py-2 flex items-center gap-3 text-sm">
              <div className="w-12 h-12 shrink-0 bg-secondary border border-border flex items-center justify-center overflow-hidden">
                {f.thumbnail ? <img src={f.thumbnail} alt={f.name} className="w-full h-full object-cover" /> : <ScanFace size={18} className="text-muted-foreground" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2"><b className="truncate">{f.name}</b>{f.watchlist && <span className="text-[9px] text-[#FF3333] border border-[#FF3333] px-1.5">SURVEILLANCE</span>}{!f.thumbnail && <span className="text-[9px] text-[#FFB800]">SANS PHOTO</span>}</div>
                {f.photo_meta && <div className="text-[10px] mono text-muted-foreground">det_score={(f.photo_meta.det_score || 0).toFixed(2)} · bbox=[{(f.photo_meta.bbox || []).join(",")}]</div>}
              </div>
              <label className="text-xs px-2 py-1 border border-border hover:bg-secondary cursor-pointer flex items-center gap-1" data-testid={`face-upload-${f.id}`}>
                {uploading === f.id ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />} Photo
                <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadPhoto(f.id, e.target.files?.[0])} disabled={!avail?.installed} />
              </label>
              <button onClick={() => delFace(f.id)} className="text-[#FF3333] hover:opacity-80"><Trash2 size={14} /></button>
            </li>
          ))}
          {faces.length === 0 && <li className="py-3 text-muted-foreground text-center">Aucun visage enregistré.</li>}
        </ul>
      </div>
      <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Parking — zones polygonales par caméra
// ═══════════════════════════════════════════════════════════════════
function ParkingSettings({ onSaved }) {
  const [zones, setZones] = useState([]);
  const [cams, setCams] = useState([]);
  const [dialog, setDialog] = useState(null); // { mode: 'new'|'edit', zone }
  const loadAll = async () => {
    const [z, c] = await Promise.all([api.get("/plugins/parking/zones"), api.get("/cameras")]);
    setZones(z.data); setCams(c.data);
  };
  useEffect(() => { loadAll().catch(() => {}); }, []);
  const del = async (id) => {
    if (!confirm("Supprimer cette zone ?")) return;
    try { await api.delete(`/plugins/parking/zones/${id}`); loadAll(); toast.success("Zone supprimée"); onSaved?.(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  return (
    <div className="space-y-4">
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2"><Car size={18} className="text-[#00E676]" /><span className="font-head font-semibold">Zones de stationnement</span></div>
          <button onClick={() => setDialog({ mode: "new" })} className="text-sm px-3 py-1.5 bg-[#0044FF] text-white flex items-center gap-1" data-testid="parking-new"><Plus size={12} /> Nouvelle zone</button>
        </div>
        <ul className="divide-y divide-border">
          {zones.map((z) => (
            <li key={z.id} className="py-2 flex items-center justify-between text-sm">
              <div>
                <span className="font-medium">{z.name}</span>
                <span className="text-xs text-muted-foreground ml-2">· {z.camera_name} · {z.polygon?.length || 0} pts · capacité {z.capacity}</span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setDialog({ mode: "edit", zone: z })} className="text-xs px-2 py-1 border border-border hover:bg-secondary"><Edit3 size={11} /></button>
                <button onClick={() => del(z.id)} className="text-[#FF3333]"><Trash2 size={14} /></button>
              </div>
            </li>
          ))}
          {zones.length === 0 && <li className="py-4 text-center text-muted-foreground">Aucune zone. Cliquez sur « Nouvelle zone » pour dessiner une zone sur une caméra.</li>}
        </ul>
      </div>
      {dialog && <ParkingZoneDialog zone={dialog.zone} cams={cams} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); loadAll(); onSaved?.(); }} />}
    </div>
  );
}

function ParkingZoneDialog({ zone, cams, onClose, onSaved }) {
  const [name, setName] = useState(zone?.name || "");
  const [cameraId, setCameraId] = useState(zone?.camera_id || (cams[0]?.id || ""));
  const [capacity, setCapacity] = useState(zone?.capacity || 10);
  const [polygon, setPolygon] = useState(zone?.polygon || []);
  const [poly, setPoly] = useState(false);
  const [saving, setSaving] = useState(false);
  const snapshotUrl = cameraId ? `${process.env.REACT_APP_BACKEND_URL}/api/plugins/_helpers/camera-snapshot/${cameraId}?_=${Date.now()}` : null;
  const save = async () => {
    if (!name.trim() || !cameraId || polygon.length < 3) { toast.error("Nom, caméra et polygone (≥3 pts) requis"); return; }
    setSaving(true);
    try {
      const payload = { name, camera_id: cameraId, capacity: Number(capacity), polygon };
      if (zone) await api.put(`/plugins/parking/zones/${zone.id}`, payload);
      else await api.post("/plugins/parking/zones", payload);
      toast.success("Zone enregistrée"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4">
        <div className="bg-card border border-border w-full max-w-lg">
          <div className="p-4 border-b border-border flex items-center justify-between"><div className="font-head font-semibold">{zone ? "Modifier zone" : "Nouvelle zone"}</div><button onClick={onClose}><XCircle size={16} /></button></div>
          <div className="p-4 space-y-3">
            <Field label="Nom"><input value={name} onChange={(e) => setName(e.target.value)} className="inp" data-testid="parking-zone-name" /></Field>
            <Field label="Caméra"><select value={cameraId} onChange={(e) => setCameraId(e.target.value)} className="inp" data-testid="parking-zone-cam"><option value="">— Sélectionner —</option>{cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label="Capacité (nombre de places)"><input type="number" min="1" value={capacity} onChange={(e) => setCapacity(e.target.value)} className="inp mono" /></Field>
            <Field label="Polygone" hint="Dessiné sur snapshot de la caméra">
              <div className="flex items-center gap-2">
                <span className="mono text-xs">{polygon.length} pts</span>
                <button onClick={() => setPoly(true)} disabled={!cameraId} className="text-xs px-2 py-1 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10 disabled:opacity-40 flex items-center gap-1" data-testid="parking-poly-open"><Waypoints size={12} /> Dessiner</button>
              </div>
            </Field>
          </div>
          <div className="p-4 border-t border-border flex justify-end gap-2">
            <button onClick={onClose} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">Annuler</button>
            <button onClick={save} disabled={saving} className="flex items-center gap-1.5 text-sm px-3 py-1.5 bg-[#0044FF] text-white disabled:opacity-50" data-testid="parking-zone-save">{saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer</button>
          </div>
        </div>
      </div>
      {poly && (
        <PolygonEditor imageSrc={snapshotUrl} initialPolygon={polygon} title={`Zone parking — ${name || "sans nom"}`}
          onSave={(p) => { setPolygon(p); setPoly(false); }} onCancel={() => setPoly(false)} />
      )}
      <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Access Control
// ═══════════════════════════════════════════════════════════════════
function AccessControlSettings({ onSaved }) {
  const [items, setItems] = useState([]);
  const [dialog, setDialog] = useState(null);
  const load = () => api.get("/plugins/access_control/controllers").then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const del = async (id) => {
    if (!confirm("Supprimer ce contrôleur ?")) return;
    try { await api.delete(`/plugins/access_control/controllers/${id}`); load(); toast.success("Contrôleur supprimé"); onSaved?.(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const test = async (id) => {
    try { const r = await api.post(`/plugins/access_control/controllers/${id}/test`); toast[r.data.status === "online" ? "success" : "error"](`${r.data.ip}:${r.data.port} → ${r.data.status}`); load(); }
    catch (e) { toast.error("Test échoué"); }
  };
  return (
    <div className="space-y-4">
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2"><DoorOpen size={18} className="text-[#A855F7]" /><span className="font-head font-semibold">Contrôleurs (barrières, portes, lecteurs)</span></div>
          <button onClick={() => setDialog({})} className="text-sm px-3 py-1.5 bg-[#0044FF] text-white flex items-center gap-1" data-testid="ac-new"><Plus size={12} /> Ajouter</button>
        </div>
        <ul className="divide-y divide-border">
          {items.map((c) => (
            <li key={c.id} className="py-2 flex items-center justify-between text-sm">
              <div>
                <span className="font-medium">{c.name}</span>
                <span className="ml-2 text-xs text-muted-foreground">{c.kind} · {c.protocol}://{c.ip}:{c.port}</span>
                {c.status && <span className={"ml-2 text-[10px] mono " + (c.status === "online" ? "text-[#00E676]" : "text-[#FF3333]")}>{c.status.toUpperCase()}</span>}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => test(c.id)} className="text-xs px-2 py-1 border border-border hover:bg-secondary"><Wifi size={11} /></button>
                <button onClick={() => setDialog({ item: c })} className="text-xs px-2 py-1 border border-border hover:bg-secondary"><Edit3 size={11} /></button>
                <button onClick={() => del(c.id)} className="text-[#FF3333]"><Trash2 size={14} /></button>
              </div>
            </li>
          ))}
          {items.length === 0 && <li className="py-4 text-center text-muted-foreground">Aucun contrôleur.</li>}
        </ul>
      </div>
      {dialog && <AcDialog item={dialog.item} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); load(); onSaved?.(); }} />}
    </div>
  );
}

function AcDialog({ item, onClose, onSaved }) {
  const [f, setF] = useState(item || { name: "", kind: "gate", ip: "", port: 80, protocol: "http", site_id: "", linked_camera_id: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...f, port: Number(f.port) };
      if (item?.id) await api.put(`/plugins/access_control/controllers/${item.id}`, payload);
      else await api.post("/plugins/access_control/controllers", payload);
      toast.success("Contrôleur enregistré"); onSaved?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border w-full max-w-lg" data-testid="ac-dialog">
        <div className="p-4 border-b border-border flex items-center justify-between"><div className="font-head font-semibold">{item ? "Modifier contrôleur" : "Nouveau contrôleur"}</div><button onClick={onClose}><XCircle size={16} /></button></div>
        <div className="p-4 grid grid-cols-2 gap-3">
          <Field label="Nom"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="inp" data-testid="ac-name" /></Field>
          <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} className="inp"><option value="gate">Portail</option><option value="door">Porte</option><option value="barrier">Barrière</option><option value="reader">Lecteur</option></select></Field>
          <Field label="Adresse IP"><input value={f.ip} onChange={(e) => setF({ ...f, ip: e.target.value })} className="inp mono" placeholder="192.168.1.50" /></Field>
          <Field label="Port"><input type="number" value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} className="inp mono" /></Field>
          <Field label="Protocole"><select value={f.protocol} onChange={(e) => setF({ ...f, protocol: e.target.value })} className="inp"><option value="http">HTTP</option><option value="wiegand">Wiegand</option><option value="osdp">OSDP</option><option value="mqtt">MQTT</option></select></Field>
          <Field label="Notes"><input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className="inp" /></Field>
        </div>
        <div className="p-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">Annuler</button>
          <button onClick={save} disabled={saving} className="flex items-center gap-1.5 text-sm px-3 py-1.5 bg-[#0044FF] text-white disabled:opacity-50" data-testid="ac-save">{saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer</button>
        </div>
        <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Sensor (thermal / radar / drone) — CRUD manuel
// ═══════════════════════════════════════════════════════════════════
function SensorSettings({ kind, label, Icon, onSaved }) {
  const [items, setItems] = useState([]);
  const [dialog, setDialog] = useState(null);
  const load = () => api.get(`/plugins/${kind}/sensors`).then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { load(); }, [kind]);
  const del = async (id) => {
    if (!confirm(`Supprimer ce capteur ${label} ?`)) return;
    try { await api.delete(`/plugins/${kind}/sensors/${id}`); load(); toast.success("Capteur supprimé"); onSaved?.(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><Icon size={18} className="text-[#FFB800]" /><span className="font-head font-semibold">Capteurs {label}</span></div>
        <button onClick={() => setDialog({})} className="text-sm px-3 py-1.5 bg-[#0044FF] text-white flex items-center gap-1"><Plus size={12} /> Ajouter</button>
      </div>
      <ul className="divide-y divide-border">
        {items.map((s) => (
          <li key={s.id} className="py-2 flex items-center justify-between text-sm">
            <div><span className="font-medium">{s.name}</span><span className="ml-2 text-xs text-muted-foreground">{s.protocol}://{s.ip}:{s.port || "—"}</span></div>
            <button onClick={() => del(s.id)} className="text-[#FF3333]"><Trash2 size={14} /></button>
          </li>
        ))}
        {items.length === 0 && <li className="py-4 text-center text-muted-foreground">Aucun capteur {label} déclaré.</li>}
      </ul>
      {dialog && (
        <SensorDialog kind={kind} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); load(); onSaved?.(); }} />
      )}
    </div>
  );
}

function SensorDialog({ kind, onClose, onSaved }) {
  const [f, setF] = useState({ name: "", kind, ip: "", port: 0, protocol: "http", notes: "" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!f.name.trim()) return toast.error("Nom requis");
    setSaving(true);
    try { await api.post(`/plugins/${kind}/sensors`, { ...f, port: Number(f.port) }); toast.success("Capteur ajouté"); onSaved?.(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="p-4 border-b border-border flex items-center justify-between"><div className="font-head font-semibold">Nouveau capteur</div><button onClick={onClose}><XCircle size={16} /></button></div>
        <div className="p-4 space-y-3">
          <Field label="Nom"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="inp" /></Field>
          <Field label="IP"><input value={f.ip} onChange={(e) => setF({ ...f, ip: e.target.value })} className="inp mono" /></Field>
          <Field label="Port"><input type="number" value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} className="inp mono" /></Field>
          <Field label="Protocole"><input value={f.protocol} onChange={(e) => setF({ ...f, protocol: e.target.value })} className="inp" /></Field>
          <Field label="Notes"><textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className="inp" /></Field>
        </div>
        <div className="p-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">Annuler</button>
          <button onClick={save} disabled={saving} className="flex items-center gap-1.5 text-sm px-3 py-1.5 bg-[#0044FF] text-white disabled:opacity-50">{saving && <Loader2 size={12} className="animate-spin" />} <Save size={13} /> Enregistrer</button>
        </div>
        <style>{`.inp{width:100%;padding:0.45rem 0.6rem;background:hsl(var(--background));border:1px solid hsl(var(--input));font-size:0.85rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
      </div>
    </div>
  );
}
