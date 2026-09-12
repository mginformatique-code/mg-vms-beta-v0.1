import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Loader2, Save, Clock, Power, Radio, RefreshCw, Plus, X } from "lucide-react";
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
  const { user, t } = useApp();
  return (
    <div className="p-4 max-w-4xl" data-testid="datetime-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("dt.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("dt.subtitle")}</p>
      </div>

      <SystemClockCard admin={user?.role === "admin"} />
      <NtpCard admin={user?.role === "admin"} />
      <LiveClockCard />
    </div>
  );
}

// v3.19 · Horloge en temps réel, purement client (tick local, pas d'appel
// serveur à chaque seconde) — distincte de la "Date & heure serveur"
// ci-dessus qui ne se rafraîchit que toutes les 30s.
function LiveClockCard() {
  const { t } = useApp();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <div className="bg-card border border-border p-5 text-center" data-testid="live-clock">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("dt.live_clock_label")}</div>
      <div className="mono text-3xl font-bold tabular-nums">{now.toLocaleTimeString("fr-FR")}</div>
      <div className="text-xs text-muted-foreground mt-1">{now.toLocaleDateString("fr-FR", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</div>
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

const getAutoRebootDays = (t) => [
  ["daily", t("dt.day_daily")], ["monday", t("dt.day_monday")], ["tuesday", t("dt.day_tuesday")], ["wednesday", t("dt.day_wednesday")],
  ["thursday", t("dt.day_thursday")], ["friday", t("dt.day_friday")], ["saturday", t("dt.day_saturday")], ["sunday", t("dt.day_sunday")],
];

// v3.19 · Périmètre volontairement réduit à un reboot complet de la
// machine hôte (pas de gestion fine des conteneurs) — décision du 31 août
// pour éviter d'exposer le socket Docker ou d'élever les privilèges du
// conteneur backend. CPU/RAM/disque/uptime existent déjà dans le tableau
// de bord santé — pas dupliqués ici, uniquement date/heure + reboot.
function SystemClockCard({ admin }) {
  const { t } = useApp();
  const AUTO_REBOOT_DAYS = getAutoRebootDays(t);
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
    if (!window.confirm(t("dt.confirm_reboot"))) return;
    setRebooting(true);
    try {
      await api.post("/system/reboot");
      toast.success(t("dt.toast_reboot_scheduled"));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setRebooting(false); }
  };

  const saveAutoReboot = async () => {
    setSavingAuto(true);
    try {
      const { data } = await api.put("/system/auto-reboot", autoReboot);
      setAutoReboot(data);
      toast.success(t("dt.toast_auto_reboot_updated"));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setSavingAuto(false); }
  };

  if (!info) return null;

  return (
    <SectionCard title={t("dt.clock_card_title")} subtitle={t("dt.clock_card_subtitle")} icon={Clock}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
        <StatBox label={t("dt.lbl_server_datetime")} value={new Date(info.server_time).toLocaleString("fr-FR")} />
        <StatBox label={t("dt.lbl_timezone")} value={`${info.timezone} (UTC${info.utc_offset})`} />
      </div>

      {admin && autoReboot && (
        <>
          <div className="border-t border-border pt-4 mb-4">
            <label className="flex items-center gap-2 text-sm mb-3">
              <input type="checkbox" checked={autoReboot.enabled} onChange={(e) => setAutoReboot({ ...autoReboot, enabled: e.target.checked })} data-testid="auto-reboot-enabled" />
              {t("dt.lbl_auto_reboot")}
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("dt.lbl_frequency")}</label>
                <select value={autoReboot.day} onChange={(e) => setAutoReboot({ ...autoReboot, day: e.target.value })} data-testid="auto-reboot-day"
                        className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]">
                  {AUTO_REBOOT_DAYS.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("dt.lbl_time")}</label>
                <input type="time" value={autoReboot.time} onChange={(e) => setAutoReboot({ ...autoReboot, time: e.target.value })} data-testid="auto-reboot-time"
                       className="w-full px-3 py-2 bg-background border border-input outline-none mono focus:border-[#0044FF]" />
              </div>
            </div>
            <button onClick={saveAutoReboot} disabled={savingAuto} data-testid="auto-reboot-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm">
              {savingAuto && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> {t("common.save")}
            </button>
          </div>

          <div className="border-t border-border pt-4">
            <button onClick={rebootNow} disabled={rebooting} data-testid="system-reboot-btn" className="flex items-center gap-2 px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">
              {rebooting ? <Loader2 size={14} className="animate-spin" /> : <Power size={14} />} {t("dt.btn_reboot_now")}
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
const RESYNC_PRESETS = [24, 48, 72];

function NtpCard({ admin }) {
  const { t } = useApp();
  const [cams, setCams] = useState(null);
  const [upstream, setUpstream] = useState(null);
  const [savingUpstream, setSavingUpstream] = useState(false);
  const [resyncHours, setResyncHours] = useState(null);
  const [resyncCustom, setResyncCustom] = useState(false);
  const [savingResync, setSavingResync] = useState(false);
  const [forcingSync, setForcingSync] = useState(false);
  // v3.60 · Ajout en masse de caméras à la synchro NTP — jusqu'ici,
  // activer le serveur de temps MG-VMS sur une caméra demandait de quitter
  // cette page (Appareils → modifier → "Définir comme serveur de temps"),
  // une caméra à la fois. Menu déroulant à cocher (+ "tout cocher") pour
  // en ajouter plusieurs d'un coup depuis ici.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [applying, setApplying] = useState(false);

  const load = () => api.get("/cameras").then((r) => setCams(r.data || [])).catch(() => setCams([]));

  useEffect(() => {
    load();
    if (admin) {
      api.get("/system/ntp-upstream").then((r) => setUpstream(r.data.upstream || "")).catch(() => setUpstream(""));
      api.get("/system/ntp-resync-interval").then((r) => {
        const h = r.data.hours || 24;
        setResyncHours(h);
        setResyncCustom(!RESYNC_PRESETS.includes(h));
      }).catch(() => setResyncHours(24));
    }
  }, [admin]);

  const saveUpstream = async () => {
    setSavingUpstream(true);
    try {
      await api.put("/system/ntp-upstream", { upstream });
      toast.success(t("dt.toast_upstream_updated"));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setSavingUpstream(false); }
  };

  const saveResync = async (hours) => {
    setSavingResync(true);
    try {
      const { data } = await api.put("/system/ntp-resync-interval", { hours });
      setResyncHours(data.hours);
      toast.success(`${t("dt.toast_resync_scheduled_prefix")} ${data.hours}h`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setSavingResync(false); }
  };

  // v3.60 · "Forcer la synchro" — repousse l'heure MAINTENANT à toutes les
  // caméras `ntp_managed`, sans attendre le prochain cycle programmé
  // (24h/48h/72h) — utile après un changement réseau ou pour vérifier
  // qu'une caméra répond bien, sans devoir patienter.
  const forceSyncNow = async () => {
    setForcingSync(true);
    try {
      const { data } = await api.post("/system/ntp-resync-now");
      const okCount = data.ok?.length || 0;
      const errCount = data.errors?.length || 0;
      if (errCount === 0) {
        toast.success(okCount > 0 ? `${okCount} ${t("dt.lbl_cameras_resynced")}` : t("dt.toast_no_cameras_to_sync"));
      } else {
        toast.error(`${okCount} ${t("dt.lbl_succeeded")} ${errCount} ${t("dt.lbl_failed_see")} ${data.errors.map((e) => e.camera).join(", ")}`);
      }
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setForcingSync(false); }
  };

  const toggleSelected = (id) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  const applySelected = async () => {
    if (selectedIds.length === 0) return;
    setApplying(true);
    try {
      const { data } = await api.post("/system/ntp-apply-bulk", {
        camera_ids: selectedIds, ntp_server: window.location.hostname,
      });
      const okCount = data.ok?.length || 0;
      const errCount = data.errors?.length || 0;
      if (errCount === 0) {
        toast.success(`${okCount} ${t("dt.lbl_cameras_added_ntp")}`);
      } else {
        toast.error(`${okCount} ${t("dt.lbl_succeeded")} ${errCount} ${t("dt.lbl_failed_see")} ${data.errors.map((e) => e.camera).join(", ")}`);
      }
      setSelectedIds([]);
      setPickerOpen(false);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("dt.err_generic")); }
    finally { setApplying(false); }
  };

  if (cams === null) return null;
  const onvifCams = cams.filter((c) => c.mode === "onvif");
  const managed = cams.filter((c) => c.ntp_managed);
  const unmanaged = onvifCams.filter((c) => !c.ntp_managed);
  const allSelected = unmanaged.length > 0 && selectedIds.length === unmanaged.length;

  return (
    <SectionCard title={t("dt.ntp_card_title")} subtitle={t("dt.ntp_card_subtitle")} icon={Radio}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
        <StatBox label={t("dt.lbl_cameras_synced")} value={`${managed.length} / ${onvifCams.length} (ONVIF)`} />
        <div className="border border-border p-2 text-center">
          <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">{t("dt.lbl_resync")}</div>
          {admin && resyncHours !== null ? (
            <div className="flex items-center gap-1 justify-center">
              <select
                value={resyncCustom ? "custom" : resyncHours}
                onChange={(e) => {
                  if (e.target.value === "custom") { setResyncCustom(true); return; }
                  setResyncCustom(false);
                  saveResync(Number(e.target.value));
                }}
                disabled={savingResync} data-testid="ntp-resync-select"
                className="mono text-xs bg-background border border-input outline-none px-1.5 py-1 focus:border-[#0044FF]">
                <option value={24}>{t("dt.opt_24h_recommended")}</option>
                <option value={48}>48h</option>
                <option value={72}>72h</option>
                <option value="custom">{t("dt.opt_custom")}</option>
              </select>
              {resyncCustom && (
                <input type="number" min="1" max="720" defaultValue={resyncHours} data-testid="ntp-resync-custom"
                       onBlur={(e) => { const h = Number(e.target.value); if (h > 0) saveResync(h); }}
                       className="mono text-xs bg-background border border-input outline-none px-1.5 py-1 w-14 focus:border-[#0044FF]" />
              )}
            </div>
          ) : (
            <div className="mono text-lg font-bold mt-0.5">{t("dt.lbl_auto_24h")}</div>
          )}
        </div>
      </div>
      {managed.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {managed.map((c) => (
            <span key={c.id} className="text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">{c.name}</span>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-start gap-2 mb-3">
        {admin && managed.length > 0 && (
          <button onClick={forceSyncNow} disabled={forcingSync} data-testid="ntp-force-sync"
                  className="flex items-center gap-2 px-4 py-2 border border-[#0044FF] text-[#0044FF] text-sm hover:bg-[#0044FF]/10 disabled:opacity-50">
            {forcingSync ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {t("dt.btn_force_sync_prefix")} ({managed.length})
          </button>
        )}
        {admin && unmanaged.length > 0 && (
          <div className="relative">
            <button onClick={() => setPickerOpen((v) => !v)} data-testid="ntp-add-cameras-btn"
                    className="flex items-center gap-2 px-4 py-2 border border-[#00E676] text-[#00E676] text-sm hover:bg-[#00E676]/10">
              <Plus size={14} /> {t("dt.btn_add_cameras_prefix")} ({unmanaged.length} {t("dt.lbl_not_synced")})
            </button>
            {pickerOpen && (
              <div className="absolute top-full left-0 mt-1 z-30 bg-card border border-border shadow-lg w-72" data-testid="ntp-add-cameras-panel">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                  <label className="flex items-center gap-2 text-xs font-medium cursor-pointer">
                    <input type="checkbox" checked={allSelected}
                           onChange={(e) => setSelectedIds(e.target.checked ? unmanaged.map((c) => c.id) : [])}
                           data-testid="ntp-select-all" />
                    {t("dt.lbl_select_all")}
                  </label>
                  <button onClick={() => setPickerOpen(false)} className="text-muted-foreground hover:text-foreground">
                    <X size={14} />
                  </button>
                </div>
                <div className="max-h-56 overflow-y-auto">
                  {unmanaged.map((c) => (
                    <label key={c.id} className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary/50 cursor-pointer">
                      <input type="checkbox" checked={selectedIds.includes(c.id)} onChange={() => toggleSelected(c.id)} />
                      <span className="truncate">{c.name}</span>
                      <span className="text-muted-foreground ml-auto">{c.site_name || "—"}</span>
                    </label>
                  ))}
                </div>
                <div className="px-3 py-2 border-t border-border">
                  <button onClick={applySelected} disabled={applying || selectedIds.length === 0} data-testid="ntp-apply-selected"
                          className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-[#0044FF] text-white text-xs disabled:opacity-40">
                    {applying && <Loader2 size={13} className="animate-spin" />}
                    {t("dt.btn_apply_config_prefix")} ({selectedIds.length})
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground leading-relaxed mb-4">
        {t("dt.hint_enable_single_camera")}
      </p>

      {admin && upstream !== null && (
        <div className="border-t border-border pt-4">
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("dt.lbl_ntp_upstream")}</label>
          <p className="text-[11px] text-muted-foreground leading-relaxed mb-2">
            {t("dt.ntp_upstream_hint")}
          </p>
          <div className="flex gap-2">
            <input value={upstream} onChange={(e) => setUpstream(e.target.value)} placeholder={t("dt.ph_ntp_upstream_example")} data-testid="ntp-upstream-input"
                   className="flex-1 px-3 py-2 bg-background border border-input outline-none mono text-sm focus:border-[#0044FF]" />
            <button onClick={saveUpstream} disabled={savingUpstream} data-testid="ntp-upstream-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm shrink-0">
              {savingUpstream && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> {t("common.save")}
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}
