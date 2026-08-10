/**
 * Go2RTCDiagnostic.jsx — Page dédiée v1.0-rc4.5 · Phase 3
 *
 * Diagnostic Go2RTC détaillé pour une caméra donnée.
 * Route : /diagnostics/go2rtc/:cameraId
 *
 * Affiche codec I/O, transport, bitrate, résolution, hwaccel,
 * transcoding actif, temps connexion, état WebRTC, verdict global.
 */
import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { RefreshCw, ArrowLeft, Wrench, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

const VerdictBadge = ({ verdict }) => {
  const map = {
    PASS: { color: "#22c55e", icon: CheckCircle2, label: "OK" },
    WARN: { color: "#f59e0b", icon: AlertTriangle, label: "Avertissement" },
    FAIL: { color: "#ef4444", icon: XCircle, label: "Échec" },
    "N/A": { color: "#6b7280", icon: AlertTriangle, label: "Non applicable" },
  };
  const cfg = map[verdict] || map.WARN;
  const Icon = cfg.icon;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 text-xs font-semibold"
      style={{ backgroundColor: `${cfg.color}20`, color: cfg.color, borderLeft: `3px solid ${cfg.color}` }}
      data-testid="go2rtc-diag-verdict"
    >
      <Icon size={13} /> {verdict} · {cfg.label}
    </span>
  );
};

const Row = ({ label, value, mono = false, testid }) => (
  <div className="grid grid-cols-3 gap-3 py-1.5 border-b border-border/40">
    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
    <div className={`col-span-2 text-sm ${mono ? "mono break-all" : ""}`} data-testid={testid}>
      {value ?? <span className="text-muted-foreground italic">non disponible</span>}
    </div>
  </div>
);

