import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { Activity, AlertTriangle, CheckCircle2, Download, Filter, RefreshCw, ChevronRight, Info, X } from "lucide-react";

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
    </div>
  );
}
