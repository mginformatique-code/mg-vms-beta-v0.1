import React, { useEffect, useRef, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import {
  Server, Cpu, MemoryStick, HardDrive, Gauge, Zap, Activity, Thermometer,
  Save, Loader2, Sparkles, Cctv, Brain, Film,
} from "lucide-react";
import { toast } from "sonner";

const OPT_LABEL = {
  cpu: "CPU", gpu: "GPU", auto: "Auto", nvdec: "NVIDIA NVDEC", nvenc: "NVIDIA NVENC",
  quicksync: "Intel QuickSync", amf: "AMD AMF", gpu_priority: "Priorité GPU", cpu_priority: "Priorité CPU",
  gpu0: "GPU 0", gpu1: "GPU 1", gpu2: "GPU 2", coral: "Google Coral",
};
const VENDOR_COLOR = { NVIDIA: "#76B900", Intel: "#0071C5", AMD: "#ED1C24", Google: "#FBBC05" };
const barColor = (v) => (v > 88 ? "#FF3333" : v > 70 ? "#FFB800" : "#00E676");

function Bar({ value, label, unit = "%", icon: Icon }) {
  return (
    <div data-testid={`hw-gauge-${label}`}>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="flex items-center gap-1.5 text-muted-foreground uppercase tracking-wider">
          {Icon && <Icon size={12} />} {label}
        </span>
        <span className="mono font-bold">{value}{unit}</span>
      </div>
      <div className="h-2 bg-secondary overflow-hidden">
        <div className="h-full transition-all duration-500" style={{ width: `${Math.min(100, value)}%`, backgroundColor: barColor(value) }} />
      </div>
    </div>
  );
}

export default function Hardware() {
  const { t, can } = useApp();
  const [tab, setTab] = useState("hardware");
  const [info, setInfo] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [mon, setMon] = useState(null);
  const [saving, setSaving] = useState(false);
  const monRef = useRef(null);

  const loadCfg = () => api.get("/hardware/config").then((r) => setCfg(r.data)).catch(() => {});
  useEffect(() => {
    api.get("/hardware/info").then((r) => setInfo(r.data)).catch(() => {});
    loadCfg();
  }, []);

  // monitoring temps réel (poll 2s quand l'onglet est actif)
  useEffect(() => {
    if (tab !== "monitor") { clearInterval(monRef.current); return; }
    let cancelled = false;
    const tick = () => api.get("/hardware/monitor").then((r) => { if (!cancelled) setMon(r.data); }).catch(() => {});
    tick();
    monRef.current = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(monRef.current); };
  }, [tab]);

  const setAssign = (fn, val) => setCfg((c) => ({ ...c, assignments: { ...c.assignments, [fn]: val }, profile: "custom" }));
  const setPrio = (eng, val) => setCfg((c) => ({ ...c, priorities: { ...c.priorities, [eng]: val }, profile: "custom" }));

  const saveConfig = async () => {
    setSaving(true);
    try {
      await api.put("/hardware/config", { assignments: cfg.assignments, priorities: cfg.priorities, auto_optimize: cfg.auto_optimize });
      toast.success(t("hw.saved")); loadCfg();
    } catch (e) { toast.error("Échec"); } finally { setSaving(false); }
  };

  const applyProfile = async (p) => {
    try { const { data } = await api.post(`/hardware/profile/${p}`); setCfg((c) => ({ ...c, ...data })); toast.success(`${t("hw.opt." + p)}`); }
    catch (e) { toast.error("Échec"); }
  };

  const TABS = [["hardware", t("hw.tab.hardware")], ["resources", t("hw.tab.resources")], ["profiles", t("hw.tab.profiles")], ["monitor", t("hw.tab.monitor")]];

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="hardware-page">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Server size={22} className="text-[#0044FF]" /> {t("hw.title")}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{t("hw.subtitle")}</p>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-border flex-wrap">
        {TABS.map(([k, lbl]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`hw-tab-${k}`}
            className={`px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${tab === k ? "border-[#0044FF] text-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{lbl}</button>
        ))}
        {info?.gpus?.length === 0 && <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">Aucun GPU détecté</span>}
      </div>

      {/* MATÉRIEL */}
      {tab === "hardware" && info && (
        <div className="space-y-4" data-testid="hw-detection">
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="border border-border bg-card p-4">
              <div className="flex items-center gap-2 mb-2"><Cpu size={18} className="text-[#0044FF]" /><span className="font-head font-bold">{t("hw.cpu")}</span></div>
              <div className="text-sm">{info.cpu.model}</div>
              <div className="text-xs text-muted-foreground mt-1">{t("hw.cores")}: <span className="mono">{info.cpu.cores} / {info.cpu.threads}</span>{info.cpu.freq_mhz ? ` · ${(info.cpu.freq_mhz / 1000).toFixed(1)} GHz` : ""}</div>
            </div>
            <div className="border border-border bg-card p-4">
              <div className="flex items-center gap-2 mb-2"><MemoryStick size={18} className="text-[#0044FF]" /><span className="font-head font-bold">{t("hw.ram")}</span></div>
              <div className="text-sm mono">{(info.ram.total_mb / 1024).toFixed(1)} GB</div>
              <div className="text-xs text-muted-foreground mt-1">Disponible: <span className="mono">{(info.ram.available_mb / 1024).toFixed(1)} GB</span></div>
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("hw.gpus")}</div>
            <div className="grid sm:grid-cols-2 gap-3">
              {info.gpus.map((g) => (
                <div key={g.id} className="border border-border bg-card p-4 border-l-4" style={{ borderLeftColor: VENDOR_COLOR[g.vendor] || "#888" }} data-testid={`hw-gpu-${g.id}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{g.name}</span>
                    <span className="text-[10px] uppercase px-1.5 py-0.5" style={{ color: VENDOR_COLOR[g.vendor] }}>{g.vendor}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">{t("hw.vram")}: <span className="mono">{g.vram_mb ? `${(g.vram_mb / 1024).toFixed(0)} GB` : "—"}</span></div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {g.features.map((f) => <span key={f} className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-border">{f}</span>)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("hw.accelerators")}</div>
            <div className="flex flex-wrap gap-1.5">
              {info.accelerators.map((a) => <span key={a} className="text-xs px-2 py-1 bg-secondary">{a}</span>)}
            </div>
          </div>
        </div>
      )}

      {/* RESSOURCES */}
      {tab === "resources" && cfg && (
        <div className="space-y-3" data-testid="hw-resources">
          <p className="text-sm text-muted-foreground">{t("hw.assign_intro")}</p>
          <div className="border border-border bg-card divide-y divide-border">
            {Object.keys(cfg.options).map((fn) => (
              <div key={fn} className="flex items-center justify-between px-4 py-2.5 gap-4" data-testid={`hw-assign-row-${fn}`}>
                <span className="text-sm font-medium">{cfg.labels[fn]}</span>
                <select value={cfg.assignments[fn]} onChange={(e) => setAssign(fn, e.target.value)} disabled={!can("admin")}
                  data-testid={`hw-assign-${fn}`} className="px-3 py-1.5 bg-background border border-input text-sm outline-none min-w-[180px] disabled:opacity-60">
                  {cfg.options[fn].map((o) => <option key={o} value={o}>{OPT_LABEL[o] || o}</option>)}
                </select>
              </div>
            ))}
          </div>
          {can("admin") && (
            <button onClick={saveConfig} disabled={saving} data-testid="hw-save-btn" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]">
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} {t("hw.apply")}
            </button>
          )}
        </div>
      )}

      {/* PROFILS & PRIORITÉS */}
      {tab === "profiles" && cfg && (
        <div className="space-y-4" data-testid="hw-profiles">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("hw.profile")}</div>
            <div className="flex flex-wrap gap-2">
              {cfg.profiles.map((p) => (
                <button key={p} onClick={() => can("admin") && applyProfile(p)} disabled={!can("admin")} data-testid={`hw-profile-${p}`}
                  className={`flex items-center gap-2 px-4 py-2.5 border text-sm transition-colors disabled:opacity-60 ${cfg.profile === p ? "border-[#0044FF] bg-secondary font-medium" : "border-border hover:bg-secondary"}`}>
                  <Sparkles size={15} className={cfg.profile === p ? "text-[#0044FF]" : "text-muted-foreground"} /> {t("hw.opt." + p)}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("hw.priorities")}</div>
            <div className="border border-border bg-card divide-y divide-border">
              {cfg.priority_engines.map((eng) => (
                <div key={eng} className="flex items-center justify-between px-4 py-2.5 gap-4" data-testid={`hw-prio-row-${eng}`}>
                  <span className="text-sm font-medium">{cfg.labels[eng] || eng}</span>
                  <select value={cfg.priorities[eng] || "normal"} onChange={(e) => setPrio(eng, e.target.value)} disabled={!can("admin")}
                    data-testid={`hw-prio-${eng}`} className="px-3 py-1.5 bg-background border border-input text-sm outline-none min-w-[160px] disabled:opacity-60">
                    {cfg.priority_levels.map((l) => <option key={l} value={l}>{t("hw.prio." + l)}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm" data-testid="hw-auto-optimize">
            <input type="checkbox" checked={!!cfg.auto_optimize} disabled={!can("admin")} onChange={(e) => setCfg((c) => ({ ...c, auto_optimize: e.target.checked }))} />
            <span className="font-medium">{t("hw.auto_optimize")}</span>
            <span className="text-xs text-muted-foreground">— {t("hw.auto_optimize_hint")}</span>
          </label>

          {can("admin") && (
            <button onClick={saveConfig} disabled={saving} data-testid="hw-save-profiles-btn" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]">
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} {t("hw.apply")}
            </button>
          )}
        </div>
      )}

      {/* MONITORING */}
      {tab === "monitor" && (
        <div className="space-y-4" data-testid="hw-monitor">
          {!mon ? <div className="text-sm text-muted-foreground py-10 text-center">{t("common.loading")}</div> : (
            <>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="border border-border bg-card p-4 space-y-3">
                  <Bar value={mon.cpu_pct} label="CPU" icon={Cpu} />
                  <Bar value={mon.ram_pct} label="RAM" icon={MemoryStick} />
                </div>
                <div className="border border-border bg-card p-4 space-y-3">
                  <Bar value={mon.ai_load_pct} label={t("hw.ai_load")} icon={Brain} />
                  <Bar value={mon.ffmpeg_load_pct} label={t("hw.ffmpeg_load")} icon={Film} />
                </div>
                <div className="border border-border bg-card p-4 grid grid-cols-2 gap-3">
                  <Metric icon={Cctv} label={t("hw.streams")} value={mon.streams} />
                  <Metric icon={Activity} label={t("hw.fps")} value={mon.fps} />
                  <Metric icon={Zap} label={t("hw.power")} value={`${mon.power_total_w} W`} />
                  <Metric icon={Thermometer} label="CPU °C" value={`${mon.cpu_temp_c}°`} />
                </div>
                <div className="border border-border bg-card p-4 flex flex-col justify-center">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("hw.power")}</div>
                  <div className="text-3xl font-head font-bold mono text-[#0044FF]">{mon.power_total_w}<span className="text-base"> W</span></div>
                  <div className="text-xs text-muted-foreground mt-1 mono">{mon.bandwidth_mbps} Mbps</div>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                {mon.gpus.map((g) => (
                  <div key={g.id} className="border border-border bg-card p-4 border-l-4" style={{ borderLeftColor: VENDOR_COLOR[g.vendor] || "#888" }} data-testid={`hw-mon-gpu-${g.id}`}>
                    <div className="flex items-center justify-between mb-3">
                      <span className="font-medium text-sm flex items-center gap-2"><Gauge size={15} style={{ color: VENDOR_COLOR[g.vendor] }} /> {g.name}</span>
                      <span className="text-xs mono flex items-center gap-1"><Thermometer size={12} /> {g.temp_c}°C</span>
                    </div>
                    <div className="space-y-3">
                      <Bar value={g.util_pct} label="GPU" icon={Gauge} />
                      {g.vram_mb > 0 && <Bar value={Math.round((g.vram_used_mb / g.vram_mb) * 100)} label={`VRAM ${(g.vram_used_mb / 1024).toFixed(1)}/${(g.vram_mb / 1024).toFixed(0)}GB`} unit="%" />}
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1"><Zap size={12} /> {g.power_w} W</span>
                        <span>Fan {g.fan_pct}%</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ icon: Icon, label, value }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1"><Icon size={11} /> {label}</div>
      <div className="text-lg font-head font-bold mono">{value}</div>
    </div>
  );
}