export default function Go2RTCDiagnostic() {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [repairing, setRepairing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: d } = await api.get(`/cameras/${cameraId}/go2rtc-diagnostic`);
      setData(d);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Diagnostic Go2RTC indisponible");
    } finally {
      setLoading(false);
    }
  }, [cameraId]);

  useEffect(() => { load(); }, [load]);

  const repair = async () => {
    if (!cameraId) return;
    setRepairing(true);
    try {
      await api.post(`/cameras/${cameraId}/refresh-stream`);
      toast.success("Flux ré-enregistré avec #transport=tcp");
      setTimeout(load, 500);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec de la réparation");
    } finally {
      setRepairing(false);
    }
  };

  if (!data && loading) {
    return (
      <div className="p-8 text-muted-foreground" data-testid="go2rtc-diag-loading">
        Chargement du diagnostic Go2RTC…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-8">
        <button onClick={() => navigate(-1)} className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-2">
          <ArrowLeft size={14} /> Retour
        </button>
        <div className="mt-6 text-sm text-[#ff3333]">Aucune donnée reçue. Vérifiez que la caméra existe et que Go2RTC est actif.</div>
      </div>
    );
  }

  const isDirectRtsp = (data.stream_mode || "").toLowerCase() === "direct_rtsp";

  return (
    <div className="p-6 space-y-4 max-w-5xl" data-testid="go2rtc-diag-page">
      {/* En-tête */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-2"
          data-testid="go2rtc-diag-back"
        >
          <ArrowLeft size={14} /> Retour
        </button>
        <div className="flex-1" />
        <button
          onClick={load}
          disabled={loading}
          className="border border-border px-3 py-1.5 text-xs hover:bg-secondary flex items-center gap-2"
          data-testid="go2rtc-diag-refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          Rafraîchir
        </button>
        {!isDirectRtsp && (
          <button
            onClick={repair}
            disabled={repairing}
            className="border border-[#00E5FF] text-[#00E5FF] px-3 py-1.5 text-xs hover:bg-[#00E5FF]/10 flex items-center gap-2"
            data-testid="go2rtc-diag-repair"
          >
            <Wrench size={13} className={repairing ? "animate-spin" : ""} />
            Réparer le flux (ré-enregistrer)
          </button>
        )}
      </div>

      {/* Titre + verdict */}
      <div className="border border-border p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Diagnostic Go2RTC v1.0-rc4.5</div>
        <h1 className="font-head text-2xl font-black">{data.camera_name || data.camera_id}</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <VerdictBadge verdict={data.verdict} />
          <span className="text-xs text-muted-foreground">Mode : <strong>{data.stream_mode}</strong></span>
          <span className="text-xs text-muted-foreground mono">stream : {data.stream_name}</span>
        </div>
        {data.reason && (
          <div className="text-xs text-muted-foreground pt-2" data-testid="go2rtc-diag-reason">{data.reason}</div>
        )}
        {isDirectRtsp && (
          <div className="text-xs text-[#00E5FF] pt-1 border-l-2 border-[#00E5FF] pl-3">
            {data.note}
          </div>
        )}
      </div>

      {/* Section Stream */}
      {!isDirectRtsp && (
        <div className="border border-border">
          <div className="bg-secondary/50 px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
            Stream & source
          </div>
          <div className="p-4 space-y-1">
            <Row label="Stream déclaré" value={String(data.stream_registered)} testid="row-registered" />
            <Row label="Source déclarée" value={data.stream_source_declared} mono testid="row-source" />
            <Row label="Producers" value={data.producers_count} testid="row-producers" />
            <Row label="Consumers" value={data.consumers_count} testid="row-consumers" />
            <Row label="Producer connecté" value={String(data.producer_connected)} testid="row-connected" />
            <Row label="Octets reçus" value={data.producer_bytes_recv?.toLocaleString?.() || 0} testid="row-bytes" />
          </div>
        </div>
      )}

      {/* Section Codecs & Transport */}
      {!isDirectRtsp && (
        <div className="border border-border">
          <div className="bg-secondary/50 px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
            Codecs · Transport · Résolution
          </div>
          <div className="p-4 space-y-1">
            <Row label="Codec entrant" value={data.codec_in} testid="row-codec-in" />
            <Row label="Codecs disponibles" value={(data.codecs_available || []).join(", ") || null} testid="row-codecs-out" />
            <Row label="Résolution" value={data.resolution} testid="row-resolution" />
            <Row label="Transport RTSP" value={
              <span className={data.transport?.startsWith("TCP") ? "text-[#22c55e]" : "text-[#f59e0b]"}>{data.transport}</span>
            } testid="row-transport" />
            <Row label="Copy codec (source)" value={String(data.copy_codec_source)} testid="row-copy-source" />
            <Row label="Transcoding source" value={String(data.transcoding_source)} testid="row-transcoding-source" />
            <Row label="Transcoding _hd" value={data.transcoding_hd_variant} testid="row-transcoding-hd" />
            <Row label="Transcoding _sd" value={data.transcoding_sd_variant} testid="row-transcoding-sd" />
          </div>
        </div>
      )}

      {/* Section Performance */}
      {!isDirectRtsp && (
        <div className="border border-border">
          <div className="bg-secondary/50 px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
            Performance (échantillon {data.sampling?.duration_ms || 0}ms)
          </div>
          <div className="p-4 space-y-1">
            <Row label="Bitrate estimé" value={data.sampling?.bitrate_kbps != null ? `${data.sampling.bitrate_kbps} kbps` : null} testid="row-bitrate" />
            <Row label="FPS estimé" value={data.sampling?.fps_estimated} testid="row-fps" />
            <Row label="Delta octets" value={data.sampling?.bytes_delta?.toLocaleString?.() || 0} testid="row-bytes-delta" />
            {data.sampling?.error && (
              <Row label="Erreur sampling" value={<span className="text-[#ff3333]">{data.sampling.error}</span>} testid="row-sampling-error" />
            )}
          </div>
        </div>
      )}

      {/* Section Pipeline */}
      <div className="border border-border">
        <div className="bg-secondary/50 px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
          Pipeline vidéo (video_engine)
        </div>
        <div className="p-4 space-y-1">
          <Row label="Mode pipeline" value={data.pipeline?.mode} testid="row-pipeline-mode" />
          <Row label="Décodeur" value={data.pipeline?.decoder} testid="row-decoder" />
          <Row label="Preview" value={data.pipeline?.preview} testid="row-preview" />
          <Row label="Recorder" value={data.pipeline?.recorder} testid="row-recorder" />
          <Row label="IA" value={data.pipeline?.ai} testid="row-ai" />
          <Row label="CUDA disponible" value={String(data.pipeline?.cuda_available)} testid="row-cuda" />
          <Row label="Hwaccels détectés" value={(data.pipeline?.hwaccels || []).join(", ")} testid="row-hwaccels" />
          <Row label="ffmpeg" value={data.pipeline?.ffmpeg_version} mono testid="row-ffmpeg" />
        </div>
      </div>

      {/* Section WebRTC */}
      {!isDirectRtsp && data.webrtc && (
        <div className="border border-border">
          <div className="bg-secondary/50 px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
            WebRTC (candidates ICE)
          </div>
          <div className="p-4 space-y-1">
            <Row label="Listen" value={data.webrtc.listen} testid="row-webrtc-listen" />
            <Row label="Candidates" value={(data.webrtc.candidates_configured || []).join(", ") || <span className="text-[#f59e0b]">Aucun (LAN inaccessible)</span>} testid="row-webrtc-candidates" />
            <Row label="ICE servers" value={JSON.stringify(data.webrtc.ice_servers || [])} mono testid="row-webrtc-ice" />
            {data.webrtc.note && <div className="pt-2 text-[11px] text-muted-foreground italic">{data.webrtc.note}</div>}
            {data.webrtc.error && <div className="pt-2 text-[11px] text-[#ff3333]">{data.webrtc.error}</div>}
          </div>
        </div>
      )}

      <div className="text-[10px] text-muted-foreground pt-4">
        MG-VMS · Go2RTC diagnostic · Endpoint <code className="mono">GET /api/cameras/{cameraId}/go2rtc-diagnostic</code>
      </div>
    </div>
  );
}
