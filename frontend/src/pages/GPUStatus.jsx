import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { Zap, RefreshCw, AlertTriangle, CheckCircle2, XCircle, Cpu, Activity, Thermometer, Gauge, HardDrive } from "lucide-react";

function StatCard({ label, value, unit, color, testid }) {
  return (
    <div className="border border-border bg-card p-3" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mono font-bold text-2xl mt-1" style={{ color: color || undefined }}>
        {value ?? "—"}{unit && value != null && <span className="text-sm text-muted-foreground ml-1">{unit}</span>}
      </div>
    </div>
  );
}

function RuntimeRow({ label, runtime, gpuKey = "available" }) {
  const { t } = useApp();
  const active = !!runtime[gpuKey];
  const Icon = active ? CheckCircle2 : XCircle;
  const color = active ? "#00E676" : "#FF3333";
  return (
    <tr className="border-b border-border" data-testid={`runtime-${label}`}>
      <td className="px-3 py-2 text-sm font-medium">{label}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2 text-xs mono">
          <Icon size={14} style={{ color }} />
          <span style={{ color }}>{active ? t("common.active") : t("gpu.inactive")}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-[11px] mono text-muted-foreground">{runtime.version || "—"}</td>
      <td className="px-3 py-2 text-[11px] mono text-muted-foreground">
        {runtime.cuda_version && `CUDA ${runtime.cuda_version}`}
        {runtime.gpu_provider && ` · ${runtime.gpu_provider}`}
        {runtime.cuda_devices != null && ` · ${runtime.cuda_devices} device(s) CUDA`}
        {runtime.source && ` · ${runtime.source}`}
        {runtime.error && <span className="text-[#FF3333]" title={runtime.error}> · {t("gpu.error_label")}</span>}
      </td>
    </tr>
  );
}

