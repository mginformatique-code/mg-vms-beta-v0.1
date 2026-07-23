import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Cpu, Zap, Video, Save, RefreshCw, CheckCircle2, XCircle, Info } from "lucide-react";

const MODE_LABELS = {
  pipeline_mode: { label: "Pipeline vidéo global", opts: [
    { v: "auto", desc: "Auto (recommandé)" }, { v: "gpu", desc: "GPU NVIDIA" },
    { v: "cpu", desc: "CPU" }, { v: "direct", desc: "Direct (WebRTC sans transcodage)" },
  ]},
  preview_mode: { label: "Prévisualisation", opts: [
    { v: "auto", desc: "Auto" }, { v: "webrtc", desc: "WebRTC (H.264 pass-through)" },
    { v: "mjpeg", desc: "MJPEG (compatible universel)" }, { v: "mse", desc: "MSE (fMP4)" },
  ]},
  ai_pipeline: { label: "Pipeline IA", opts: [
    { v: "auto", desc: "Auto" }, { v: "gpu", desc: "GPU (NVDEC + torch.cuda)" }, { v: "cpu", desc: "CPU" },
  ]},
  recorder_mode: { label: "Recorder", opts: [
    { v: "auto", desc: "Auto (copy si H.264/H.265)" }, { v: "copy", desc: "Copy uniquement (sans perte)" },
    { v: "reencode", desc: "Réencodage" },
  ]},
};

