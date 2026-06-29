import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Puzzle, ScanLine, Brain, Activity, ScanFace, Car, Thermometer, Radar, Plane, Radio, DoorOpen, Lock } from "lucide-react";
import { toast } from "sonner";

const ICONS = {
  anpr: ScanLine, ai_detection: Brain, tracking: Activity, face_recognition: ScanFace,
  parking: Car, thermal: Thermometer, radar: Radar, drone: Plane, mqtt: Radio, access_control: DoorOpen,
};
const CAT_COLOR = { Vision: "#0044FF", Capteurs: "#FFB800", "Métier": "#00E676", "Intégration": "#A855F7" };

export default function Plugins() {
  const { t, can } = useApp();
  const [plugins, setPlugins] = useState([]);
  const isAdmin = can("admin");

  const load = () => api.get("/plugins").then((r) => setPlugins(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const toggle = async (p, enabled) => {
    try { await api.put(`/plugins/${p.id}`, { enabled }); toast.success(`${p.name} ${enabled ? "activé" : "désactivé"}`); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  return (
    <div className="p-4">
      <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2 mb-1"><Puzzle size={22} /> {t("plugins.title")}</h1>
      <p className="text-sm text-muted-foreground mb-4">{t("plugins.subtitle")}</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {plugins.map((p) => {
          const Icon = ICONS[p.id] || Puzzle;
          return (
            <div key={p.id} className={`bg-card border p-4 transition-colors ${p.enabled ? "border-[#0044FF]" : "border-border"}`} data-testid="plugin-card">
              <div className="flex items-start justify-between mb-3">
                <div className="w-9 h-9 bg-secondary flex items-center justify-center"><Icon size={18} style={{ color: CAT_COLOR[p.category] || "#0044FF" }} /></div>
                <div className="flex items-center gap-2">
                  {p.core ? <Lock size={13} className="text-muted-foreground" title={t("plugins.core")} /> : null}
                  <Switch checked={p.enabled} onCheckedChange={(v) => toggle(p, v)} disabled={!isAdmin || p.core} data-testid={`plugin-toggle-${p.id}`} />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-head font-semibold">{p.name}</span>
                <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border" style={{ borderColor: CAT_COLOR[p.category], color: CAT_COLOR[p.category] }}>{p.category}</span>
              </div>
              <div className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{p.description}</div>
              <div className="flex items-center justify-between mt-3 pt-2 border-t border-border text-[10px] mono text-muted-foreground">
                <span>v{p.version}{p.core ? ` · ${t("plugins.core")}` : ""}</span>
                <span className={p.enabled ? "mg-online" : "mg-offline"}>● {p.enabled ? t("plugins.enabled") : t("plugins.disabled")}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
