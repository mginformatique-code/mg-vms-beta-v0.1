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
  const active = !!runtime[gpuKey];
  const Icon = active ? CheckCircle2 : XCircle;
  const color = active ? "#00E676" : "#FF3333";
  return (
    <tr className="border-b border-border" data-testid={`runtime-${label}`}>
      <td className="px-3 py-2 text-sm font-medium">{label}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2 text-xs mono">
          <Icon size={14} style={{ color }} />
          <span style={{ color }}>{active ? "Actif" : "Inactif"}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-[11px] mono text-muted-foreground">{runtime.version || "—"}</td>
      <td className="px-3 py-2 text-[11px] mono text-muted-foreground">
        {runtime.cuda_version && `CUDA ${runtime.cuda_version}`}
        {runtime.gpu_provider && ` · ${runtime.gpu_provider}`}
        {runtime.cuda_devices != null && ` · ${runtime.cuda_devices} device(s) CUDA`}
        {runtime.source && ` · ${runtime.source}`}
        {runtime.error && <span className="text-[#FF3333]" title={runtime.error}> · erreur</span>}
      </td>
    </tr>
  );
}

export default function GPUStatus({ embedded = false }) {
  const { t } = useApp();
  const [full, setFull] = useState(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/system/gpu");
      setFull(data);
    } catch (e) {
      toast.error("Impossible de charger les infos GPU");
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

  const gpu = full?.devices?.[0];  // affiche le 1er GPU (multi-GPU listé en dessous)
  const isActive = !!full?.available;
  const yolo = !!full?.pipeline?.yolo_uses_gpu;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        {!embedded && (
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Zap size={22} className={isActive ? "text-[#00E676]" : "text-[#FF3333]"} /> Accélération GPU
          </h1>
        )}
        <div className="flex items-center gap-2 ml-auto">
          <button onClick={() => setAutoRefresh((v) => !v)} className={`px-2.5 py-1.5 text-xs border ${autoRefresh ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border"}`}>
            Auto-refresh {autoRefresh ? "ON (5s)" : "OFF"}
          </button>
          <button onClick={load} disabled={loading} data-testid="gpu-reload" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Actualiser
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
                ? `${full?.vendor} · ${gpu?.name || "GPU détecté"}`
                : "Aucun GPU détecté — pipeline IA en mode CPU"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {isActive
                ? <>Driver {full?.driver?.driver_version || "?"} · NVML {full?.driver?.nvml_version || "?"} · CUDA Driver {full?.driver?.cuda_driver_version || "?"}</>
                : <>NVML : {full?.diagnostic?.nvml_error || "non initialisé"} · nvidia-smi : {full?.diagnostic?.nvidia_smi_available ? "disponible" : "introuvable"}</>}
            </div>
            <div className="mt-2 text-xs flex items-center gap-1">
              <span className="mono text-muted-foreground">Pipeline IA (YOLO) :</span>
              <span className={`mono font-bold ${yolo ? "text-[#00E676]" : "text-[#FF3333]"}`}>
                {yolo ? "GPU (torch.cuda)" : "CPU (torch.cpu)"}
              </span>
              {!yolo && isActive && (
                <span className="text-[10px] text-[#FFB800] ml-2">⚠ GPU présent mais torch.cuda inactif — vérifiez que la version torch=CUDA correspond au driver.</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Métriques temps réel du GPU principal */}
      {isActive && gpu && (
        <div className="mb-4">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Métriques temps réel</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
            <StatCard label="Utilisation GPU" value={gpu.gpu_util_pct} unit="%" testid="gpu-util"
                      color={gpu.gpu_util_pct > 80 ? "#FF3333" : gpu.gpu_util_pct > 60 ? "#FFB800" : "#00E676"} />
            <StatCard label="Encodeur H.264/H.265" value={gpu.encoder_util_pct} unit="%" testid="gpu-encoder" />
            <StatCard label="Décodeur (streams)" value={gpu.decoder_util_pct} unit="%" testid="gpu-decoder" />
            <StatCard label="VRAM utilisée" value={gpu.vram_used_mb} unit="MB" testid="gpu-vram-used" />
            <StatCard label="VRAM totale" value={gpu.vram_total_mb} unit="MB" testid="gpu-vram-total" />
            <StatCard label="Occupation VRAM" value={gpu.vram_util_pct} unit="%" testid="gpu-vram-util"
                      color={gpu.vram_util_pct > 90 ? "#FF3333" : "#00E676"} />
            <StatCard label="Température" value={gpu.temperature_c} unit="°C" testid="gpu-temp"
                      color={gpu.temperature_c > 80 ? "#FF3333" : gpu.temperature_c > 70 ? "#FFB800" : "#00E676"} />
            <StatCard label="Puissance" value={gpu.power_w} unit="W" testid="gpu-power" />
            <StatCard label="Ventilateur" value={gpu.fan_pct} unit="%" testid="gpu-fan" />
            <StatCard label="Clock GPU" value={gpu.clock_graphics_mhz} unit="MHz" testid="gpu-clock-gpu" />
            <StatCard label="Clock VRAM" value={gpu.clock_memory_mhz} unit="MHz" testid="gpu-clock-mem" />
            <StatCard label="Compute Cap." value={gpu.cuda_compute_capability} testid="gpu-compute-cap" />
          </div>
        </div>
      )}

      {/* Table des runtimes détectés */}
      <div className="mb-4">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Runtimes d&apos;accélération détectés</div>
        <div className="border border-border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2">Runtime</th>
                <th className="px-3 py-2">Statut</th>
                <th className="px-3 py-2">Version</th>
                <th className="px-3 py-2">Détails</th>
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
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Tous les GPU ({full.devices.length})</div>
          <div className="space-y-2">
            {full.devices.map((d, i) => (
              <div key={i} className="border border-border p-3">
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
          <div className="font-head font-semibold mb-2 text-sm">Pour activer l&apos;accélération GPU sur ce serveur :</div>
          <ol className="text-xs list-decimal ml-5 space-y-1 text-muted-foreground">
            <li>Installer les <b className="text-foreground">pilotes NVIDIA</b> (v525+) sur l&apos;hôte : <code className="mono">sudo apt install nvidia-driver-535</code></li>
            <li>Installer le <b className="text-foreground">NVIDIA Container Toolkit</b> si MG-VMS tourne en Docker : <code className="mono">apt install nvidia-container-toolkit</code></li>
            <li>Lancer le container avec <code className="mono">--gpus all</code> ou <code className="mono">--runtime=nvidia</code></li>
            <li>Vérifier que <code className="mono">nvidia-smi</code> répond dans le container avant de redémarrer MG-VMS</li>
            <li>S&apos;assurer que la version PyTorch installée est bien la variante <code className="mono">+cuXX</code> compatible avec le driver (voir <a className="text-[#00E5FF] underline" href="https://pytorch.org/get-started/locally/" target="_blank" rel="noreferrer">pytorch.org</a>)</li>
          </ol>
        </div>
      )}
    </div>
  );
}
