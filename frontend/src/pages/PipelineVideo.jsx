import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Cpu, Zap, Video, Save, RefreshCw, CheckCircle2, XCircle, Info } from "lucide-react";
import { useApp } from "@/context/AppContext";

const MODE_LABELS = {
  pipeline_mode: { labelKey: "pvideo.pipeline_mode_label", opts: [
    { v: "auto", descKey: "pvideo.auto_recommended" }, { v: "gpu", descKey: "pvideo.gpu_nvidia" },
    { v: "cpu", descKey: "pvideo.cpu" }, { v: "direct", descKey: "pvideo.direct_webrtc" },
  ]},
  preview_mode: { labelKey: "pvideo.preview_mode_label", opts: [
    { v: "auto", descKey: "pvideo.auto" }, { v: "webrtc", descKey: "pvideo.webrtc_passthrough" },
    { v: "mjpeg", descKey: "pvideo.mjpeg" }, { v: "mse", descKey: "pvideo.mse" },
  ]},
  ai_pipeline: { labelKey: "pvideo.ai_pipeline_label", opts: [
    { v: "auto", descKey: "pvideo.auto" }, { v: "gpu", descKey: "pvideo.gpu_nvdec" }, { v: "cpu", descKey: "pvideo.cpu" },
  ]},
  recorder_mode: { labelKey: "pvideo.recorder_mode_label", opts: [
    { v: "auto", descKey: "pvideo.auto_copy" }, { v: "copy", descKey: "pvideo.copy_only" },
    { v: "reencode", descKey: "pvideo.reencode" },
  ]},
};

function ModeRadio({ mode, cfg, setCfg }) {
  const { t } = useApp();
  const M = MODE_LABELS[mode];
  return (
    <div className="border border-border p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t(M.labelKey)}</div>
      <div className="space-y-1">
        {M.opts.map((o) => (
          <label key={o.v} className="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground">
            <input type="radio" name={mode} value={o.v} checked={cfg[mode] === o.v}
                    onChange={() => setCfg({ ...cfg, [mode]: o.v })}
                    data-testid={`${mode}-${o.v}`} />
            <span>{t(o.descKey)}</span>
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
  const { t } = useApp();
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
    } catch (e) { toast.error(t("pvideo.toast_load_failed")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/pipeline/config", cfg);
      toast.success(t("pvideo.toast_saved") + " " + (data.note || ""));
      setDirty(false);
      await load();
    } catch (e) { toast.error(t("pvideo.toast_save_failed") + " " + (e.response?.data?.detail || e.message)); }
    finally { setSaving(false); }
  };

  const applyAll = async () => {
    if (!status?.cameras) return;
    setSaving(true);
    try {
      await Promise.all(status.cameras.map((c) =>
        api.post(`/cameras/${c.id}/refresh-stream`).catch(() => null)));
      toast.success(`${t("pvideo.toast_applied_prefix")} ${status.cameras.length} ${t("pvideo.toast_applied_suffix")}`);
      await load();
    } catch (e) { toast.error(t("pvideo.toast_apply_failed")); }
    finally { setSaving(false); }
  };

  if (!cfg || !status) return <div className="p-4 text-muted-foreground">{t("common.loading")}</div>;
  const caps = status.capabilities;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Video size={22} /> {t("pvideo.title")}
        </h1>
        <div className="flex items-center gap-2">
          <button onClick={load} disabled={loading} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border hover:bg-secondary">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> {t("pvideo.refresh")}
          </button>
          <button onClick={save} disabled={!dirty || saving} data-testid="pipeline-save"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#00E676] text-[#00E676] hover:bg-[#00E676] hover:text-black disabled:opacity-50">
            <Save size={13} /> {t("pvideo.save")}
          </button>
          <button onClick={applyAll} disabled={saving} data-testid="pipeline-apply-all"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF] hover:text-white">
            {t("pvideo.apply_all")}
          </button>
        </div>
      </div>

      {/* Capacités FFmpeg détectées */}
      <div className="border border-border p-3 mb-4" data-testid="pipeline-caps">
        <div className="flex items-center gap-2 mb-2">
          <Info size={14} className="text-muted-foreground" />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("pvideo.detected_capabilities")}</span>
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
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("pvideo.advanced_options")}</div>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">{t("pvideo.hd_width")}</span>
            <input type="number" min="0" max="4096" value={cfg.hd_preview_width}
                    onChange={(e) => { setCfg({ ...cfg, hd_preview_width: Number(e.target.value) || 0 }); setDirty(true); }}
                    className="px-2 py-1 bg-card border border-input" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">{t("pvideo.sd_width")}</span>
            <input type="number" min="160" max="1280" value={cfg.sd_preview_width}
                    onChange={(e) => { setCfg({ ...cfg, sd_preview_width: Number(e.target.value) || 640 }); setDirty(true); }}
                    className="px-2 py-1 bg-card border border-input" />
          </label>
          <label className="flex items-center gap-2 mt-4">
            <input type="checkbox" checked={cfg.low_latency}
                    onChange={(e) => { setCfg({ ...cfg, low_latency: e.target.checked }); setDirty(true); }} />
            <span>{t("pvideo.low_latency")}</span>
          </label>
        </div>
      </div>

      {/* Pipeline effectif par caméra */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
          {t("pvideo.effective_pipeline")} ({status.cameras.length})
        </div>
        <div className="border border-border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2">{t("common.camera")}</th>
                <th className="px-3 py-2">{t("pvideo.th_codec_res")}</th>
                <th className="px-3 py-2">Mode</th>
                <th className="px-3 py-2">{t("pvideo.th_decoder")}</th>
                <th className="px-3 py-2">Preview</th>
                <th className="px-3 py-2">Recorder</th>
                <th className="px-3 py-2">{t("pvideo.th_ai")}</th>
                <th className="px-3 py-2">{t("pvideo.th_reason")}</th>
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