export default function GPUStatus({ embedded = false }) {
  const { t } = useApp();
  const [full, setFull] = useState(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  // v3.38 · 2e GPU ajouté sur ce serveur (isolation ANPR) — sélecteur
  // GPU0/GPU1 pour les métriques temps réel, affiché seulement si >1 GPU.
  const [selectedGpuIdx, setSelectedGpuIdx] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/system/gpu");
      setFull(data);
    } catch (e) {
      toast.error(t("gpu.toast_load_error"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!autoRefresh) return;
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [autoRefresh, load]);

  const multiGpu = (full?.devices?.length || 0) > 1;
  const gpu = full?.devices?.[multiGpu ? selectedGpuIdx : 0] || full?.devices?.[0];
  const isActive = !!full?.available;
  const yolo = !!full?.pipeline?.yolo_uses_gpu;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        {!embedded && (
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Zap size={22} className={isActive ? "text-[#00E676]" : "text-[#FF3333]"} /> {t("nav.gpu")}
          </h1>
        )}
        <div className="flex items-center gap-2 ml-auto">
          <button onClick={() => setAutoRefresh((v) => !v)} className={`px-2.5 py-1.5 text-xs border ${autoRefresh ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border"}`}>
            Auto-refresh {autoRefresh ? "ON (5s)" : "OFF"}
          </button>
          <button onClick={load} disabled={loading} data-testid="gpu-reload" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> {t("gpu.refresh")}
          </button>
        </div>
      </div>

      {/* Bandeau de statut global */}
      <div className={`mb-4 p-3 border ${isActive ? "border-[#00E676] bg-[#00E676]/5" : "border-[#FF3333] bg-[#FF3333]/5"}`} data-testid="gpu-status-banner">
        <div className="flex items-start gap-3">
          {isActive
            ? <CheckCircle2 size={20} className="text-[#00E676] mt-0.5" />
            : <AlertTriangle size={20} className="text-[#FF3333] mt-0.5" />}
          <div className="flex-1">
            <div className="font-head font-bold text-lg" style={{ color: isActive ? "#00E676" : "#FF3333" }}>
              {isActive
                ? `${full?.vendor} · ${gpu?.name || t("gpu.gpu_detected")}`
                : t("gpu.no_gpu_detected")}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {isActive
                ? <>Driver {full?.driver?.driver_version || "?"} · NVML {full?.driver?.nvml_version || "?"} · CUDA Driver {full?.driver?.cuda_driver_version || "?"}</>
                : <>{t("gpu.nvml_label")} {full?.diagnostic?.nvml_error || t("gpu.not_initialized")} · {t("gpu.nvidia_smi_label")} {full?.diagnostic?.nvidia_smi_available ? t("gpu.available") : t("gpu.not_found")}</>}
            </div>
            <div className="mt-2 text-xs flex items-center gap-1">
              <span className="mono text-muted-foreground">{t("gpu.ai_pipeline_label")}</span>
              <span className={`mono font-bold ${yolo ? "text-[#00E676]" : "text-[#FF3333]"}`}>
                {yolo ? "GPU (torch.cuda)" : "CPU (torch.cpu)"}
              </span>
              {!yolo && isActive && (
                <span className="text-[10px] text-[#FFB800] ml-2">⚠ {t("gpu.gpu_present_torch_inactive")}</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Métriques temps réel du GPU principal */}
      {isActive && gpu && (
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-2">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("gpu.realtime_metrics")}</div>
            {/* v3.54 · Sélecteur dropdown retiré (doublon avec les cartes
                cliquables de "Tous les GPU" plus bas — même état
                `selectedGpuIdx`, un seul moyen de sélection suffit). */}
            {multiGpu && (
              <span className="text-[11px] mono text-muted-foreground">GPU{gpu?.index ?? selectedGpuIdx} · {gpu?.name}</span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
            <StatCard label={t("gpu.util")} value={gpu.gpu_util_pct} unit="%" testid="gpu-util"
                      color={gpu.gpu_util_pct > 80 ? "#FF3333" : gpu.gpu_util_pct > 60 ? "#FFB800" : "#00E676"} />
            <StatCard label={t("gpu.encoder")} value={gpu.encoder_util_pct} unit="%" testid="gpu-encoder" />
            <StatCard label={t("gpu.decoder")} value={gpu.decoder_util_pct} unit="%" testid="gpu-decoder" />
            <StatCard label={t("gpu.vram_used")} value={gpu.vram_used_mb} unit="MB" testid="gpu-vram-used" />
            <StatCard label={t("gpu.vram_total")} value={gpu.vram_total_mb} unit="MB" testid="gpu-vram-total" />
            <StatCard label={t("gpu.vram_util")} value={gpu.vram_util_pct} unit="%" testid="gpu-vram-util"
                      color={gpu.vram_util_pct > 90 ? "#FF3333" : "#00E676"} />
            <StatCard label={t("gpu.temperature")} value={gpu.temperature_c} unit="°C" testid="gpu-temp"
                      color={gpu.temperature_c > 80 ? "#FF3333" : gpu.temperature_c > 70 ? "#FFB800" : "#00E676"} />
            <StatCard label={t("gpu.power")} value={gpu.power_w} unit="W" testid="gpu-power" />
            <StatCard label={t("gpu.fan")} value={gpu.fan_pct} unit="%" testid="gpu-fan" />
            <StatCard label={t("gpu.clock_gpu")} value={gpu.clock_graphics_mhz} unit="MHz" testid="gpu-clock-gpu" />
            <StatCard label={t("gpu.clock_vram")} value={gpu.clock_memory_mhz} unit="MHz" testid="gpu-clock-mem" />
            <StatCard label={t("gpu.compute_cap")} value={gpu.cuda_compute_capability} testid="gpu-compute-cap" />
          </div>
        </div>
      )}

      {/* Table des runtimes détectés */}
      <div className="mb-4">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("gpu.detected_runtimes")}</div>
        <div className="border border-border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2">Runtime</th>
                <th className="px-3 py-2">{t("common.status")}</th>
                <th className="px-3 py-2">Version</th>
                <th className="px-3 py-2">{t("gpu.details")}</th>
              </tr>
            </thead>
            <tbody>
              {full?.runtimes?.pytorch && <RuntimeRow label="PyTorch CUDA" runtime={full.runtimes.pytorch} />}
              {full?.runtimes?.tensorrt && <RuntimeRow label="TensorRT" runtime={full.runtimes.tensorrt} />}
              {full?.runtimes?.onnx_runtime && <RuntimeRow label="ONNX Runtime GPU" runtime={full.runtimes.onnx_runtime} />}
              {full?.runtimes?.opencv_cuda && <RuntimeRow label="OpenCV CUDA" runtime={full.runtimes.opencv_cuda} />}
            </tbody>
          </table>
        </div>
      </div>

      {/* Multi-GPU : liste tous les devices si > 1 */}
      {full?.devices?.length > 1 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("gpu.all_gpus")} ({full.devices.length})</div>
          <div className="space-y-2">
            {full.devices.map((d, i) => (
              <div key={i}
                   onClick={() => setSelectedGpuIdx(i)}
                   className={`border p-3 cursor-pointer ${i === selectedGpuIdx ? "border-[#0044FF] bg-[#0044FF]/5" : "border-border hover:bg-secondary/40"}`}>
                <div className="font-medium text-sm">GPU #{d.index} · {d.name}</div>
                <div className="text-[10px] mono text-muted-foreground">{d.uuid}</div>
                <div className="mt-1 grid grid-cols-4 gap-2 text-[11px] mono">
                  <span>Util : {d.gpu_util_pct}%</span>
                  <span>VRAM : {d.vram_used_mb}/{d.vram_total_mb} MB</span>
                  <span>Temp : {d.temperature_c}°C</span>
                  <span>Power : {d.power_w}W</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Aide si aucun GPU */}
      {!isActive && (
        <div className="border border-border p-4 bg-secondary/30" data-testid="gpu-help">
          <div className="font-head font-semibold mb-2 text-sm">{t("gpu.enable_gpu_title")}</div>
          <ol className="text-xs list-decimal ml-5 space-y-1 text-muted-foreground">
            <li>{t("gpu.step1_prefix")} <b className="text-foreground">{t("gpu.step1_bold")}</b> {t("gpu.step1_suffix")} <code className="mono">sudo apt install nvidia-driver-535</code></li>
            <li>{t("gpu.step2_prefix")} <b className="text-foreground">NVIDIA Container Toolkit</b> {t("gpu.step2_suffix")} <code className="mono">apt install nvidia-container-toolkit</code></li>
            <li>{t("gpu.step3")} <code className="mono">--gpus all</code> {t("gpu.step3_or")} <code className="mono">--runtime=nvidia</code></li>
            <li>{t("gpu.step4_prefix")} <code className="mono">nvidia-smi</code> {t("gpu.step4_suffix")}</li>
            <li>{t("gpu.step5_prefix")} <code className="mono">+cuXX</code> {t("gpu.step5_suffix")} <a className="text-[#00E5FF] underline" href="https://pytorch.org/get-started/locally/" target="_blank" rel="noreferrer">pytorch.org</a>)</li>
          </ol>
        </div>
      )}
    </div>
  );
}
