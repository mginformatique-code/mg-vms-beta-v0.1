import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { Activity, AlertTriangle, CheckCircle2, Download, Filter, RefreshCw, ChevronRight, Info, X, Cpu, Zap } from "lucide-react";

const CAUSE_COLORS = {
  "Timeout RTSP": "#FFB800",
  "Authentification refusée": "#FF3333",
  "Caméra hors ligne": "#FF3333",
  "Erreur DNS": "#FF3333",
  "GOP corrompu": "#FF66CC",
  "Trop de pertes réseau": "#FFB800",
  "Flux interrompu": "#FFB800",
  "Flux RTSP invalide": "#FF3333",
  "Erreur ONVIF": "#FFB800",
  "Crash go2rtc": "#FF3333",
  "Saturation GPU": "#FF66CC",
  "Mémoire insuffisante": "#FF3333",
  "Saturation CPU": "#FFB800",
  "Exception Python": "#FF3333",
  "TCP réinitialisé": "#FFB800",
  "Erreur UDP": "#FFB800",
  "Caméra redémarrée": "#00E5FF",
  "Reconnexion automatique": "#00E676",
  "Cause inconnue": "#666",
};

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} j`;
}

function CauseBadge({ cause, confidence }) {
  const color = CAUSE_COLORS[cause] || "#666";
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] mono font-bold border" style={{ borderColor: color, color }} data-testid="cause-badge">
      {cause}
      {confidence != null && confidence > 0 && <span className="text-white/60">({confidence}%)</span>}
    </span>
  );
}

function IncidentRow({ item, onDetail }) {
  const isReconnect = item.event_type === "reconnect";
  const dt = item.timestamp ? new Date(item.timestamp) : null;
  return (
    <tr onClick={() => onDetail(item)} className="border-b border-border hover:bg-secondary/50 cursor-pointer" data-testid="incident-row">
      <td className="px-3 py-2 whitespace-nowrap">
        {isReconnect
          ? <CheckCircle2 size={14} className="text-[#00E676] inline mr-1" />
          : <AlertTriangle size={14} className="text-[#FF3333] inline mr-1" />}
        <span className="text-[11px] mono">{dt ? dt.toLocaleString("fr-FR") : "—"}</span>
      </td>
      <td className="px-3 py-2 text-xs font-medium">{item.camera_name || item.camera_id}</td>
      <td className="px-3 py-2 text-xs text-muted-foreground">{item.site_name || "—"}</td>
      <td className="px-3 py-2"><CauseBadge cause={item.cause} confidence={item.cause_confidence} /></td>
      <td className="px-3 py-2 text-xs mono text-muted-foreground">{fmtDuration(item.uptime_before_incident_s)}</td>
      <td className="px-3 py-2 text-xs mono">
        {isReconnect
          ? <span className="text-[#00E676]">Reconnecté · {fmtDuration(item.reconnect_duration_s)} · {item.reconnect_attempts || 1} essai(s)</span>
          : (item.reconnected
              ? <span className="text-[#00E676]">Résolu · {fmtDuration(item.reconnect_duration_s)}</span>
              : <span className="text-[#FF3333]">En cours…</span>)}
      </td>
      <td className="px-3 py-2 text-right"><ChevronRight size={14} className="text-muted-foreground" /></td>
    </tr>
  );
}

function IncidentDetail({ item, onClose }) {
  if (!item) return null;
  const dt = item.timestamp ? new Date(item.timestamp) : null;
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose} data-testid="incident-detail-modal">
      <div className="max-w-3xl w-full bg-card border border-border max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Incident diagnostic</div>
            <div className="font-head font-bold text-lg">{item.camera_name || item.camera_id}</div>
            <div className="text-xs mono text-muted-foreground">{dt ? dt.toLocaleString("fr-FR") : "—"}</div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-secondary"><X size={16} /></button>
        </div>
        <div className="p-4 space-y-4 text-sm">
          <section>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Cause probable</div>
            <div className="flex items-center gap-2">
              <CauseBadge cause={item.cause} confidence={item.cause_confidence} />
              <span className="text-xs text-muted-foreground">{item.cause_detail || ""}</span>
            </div>
          </section>
          <section className="grid grid-cols-2 gap-3">
            <Info2 label="Type" value={item.event_type} />
            <Info2 label="Source" value={item.error_source} />
            <Info2 label="État précédent" value={item.previous_state} />
            <Info2 label="État actuel" value={item.current_state} />
            <Info2 label="Uptime avant incident" value={fmtDuration(item.uptime_before_incident_s)} />
            <Info2 label="Temps depuis dernière frame" value={fmtDuration(item.time_since_last_frame_s)} />
            <Info2 label="Tentatives de reconnexion" value={item.reconnect_attempts ?? "—"} />
            <Info2 label="Durée de reconnexion" value={fmtDuration(item.reconnect_duration_s)} />
            <Info2 label="Reconnecté" value={item.reconnected ? "Oui" : (item.event_type === "reconnect" ? "Oui" : "En cours")} />
            <Info2 label="Profil ONVIF" value={item.profile_name || "—"} />
          </section>
          <section className="grid grid-cols-2 gap-3">
            <Info2 label="Codec" value={item.codec || "—"} />
            <Info2 label="Résolution" value={item.resolution || "—"} />
            <Info2 label="FPS demandé" value={item.fps_requested ?? "—"} />
            <Info2 label="FPS réel" value={item.fps_actual ?? "—"} />
            <Info2 label="Bitrate" value={item.bitrate_kbps ? `${item.bitrate_kbps} kbps` : "—"} />
            <Info2 label="Transport RTSP" value={(item.rtsp_transport || "").toUpperCase() || "—"} />
          </section>
          {item.url_masked && (
            <section>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">URL RTSP</div>
              <div className="text-[11px] mono bg-secondary p-2 break-all">{item.url_masked}</div>
            </section>
          )}
          {item.error_text && (
            <section>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Erreur brute ({item.error_text.length} caractères)</div>
              <pre className="text-[10px] mono bg-black text-white/80 p-3 max-h-64 overflow-auto whitespace-pre-wrap" data-testid="incident-raw-error">{item.error_text}</pre>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Info2({ label, value }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-xs mono mt-0.5">{String(value ?? "—")}</div>
    </div>
  );
}

function CameraSummaryCard({ camera, summary, onDownload }) {
  return (
    <div className="border border-border p-3" data-testid={`summary-${camera.id}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-sm font-medium">{camera.name}</div>
          <div className="text-[10px] text-muted-foreground">{camera.site_name || "—"}</div>
        </div>
        <button onClick={() => onDownload(camera)} className="p-1.5 hover:bg-secondary" title="Télécharger le rapport">
          <Download size={14} />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <span className="text-muted-foreground">Déconnexions (30j)</span>
          <div className="mono font-bold text-base" style={{ color: (summary?.disconnects_30d || 0) > 5 ? "#FF3333" : "#00E676" }}>
            {summary?.disconnects_30d ?? "—"}
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">MTBF</span>
          <div className="mono font-bold text-base">{summary?.mtbf_hours ? `${summary.mtbf_hours} h` : "∞"}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Reconnexion moy.</span>
          <div className="mono">{summary?.avg_reconnect_s ? `${summary.avg_reconnect_s} s` : "—"}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Reconnexions</span>
          <div className="mono">{summary?.reconnects_30d ?? "—"}</div>
        </div>
      </div>
      {summary?.top_causes && summary.top_causes.length > 0 && (
        <div className="mt-2 pt-2 border-t border-border">
          <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Causes fréquentes</div>
          <div className="flex flex-wrap gap-1">
            {summary.top_causes.slice(0, 3).map((c, i) => (
              <span key={i} className="text-[9px] mono px-1.5 py-0.5 border" style={{ borderColor: CAUSE_COLORS[c.cause] || "#666", color: CAUSE_COLORS[c.cause] || "#666" }}>
                {c.cause} × {c.count}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Diagnostics() {
  const { t } = useApp();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [cams, setCams] = useState([]);
  const [summaries, setSummaries] = useState({});
  const [filter, setFilter] = useState({ camera_id: "", cause: "", event_type: "" });
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (filter.camera_id) params.set("camera_id", filter.camera_id);
      if (filter.cause) params.set("cause", filter.cause);
      if (filter.event_type) params.set("event_type", filter.event_type);
      const { data } = await api.get(`/diagnostics/journal?${params}`);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) { toast.error("Chargement du journal échoué"); }
    finally { setLoading(false); }
  };

  const loadCams = async () => {
    const { data } = await api.get("/cameras");
    setCams(data);
    // Charge les résumés pour chaque caméra en parallèle
    const results = await Promise.allSettled(data.map((c) => api.get(`/diagnostics/camera/${c.id}/summary`)));
    const sm = {};
    data.forEach((c, i) => { if (results[i].status === "fulfilled") sm[c.id] = results[i].value.data; });
    setSummaries(sm);
  };

  useEffect(() => { load(); }, [filter]);
  useEffect(() => { loadCams(); }, []);

  const downloadReport = async (camera) => {
    try {
      const { data } = await api.get(`/diagnostics/camera/${camera.id}/report`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mgvms-diag-${camera.name.replace(/[^a-z0-9]/gi, "_")}-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapport téléchargé");
    } catch (e) { toast.error("Impossible de générer le rapport"); }
  };

  const uniqueCauses = Array.from(new Set(items.map((i) => i.cause).filter(Boolean)));

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Activity size={22} /> {t("nav.diagnostics")}
        </h1>
        <button onClick={load} disabled={loading} data-testid="reload-diag" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Actualiser
        </button>
      </div>

      {/* Vue résumé par caméra */}
      {cams.length > 0 && (
        <div className="mb-6">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Vue d&apos;ensemble par caméra (30 j)</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {cams.map((c) => (
              <CameraSummaryCard key={c.id} camera={c} summary={summaries[c.id]} onDownload={downloadReport} />
            ))}
          </div>
        </div>
      )}

      {/* Filtres */}
      <div className="border border-border p-3 mb-3 flex items-center gap-2 flex-wrap" data-testid="diag-filters">
        <Filter size={14} className="text-muted-foreground" />
        <select value={filter.camera_id} onChange={(e) => setFilter({ ...filter, camera_id: e.target.value })}
                className="px-2 py-1 text-xs bg-card border border-input" data-testid="filter-camera">
          <option value="">Toutes les caméras</option>
          {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filter.cause} onChange={(e) => setFilter({ ...filter, cause: e.target.value })}
                className="px-2 py-1 text-xs bg-card border border-input" data-testid="filter-cause">
          <option value="">Toutes les causes</option>
          {uniqueCauses.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filter.event_type} onChange={(e) => setFilter({ ...filter, event_type: e.target.value })}
                className="px-2 py-1 text-xs bg-card border border-input" data-testid="filter-event-type">
          <option value="">Tous les événements</option>
          <option value="disconnect">Déconnexions</option>
          <option value="reconnect">Reconnexions</option>
        </select>
        <span className="ml-auto text-xs text-muted-foreground mono">{total} incident(s)</span>
      </div>

      {/* Journal */}
      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-3 py-2">Date &amp; heure</th>
              <th className="px-3 py-2">Caméra</th>
              <th className="px-3 py-2">Site</th>
              <th className="px-3 py-2">Cause probable</th>
              <th className="px-3 py-2">Uptime avant</th>
              <th className="px-3 py-2">Reconnexion</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-muted-foreground text-sm">
                <Info size={14} className="inline mr-1" /> Aucun incident enregistré pour la période courante.
              </td></tr>
            ) : items.map((item) => (
              <IncidentRow key={item.id} item={item} onDetail={setDetail} />
            ))}
          </tbody>
        </table>
      </div>

      <IncidentDetail item={detail} onClose={() => setDetail(null)} />

      <FrameSourceSection />
      <AiHealthSection />
      <StreamsSyncSection />
      <StreamLifecycleSection />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section "Santé pipeline IA" — workers ffmpeg-CUDA persistants (frame_source)
// ══════════════════════════════════════════════════════════════════════════
function FrameSourceSection() {
  const [state, setState] = useState({ workers: {}, cuvid_available: false, mode: "auto" });
  const [cams, setCams] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [fs, cs] = await Promise.all([
        api.get("/diagnostics/frame-source"),
        api.get("/cameras"),
      ]);
      setState(fs.data || { workers: {} });
      setCams(cs.data || []);
    } catch (e) { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, []);

  const camName = (id) => cams.find((c) => c.id === id)?.name || id;
  const workers = Object.entries(state.workers || {});
  const modeBadge = state.mode === "cuda" ? { color: "#00E676", label: "CUDA forcé" }
                    : state.mode === "none" ? { color: "#666", label: "CPU forcé (env)" }
                    : state.cuvid_available ? { color: "#00E676", label: "GPU (NVDEC)" }
                    : { color: "#FFB800", label: "CPU (fallback)" };

  return (
    <div className="mt-8 border border-border bg-card p-4" data-testid="frame-source-section">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="font-head font-semibold text-lg flex items-center gap-2">
            <Zap size={16} className="text-[#00E5FF]" />
            Santé pipeline IA — workers ffmpeg
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Un worker <span className="mono">ffmpeg -hwaccel cuda</span> par caméra IA (décodage GPU NVDEC direct → numpy zéro-copie).
            Aucun transit MJPEG. Redémarrage automatique sur crash RTSP.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 border font-bold mono text-xs" style={{ borderColor: modeBadge.color, color: modeBadge.color }} data-testid="frame-source-mode">
            {modeBadge.label}
          </span>
          <button onClick={load} disabled={loading} className="px-2 py-1 text-xs border border-border hover:bg-secondary flex items-center gap-1">
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Rafraîchir
          </button>
        </div>
      </div>

      {workers.length === 0 ? (
        <div className="p-6 text-center text-muted-foreground text-sm border border-dashed border-border" data-testid="frame-source-empty">
          <Info size={16} className="inline mr-1" />
          Aucun worker actif. Les workers sont démarrés automatiquement pour les caméras réelles (non-démo) avec IA activée.
          {!state.cuvid_available && state.mode !== "none" && (
            <div className="mt-3 text-xs text-[#FFB800]">
              ⚠️ FFmpeg sans support cuvid détecté dans ce container — décodage CPU uniquement.
              Assurez-vous que le backend est bâti avec l&apos;image <span className="mono">nvidia/cuda</span> + FFmpeg NVDEC.
            </div>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs mono" data-testid="frame-source-table">
            <thead className="border-b border-border">
              <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-2 py-1.5">Caméra</th>
                <th className="px-2 py-1.5">Codec</th>
                <th className="px-2 py-1.5">Résolution</th>
                <th className="px-2 py-1.5">GPU</th>
                <th className="px-2 py-1.5">Restarts</th>
                <th className="px-2 py-1.5">Âge dernière frame</th>
                <th className="px-2 py-1.5">État</th>
                <th className="px-2 py-1.5">Dernière erreur</th>
              </tr>
            </thead>
            <tbody>
              {workers.map(([camId, w]) => {
                const age = w.last_frame_age_s;
                const ageColor = age == null ? "#666" : (age < 3 ? "#00E676" : age < 10 ? "#FFB800" : "#FF3333");
                const restartColor = w.restart_count > 5 ? "#FF3333" : w.restart_count > 1 ? "#FFB800" : "#00E676";
                return (
                  <tr key={camId} className="border-b border-border/40 hover:bg-secondary/30" data-testid={`frame-source-row-${camId}`}>
                    <td className="px-2 py-1.5 font-semibold">{camName(camId)}</td>
                    <td className="px-2 py-1.5 uppercase">{w.codec}</td>
                    <td className="px-2 py-1.5">{w.resolution}</td>
                    <td className="px-2 py-1.5">
                      <span className="px-1.5 py-0.5 border text-[10px] font-bold" style={{
                        borderColor: w.gpu ? "#00E676" : "#666", color: w.gpu ? "#00E676" : "#666" }}>
                        {w.gpu ? "CUDA" : "CPU"}
                      </span>
                    </td>
                    <td className="px-2 py-1.5" style={{ color: restartColor }}>{w.restart_count}×</td>
                    <td className="px-2 py-1.5" style={{ color: ageColor }}>
                      {age == null ? "—" : `${age.toFixed(1)}s`}
                    </td>
                    <td className="px-2 py-1.5">
                      {w.alive ? (
                        <span className="text-[#00E676] flex items-center gap-1"><CheckCircle2 size={12} /> actif</span>
                      ) : (
                        <span className="text-[#FF3333] flex items-center gap-1"><AlertTriangle size={12} /> mort</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-white/60 truncate max-w-md" title={w.last_error || ""}>{w.last_error || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section "Cycle de vie des streams" — journal circulaire en mémoire backend
// ══════════════════════════════════════════════════════════════════════════
const LIFECYCLE_ACTION_COLORS = {
  created: "#00E676",
  registered_idempotent: "#00E676",
  destroyed: "#FF3333",
  register_failed: "#FF3333",
  consumer_attached: "#00E5FF",
  consumer_detached: "#B47CFF",
  status_probe_ok: "#00E676",
  status_probe_fail: "#FFB800",
  status_offline_confirmed: "#FF3333",
  status_online_restored: "#00E676",
  stream_absent_from_go2rtc: "#FF3333",
  registering: "#FFB800",
  webrtc_negotiation: "#00E5FF",
  webrtc_answered: "#00E676",
  webrtc_failed: "#FF3333",
};

function StreamLifecycleSection() {
  const [cams, setCams] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [summary, setSummary] = useState({});
  const [entries, setEntries] = useState([]);
  const [failureCount, setFailureCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Charge la liste des caméras + résumé lifecycle
  useEffect(() => {
    api.get("/cameras").then((r) => {
      setCams(r.data || []);
      if (!selectedId && r.data?.length) setSelectedId(r.data[0].id);
    }).catch(() => setCams([]));
    api.get("/diagnostics/stream-lifecycle").then((r) => setSummary(r.data?.summary || {})).catch(() => {});
  }, []);

  // Charge le journal détaillé de la caméra sélectionnée + auto-refresh
  useEffect(() => {
    if (!selectedId) return;
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`/diagnostics/stream-lifecycle/${selectedId}?limit=100`);
        if (!alive) return;
        setEntries(data?.entries || []);
        setFailureCount(data?.consecutive_probe_failures || 0);
      } catch (e) { if (alive) { setEntries([]); setFailureCount(0); } }
      finally { if (alive) setLoading(false); }
    };
    load();
    if (!autoRefresh) return;
    const iv = setInterval(load, 5000);  // rafraîchissement toutes les 5 s
    return () => { alive = false; clearInterval(iv); };
  }, [selectedId, autoRefresh]);

  const selectedCam = cams.find((c) => c.id === selectedId);

  return (
    <div className="mt-8 border border-border bg-card p-4" data-testid="stream-lifecycle-section">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="font-head font-semibold text-lg flex items-center gap-2">
            <Activity size={16} className="text-[#00E5FF]" />
            Cycle de vie des streams (temps réel)
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Journal circulaire en mémoire (100 dernières transitions) — trace précisément qui crée, attache, détache ou détruit chaque flux caméra.
            Utilisez cet écran pour diagnostiquer les cycles de reconnexion.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs mono cursor-pointer" data-testid="lifecycle-autorefresh">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh 5 s
          </label>
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}
                  className="px-2 py-1 text-xs bg-background border border-input" data-testid="lifecycle-camera-select">
            {cams.map((c) => (
              <option key={c.id} value={c.id}>{c.name} · {c.site_name || "?"}</option>
            ))}
          </select>
        </div>
      </div>

      {/* KPIs de la caméra sélectionnée */}
      {selectedCam && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-xs">
          <div className="border border-border bg-background p-2">
            <div className="text-muted-foreground mono uppercase tracking-wider text-[10px]">Statut actuel</div>
            <div className={`mono font-bold ${selectedCam.status === "online" ? "text-[#00E676]" : "text-[#FF3333]"}`} data-testid="lifecycle-current-status">
              {selectedCam.status || "unknown"}
            </div>
          </div>
          <div className="border border-border bg-background p-2">
            <div className="text-muted-foreground mono uppercase tracking-wider text-[10px]">Échecs probe consécutifs</div>
            <div className={`mono font-bold ${failureCount === 0 ? "text-[#00E676]" : (failureCount >= 3 ? "text-[#FF3333]" : "text-[#FFB800]")}`} data-testid="lifecycle-fail-count">
              {failureCount}/3
              {failureCount > 0 && failureCount < 3 && <span className="text-white/50 text-[10px] ml-1">(hystérésis)</span>}
            </div>
          </div>
          <div className="border border-border bg-background p-2">
            <div className="text-muted-foreground mono uppercase tracking-wider text-[10px]">Entrées journal</div>
            <div className="mono font-bold" data-testid="lifecycle-entries-count">{entries.length}</div>
          </div>
          <div className="border border-border bg-background p-2">
            <div className="text-muted-foreground mono uppercase tracking-wider text-[10px]">Dernière action</div>
            <div className="mono text-[10px] truncate" title={entries[entries.length - 1]?.action}>
              {entries.length > 0 ? entries[entries.length - 1].action : "—"}
            </div>
          </div>
        </div>
      )}

      {/* Journal détaillé (chronologique, plus récent en bas) */}
      <div className="border border-border bg-background max-h-[500px] overflow-y-auto" data-testid="lifecycle-journal">
        {loading && entries.length === 0 && (
          <div className="p-4 text-center text-muted-foreground text-sm">
            <RefreshCw size={14} className="inline animate-spin mr-1" /> Chargement…
          </div>
        )}
        {!loading && entries.length === 0 && (
          <div className="p-6 text-center text-muted-foreground text-sm">
            <Info size={14} className="inline mr-1" /> Aucune transition enregistrée pour cette caméra depuis le démarrage du backend.
          </div>
        )}
        {entries.length > 0 && (
          <table className="w-full text-xs mono">
            <thead className="sticky top-0 bg-card border-b border-border">
              <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-2 py-1.5">Timestamp</th>
                <th className="px-2 py-1.5">Action</th>
                <th className="px-2 py-1.5">Raison</th>
                <th className="px-2 py-1.5">Origine</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => {
                const dt = e.ts ? new Date(e.ts) : null;
                const color = LIFECYCLE_ACTION_COLORS[e.action] || "#888";
                return (
                  <tr key={i} className="border-b border-border/40 hover:bg-secondary/30" data-testid={`lifecycle-entry-${i}`}>
                    <td className="px-2 py-1 text-white/60 whitespace-nowrap">
                      {dt ? dt.toLocaleTimeString("fr-FR", { hour12: false }) : ""}
                      <span className="text-white/30 ml-1 text-[9px]">
                        {dt ? "." + String(dt.getMilliseconds()).padStart(3, "0") : ""}
                      </span>
                    </td>
                    <td className="px-2 py-1">
                      <span className="px-1.5 py-0.5 border font-bold" style={{ borderColor: color, color }}>
                        {e.action}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-white/80 max-w-xl truncate" title={e.reason}>{e.reason || "—"}</td>
                    <td className="px-2 py-1 text-white/50 max-w-xs truncate" title={e.caller}>{e.caller || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Résumé toutes caméras */}
      {Object.keys(summary).length > 1 && (
        <div className="mt-4 text-xs">
          <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-1">Toutes les caméras (résumé)</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {Object.entries(summary).map(([camId, s]) => {
              const c = cams.find((x) => x.id === camId);
              return (
                <div key={camId} className="border border-border bg-background p-2 flex justify-between items-center cursor-pointer hover:border-[#00E5FF]"
                     onClick={() => setSelectedId(camId)} data-testid={`lifecycle-summary-${camId}`}>
                  <div>
                    <div className="mono font-semibold">{c?.name || camId}</div>
                    <div className="text-[10px] text-muted-foreground">{s.count} entrées · dernière : {s.last_action}</div>
                  </div>
                  <ChevronRight size={14} className="text-muted-foreground" />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// Badge component (extracted to avoid react/no-unstable-nested-components)
function AiBadge({ ok, label, testid }) {
  return (
    <span data-testid={testid} className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider mono"
          style={{ background: ok ? "#00E67620" : "#FF333320", color: ok ? "#00E676" : "#FF3333", border: `1px solid ${ok ? "#00E676" : "#FF3333"}` }}>
      {ok ? "✓" : "✗"} {label}
    </span>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section "Santé IA (temps réel)" — v2.21.0 Phase 0
// Poll `/api/diagnostics/ai-health` pour montrer YOLO / ALPR / torch / CUDA
// en badges verts/rouges avec message d'erreur exact si un modèle est KO.
// ══════════════════════════════════════════════════════════════════════════
function AiHealthSection() {
  const [h, setH] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/diagnostics/ai-health");
      setH(r.data);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);

  if (!h) {
    return (
      <div className="mt-8 border border-border bg-card p-4" data-testid="ai-health-section-loading">
        <h2 className="font-head font-semibold text-lg">Santé IA (temps réel)</h2>
        <p className="text-xs text-muted-foreground mt-2">Chargement…</p>
      </div>
    );
  }

  return (
    <div className="mt-8 border border-border bg-card p-4" data-testid="ai-health-section">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="font-head font-semibold text-lg flex items-center gap-2">
            <Zap size={16} className="text-[#00E5FF]" />
            Santé IA (temps réel)
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            État exact du pipeline de détection. Auto-refresh 5s. Si un composant est rouge, l&apos;erreur exacte est indiquée en dessous.
          </p>
        </div>
        <button onClick={load} disabled={loading} data-testid="ai-health-refresh"
                className="text-xs px-3 py-1 border border-border hover:border-[#00E5FF] disabled:opacity-50">
          <RefreshCw size={12} className={`inline mr-1 ${loading ? "animate-spin" : ""}`} />
          Actualiser
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <AiBadge ok={h.loop_alive} label="Boucle IA vivante" testid="ai-badge-loop" />
        <AiBadge ok={h.yolo_loaded} label="YOLO chargé" testid="ai-badge-yolo" />
        <AiBadge ok={h.alpr_loaded} label="LAPI/ANPR chargé" testid="ai-badge-alpr" />
        <AiBadge ok={h.torch_available} label={`PyTorch ${h.torch_version || "?"}`} testid="ai-badge-torch" />
        <AiBadge ok={h.torch_cuda_available} label={h.torch_cuda_available ? "CUDA actif" : "CPU"} testid="ai-badge-cuda" />
        {h.force_cpu_env && (
          <span data-testid="ai-badge-force-cpu" className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider mono"
                style={{ background: "#FFB80020", color: "#FFB800", border: "1px solid #FFB800" }}>
            ⚠ MGVMS_AI_FORCE_CPU=1
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Device effectif</div>
          <div className="mono font-semibold" data-testid="ai-device-effective">{h.device_effective || "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Cycles totaux</div>
          <div className="mono font-semibold" data-testid="ai-cycles-total">{h.cycles_total}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Modèle YOLO</div>
          <div className="mono">{h.yolo_model || "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Ultralytics</div>
          <div className="mono">{h.ultralytics_version || "—"}</div>
        </div>
      </div>

      {!h.yolo_loaded && h.yolo_error && (
        <div className="mt-4 p-3 bg-[#FF333310] border border-[#FF3333]" data-testid="ai-yolo-error">
          <div className="text-[10px] uppercase tracking-wider text-[#FF3333] font-semibold mb-1">Erreur YOLO ({h.yolo_load_attempts} tentative{h.yolo_load_attempts > 1 ? "s" : ""})</div>
          <div className="mono text-xs break-words">{h.yolo_error}</div>
        </div>
      )}
      {!h.alpr_loaded && h.alpr_error && (
        <div className="mt-2 p-3 bg-[#FF333310] border border-[#FF3333]" data-testid="ai-alpr-error">
          <div className="text-[10px] uppercase tracking-wider text-[#FF3333] font-semibold mb-1">Erreur LAPI ({h.alpr_load_attempts} tentative{h.alpr_load_attempts > 1 ? "s" : ""})</div>
          <div className="mono text-xs break-words">{h.alpr_error}</div>
        </div>
      )}
      {h.last_cycle_error && (
        <div className="mt-2 p-3 bg-[#FFB80010] border border-[#FFB800]" data-testid="ai-cycle-error">
          <div className="text-[10px] uppercase tracking-wider text-[#FFB800] font-semibold mb-1">Dernière erreur cycle</div>
          <div className="mono text-xs break-words">{h.last_cycle_error}</div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section "Réconciliation DB ↔ go2rtc" — v2.22.0 Phase 2 option (a)
// Vérifie que toutes les caméras DB sont bien provisionnées côté moteur vidéo.
// Bouton "Resynchroniser go2rtc" pour forcer un sync_all_streams().
// ══════════════════════════════════════════════════════════════════════════
function StreamsSyncSection() {
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(false);
  const [repairing, setRepairing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/diagnostics/streams-sync");
      setState(r.data);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  const repair = async () => {
    if (!confirm("Forcer la resynchronisation DB → go2rtc ? Cette action re-provisionne tous les flux caméra dans go2rtc (idempotent).")) return;
    setRepairing(true);
    try {
      const r = await api.post("/diagnostics/streams-sync/repair");
      setState(r.data);
      toast.success("Resynchronisation terminée");
    } catch (e) {
      toast.error(`Échec resync : ${e?.response?.data?.detail || e.message}`);
    } finally {
      setRepairing(false);
    }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, []);

  if (!state) {
    return (
      <div className="mt-8 border border-border bg-card p-4" data-testid="streams-sync-loading">
        <h2 className="font-head font-semibold text-lg">Réconciliation DB ↔ go2rtc</h2>
        <p className="text-xs text-muted-foreground mt-2">Chargement…</p>
      </div>
    );
  }

  const missing = state.missing_in_go2rtc || [];
  const drift = state.variant_drift || [];
  const orphans = state.orphan_in_go2rtc || [];
  const inSync = state.in_sync || [];
  const hasIssue = missing.length + drift.length + orphans.length > 0;

  return (
    <div className="mt-8 border border-border bg-card p-4" data-testid="streams-sync-section">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="font-head font-semibold text-lg flex items-center gap-2">
            <Activity size={16} className="text-[#00E5FF]" />
            Réconciliation DB ↔ go2rtc
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Vérifie que chaque caméra en base est bien provisionnée dans go2rtc (source unique = DB).
            Utile après un <span className="mono">docker restart go2rtc</span> ou un reset de conteneur.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} disabled={loading} data-testid="streams-sync-refresh"
                  className="text-xs px-3 py-1 border border-border hover:border-[#00E5FF] disabled:opacity-50">
            <RefreshCw size={12} className={`inline mr-1 ${loading ? "animate-spin" : ""}`} />
            Actualiser
          </button>
          <button onClick={repair} disabled={repairing || !state.go2rtc_reachable} data-testid="streams-sync-repair-btn"
                  className="text-xs px-3 py-1 border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF20] disabled:opacity-50 font-semibold">
            {repairing ? "Resynchronisation…" : "Resynchroniser go2rtc"}
          </button>
        </div>
      </div>

      {!state.go2rtc_reachable && (
        <div className="p-3 bg-[#FF333310] border border-[#FF3333] mb-3" data-testid="streams-sync-unreachable">
          <div className="text-[10px] uppercase tracking-wider text-[#FF3333] font-semibold mb-1">go2rtc injoignable</div>
          <div className="mono text-xs break-words">{state.go2rtc_error || "Aucune réponse HTTP"}</div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-4">
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Caméras DB</div>
          <div className="mono font-semibold text-lg" data-testid="streams-sync-db-count">{state.db_cameras_count}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Flux go2rtc</div>
          <div className="mono font-semibold text-lg" data-testid="streams-sync-go2rtc-count">{state.go2rtc_streams_count}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Alignés</div>
          <div className="mono font-semibold text-lg text-[#00E676]" data-testid="streams-sync-in-sync-count">{inSync.length}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider">Problèmes</div>
          <div className={`mono font-semibold text-lg ${hasIssue ? "text-[#FF3333]" : "text-[#00E676]"}`} data-testid="streams-sync-issues-count">
            {missing.length + drift.length + orphans.length}
          </div>
        </div>
      </div>

      {missing.length > 0 && (
        <div className="mb-3 p-3 bg-[#FF333310] border border-[#FF3333]" data-testid="streams-sync-missing">
          <div className="text-[10px] uppercase tracking-wider text-[#FF3333] font-semibold mb-2">
            {missing.length} caméra{missing.length > 1 ? "s" : ""} manquante{missing.length > 1 ? "s" : ""} dans go2rtc — cliquez &laquo;&nbsp;Resynchroniser go2rtc&nbsp;&raquo;
          </div>
          {missing.map((m) => (
            <div key={m.stream_name} className="mono text-xs">• {m.name} <span className="text-muted-foreground">({m.stream_name})</span></div>
          ))}
        </div>
      )}

      {drift.length > 0 && (
        <div className="mb-3 p-3 bg-[#FFB80010] border border-[#FFB800]" data-testid="streams-sync-drift">
          <div className="text-[10px] uppercase tracking-wider text-[#FFB800] font-semibold mb-2">
            {drift.length} caméra{drift.length > 1 ? "s" : ""} avec variantes HD/SD manquantes
          </div>
          {drift.map((d) => (
            <div key={d.stream_name} className="mono text-xs">
              • {d.name} <span className="text-muted-foreground">({d.stream_name})</span>
              <span className="ml-2">HD:{d.hd_present ? "✓" : "✗"} SD:{d.sd_present ? "✓" : "✗"}</span>
            </div>
          ))}
        </div>
      )}

      {orphans.length > 0 && (
        <div className="mb-3 p-3 bg-[#FFB80010] border border-[#FFB800]" data-testid="streams-sync-orphans">
          <div className="text-[10px] uppercase tracking-wider text-[#FFB800] font-semibold mb-2">
            {orphans.length} flux orphelin{orphans.length > 1 ? "s" : ""} dans go2rtc (caméra supprimée en DB)
          </div>
          {orphans.map((o) => (
            <div key={o.stream_name} className="mono text-xs">• {o.stream_name}</div>
          ))}
        </div>
      )}

      {!hasIssue && state.go2rtc_reachable && (
        <div className="p-3 bg-[#00E67610] border border-[#00E676]" data-testid="streams-sync-ok">
          <div className="flex items-center gap-2 text-[#00E676] text-xs font-semibold">
            <CheckCircle2 size={14} />
            DB et go2rtc alignés — {inSync.length} caméra{inSync.length > 1 ? "s" : ""} en synchronisation
          </div>
        </div>
      )}
    </div>
  );
}

