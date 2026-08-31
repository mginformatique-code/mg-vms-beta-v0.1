import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Loader2, Save, Clock, Power, Radio } from "lucide-react";
import { toast } from "sonner";

/**
 * Page Date et heure — v3.19
 *
 * Séparée de Paramètres (Stockage) sur demande explicite du 31 août —
 * regroupe tout ce qui touche au temps : horloge serveur, redémarrage
 * programmé de la machine, et l'état du serveur NTP embarqué (chrony)
 * qui sert l'heure aux caméras (le réglage par caméra reste dans
 * Appareils → modifier, à côté des autres réglages caméra).
 */
export default function DateHeurePage() {
  const { user } = useApp();
  return (
    <div className="p-4 max-w-4xl" data-testid="datetime-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight">Date et heure</h1>
        <p className="text-sm text-muted-foreground mt-1">Horloge serveur, redémarrage programmé, serveur de temps (NTP) pour les caméras.</p>
      </div>

      <SystemClockCard admin={user?.role === "admin"} />
      <NtpCard />
    </div>
  );
}

function SectionCard({ title, subtitle, icon: Icon, children }) {
  return (
    <div className="bg-card border border-border p-5 mb-4">
      <div className="mb-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground">
          <Icon size={15} /> {title}
        </div>
        {subtitle && <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function StatBox({ label, value }) {
  return (
    <div className="border border-border p-2 text-center">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mono text-lg font-bold mt-0.5">{value}</div>
    </div>
  );
}

const AUTO_REBOOT_DAYS = [
  ["daily", "Tous les jours"], ["monday", "Lundi"], ["tuesday", "Mardi"], ["wednesday", "Mercredi"],
  ["thursday", "Jeudi"], ["friday", "Vendredi"], ["saturday", "Samedi"], ["sunday", "Dimanche"],
];

// v3.19 · Périmètre volontairement réduit à un reboot complet de la
// machine hôte (pas de gestion fine des conteneurs) — décision du 31 août
// pour éviter d'exposer le socket Docker ou d'élever les privilèges du
// conteneur backend. CPU/RAM/disque/uptime existent déjà dans le tableau
// de bord santé — pas dupliqués ici, uniquement date/heure + reboot.
function SystemClockCard({ admin }) {
  const [info, setInfo] = useState(null);
  const [autoReboot, setAutoReboot] = useState(null);
  const [savingAuto, setSavingAuto] = useState(false);
  const [rebooting, setRebooting] = useState(false);

  const load = () => {
    api.get("/system/info").then((r) => setInfo(r.data)).catch(() => {});
    if (admin) api.get("/system/auto-reboot").then((r) => setAutoReboot(r.data)).catch(() => {});
  };
  useEffect(() => { load(); const iv = setInterval(load, 30000); return () => clearInterval(iv); }, [admin]);

  const rebootNow = async () => {
    if (!window.confirm("Redémarrer la machine maintenant ? Toutes les caméras et le service seront coupés le temps du redémarrage.")) return;
    setRebooting(true);
    try {
      await api.post("/system/reboot");
      toast.success("Redémarrage programmé — la machine va redémarrer sous peu.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
    finally { setRebooting(false); }
  };

  const saveAutoReboot = async () => {
    setSavingAuto(true);
    try {
      const { data } = await api.put("/system/auto-reboot", autoReboot);
      setAutoReboot(data);
      toast.success("Reboot automatique mis à jour");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
    finally { setSavingAuto(false); }
  };

  if (!info) return null;

  return (
    <SectionCard title="Horloge serveur" subtitle="Date/heure du serveur MG-VMS." icon={Clock}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
        <StatBox label="Date & heure serveur" value={new Date(info.server_time).toLocaleString("fr-FR")} />
        <StatBox label="Fuseau horaire" value={`${info.timezone} (UTC${info.utc_offset})`} />
      </div>

      {admin && autoReboot && (
        <>
          <div className="border-t border-border pt-4 mb-4">
            <label className="flex items-center gap-2 text-sm mb-3">
              <input type="checkbox" checked={autoReboot.enabled} onChange={(e) => setAutoReboot({ ...autoReboot, enabled: e.target.checked })} data-testid="auto-reboot-enabled" />
              Redémarrage automatique programmé
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Fréquence</label>
                <select value={autoReboot.day} onChange={(e) => setAutoReboot({ ...autoReboot, day: e.target.value })} data-testid="auto-reboot-day"
                        className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]">
                  {AUTO_REBOOT_DAYS.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Heure</label>
                <input type="time" value={autoReboot.time} onChange={(e) => setAutoReboot({ ...autoReboot, time: e.target.value })} data-testid="auto-reboot-time"
                       className="w-full px-3 py-2 bg-background border border-input outline-none mono focus:border-[#0044FF]" />
              </div>
            </div>
            <button onClick={saveAutoReboot} disabled={savingAuto} data-testid="auto-reboot-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm">
              {savingAuto && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> Enregistrer
            </button>
          </div>

          <div className="border-t border-border pt-4">
            <button onClick={rebootNow} disabled={rebooting} data-testid="system-reboot-btn" className="flex items-center gap-2 px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">
              {rebooting ? <Loader2 size={14} className="animate-spin" /> : <Power size={14} />} Redémarrer la machine maintenant
            </button>
          </div>
        </>
      )}
    </SectionCard>
  );
}

// v3.19 · Vue d'ensemble du serveur NTP (chrony, côté hôte) — le réglage
// par caméra ("Définir comme serveur de temps") reste dans Appareils →
// modifier, à côté des autres réglages de cette caméra ; pas dupliqué ici,
// juste un décompte.
function NtpCard() {
  const [cams, setCams] = useState(null);

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data || [])).catch(() => setCams([]));
  }, []);

  if (cams === null) return null;
  const onvifCams = cams.filter((c) => c.mode === "onvif");
  const managed = cams.filter((c) => c.ntp_managed);

  return (
    <SectionCard title="Serveur de temps (NTP)" subtitle="MG-VMS sert l'heure aux caméras du réseau — évite les horloges qui dérivent ou se perdent après un reboot caméra." icon={Radio}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
        <StatBox label="Caméras synchronisées" value={`${managed.length} / ${onvifCams.length} (ONVIF)`} />
        <StatBox label="Resynchronisation" value="Auto — toutes les 24h" />
      </div>
      {managed.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {managed.map((c) => (
            <span key={c.id} className="text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">{c.name}</span>
          ))}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        Pour activer une caméra : Appareils → modifier la caméra (mode ONVIF) → "Définir comme serveur de temps".
      </p>
    </SectionCard>
  );
}