function ModeRadio({ mode, cfg, setCfg }) {
  const M = MODE_LABELS[mode];
  return (
    <div className="border border-border p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{M.label}</div>
      <div className="space-y-1">
        {M.opts.map((o) => (
          <label key={o.v} className="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground">
            <input type="radio" name={mode} value={o.v} checked={cfg[mode] === o.v}
                    onChange={() => setCfg({ ...cfg, [mode]: o.v })}
                    data-testid={`${mode}-${o.v}`} />
            <span>{o.desc}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function CapPill({ label, ok, extra }) {
  return (
    <div className={`flex items-center gap-1.5 text-[11px] mono px-2 py-1 border ${ok ? "border-[#00E676] text-[#00E676]" : "border-[#FF3333]/50 text-[#FF3333]"}`}>
      {ok ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
      <span>{label}</span>
      {extra && <span className="text-muted-foreground">{extra}</span>}
    </div>
  );
}

function CameraRow({ cam }) {
  const p = cam.pipeline || {};
  const mode = p.mode || "?";
  const color = mode === "gpu" ? "#00E676" : mode === "cpu" ? "#FFB800" : "#666";
  return (
    <tr className="border-b border-border" data-testid={`pipeline-row-${cam.id}`}>
      <td className="px-3 py-2 text-xs font-medium">{cam.name || cam.id}</td>
      <td className="px-3 py-2 text-[11px] mono text-muted-foreground">{cam.codec || "—"} · {cam.resolution || "—"}</td>
      <td className="px-3 py-2"><span className="text-[10px] mono font-bold px-2 py-0.5" style={{ backgroundColor: color, color: "#000" }}>{mode.toUpperCase()}</span></td>
      <td className="px-3 py-2 text-[10px] mono">{p.decoder || "—"}</td>
      <td className="px-3 py-2 text-[10px] mono">{p.preview || "—"}</td>
      <td className="px-3 py-2 text-[10px] mono">{p.recorder || "—"}</td>
      <td className="px-3 py-2 text-[10px] mono">{p.ai || "—"}</td>
      <td className="px-3 py-2 text-[9px] text-muted-foreground truncate max-w-xs" title={p.reason}>{p.reason}</td>
    </tr>
  );
}

export default function PipelineVideo() {
  const [status, setStatus] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/pipeline/status");
      setStatus(data);
      if (!cfg) setCfg(data.config);
    } catch (e) { toast.error("Chargement pipeline échoué"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/pipeline/config", cfg);
      toast.success("Config sauvegardée · " + (data.note || ""));
      setDirty(false);
      await load();
    } catch (e) { toast.error("Sauvegarde échouée : " + (e.response?.data?.detail || e.message)); }
    finally { setSaving(false); }
  };

  const applyAll = async () => {
    if (!status?.cameras) return;
    setSaving(true);
    try {
      await Promise.all(status.cameras.map((c) =>
        api.post(`/cameras/${c.id}/refresh-stream`).catch(() => null)));
      toast.success(`Config appliquée à ${status.cameras.length} caméra(s) — flux ré-enregistrés dans go2rtc`);
      await load();
    } catch (e) { toast.error("Application échouée"); }
    finally { setSaving(false); }
  };

  if (!cfg || !status) return <div className="p-4 text-muted-foreground">Chargement…</div>;
  const caps = status.capabilities;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Video size={22} /> Pipeline vidéo
        </h1>
        <div className="flex items-center gap-2">
          <button onClick={load} disabled={loading} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border hover:bg-secondary">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Actualiser
          </button>
          <button onClick={save} disabled={!dirty || saving} data-testid="pipeline-save"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E676] text-[#00E676] hover:bg-[#00E676] hover:text-black disabled:opacity-50">
            <Save size={13} /> Sauvegarder
          </button>
          <button onClick={applyAll} disabled={saving} data-testid="pipeline-apply-all"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF] hover:text-white">
            Appliquer à toutes les caméras
          </button>
        </div>
      </div>

      {/* Capacités FFmpeg détectées */}
      <div className="border border-border p-3 mb-4" data-testid="pipeline-caps">
        <div className="flex items-center gap-2 mb-2">
          <Info size={14} className="text-muted-foreground" />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Capacités FFmpeg détectées</span>
          <span className="text-[9px] mono text-muted-foreground ml-auto">{caps.ffmpeg_version}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <CapPill label="CUDA pipeline" ok={caps.cuda_pipeline_ready} />
          <CapPill label="hwaccel cuda" ok={caps.hwaccels?.includes("cuda")} />
          <CapPill label="h264_cuvid (NVDEC)" ok={caps.decoders_gpu?.includes("h264_cuvid")} />
          <CapPill label="hevc_cuvid (NVDEC)" ok={caps.decoders_gpu?.includes("hevc_cuvid")} />
          <CapPill label="h264_nvenc" ok={caps.encoders_gpu?.includes("h264_nvenc")} />
          <CapPill label="hevc_nvenc" ok={caps.encoders_gpu?.includes("hevc_nvenc")} />
          <CapPill label="scale_cuda" ok={caps.filters_cuda?.includes("scale_cuda")} />
          <CapPill label="colorspace_cuda" ok={caps.filters_cuda?.includes("colorspace_cuda")} />
        </div>
        {caps.hwaccels?.length > 0 && (
          <div className="text-[10px] mono text-muted-foreground mt-2">
            hwaccels: {caps.hwaccels.join(", ")}
          </div>
        )}
      </div>

      {/* Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <ModeRadio mode="pipeline_mode" cfg={cfg} setCfg={(c) => { setCfg(c); setDirty(true); }} />
        <ModeRadio mode="preview_mode" cfg={cfg} setCfg={(c) => { setCfg(c); setDirty(true); }} />
        <ModeRadio mode="ai_pipeline" cfg={cfg} setCfg={(c) => { setCfg(c); setDirty(true); }} />
        <ModeRadio mode="recorder_mode" cfg={cfg} setCfg={(c) => { setCfg(c); setDirty(true); }} />
      </div>

      {/* Options avancées */}
      <div className="border border-border p-3 mb-4">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Options avancées</div>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Largeur HD (0=native)</span>
            <input type="number" min="0" max="4096" value={cfg.hd_preview_width}
                    onChange={(e) => { setCfg({ ...cfg, hd_preview_width: Number(e.target.value) || 0 }); setDirty(true); }}
                    className="px-2 py-1 bg-card border border-input" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Largeur SD</span>
            <input type="number" min="160" max="1280" value={cfg.sd_preview_width}
                    onChange={(e) => { setCfg({ ...cfg, sd_preview_width: Number(e.target.value) || 640 }); setDirty(true); }}
                    className="px-2 py-1 bg-card border border-input" />
          </label>
          <label className="flex items-center gap-2 mt-4">
            <input type="checkbox" checked={cfg.low_latency}
                    onChange={(e) => { setCfg({ ...cfg, low_latency: e.target.checked }); setDirty(true); }} />
            <span>Faible latence (low_latency ffmpeg)</span>
          </label>
        </div>
      </div>

      {/* Pipeline effectif par caméra */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
          Pipeline effectif par caméra ({status.cameras.length})
        </div>
        <div className="border border-border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2">Caméra</th>
                <th className="px-3 py-2">Codec / Résolution</th>
                <th className="px-3 py-2">Mode</th>
                <th className="px-3 py-2">Décodeur</th>
                <th className="px-3 py-2">Preview</th>
                <th className="px-3 py-2">Recorder</th>
                <th className="px-3 py-2">IA</th>
                <th className="px-3 py-2">Raison du choix</th>
              </tr>
            </thead>
            <tbody>
              {status.cameras.map((c) => <CameraRow key={c.id} cam={c} />)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
