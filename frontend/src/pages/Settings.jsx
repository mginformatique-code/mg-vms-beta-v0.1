import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Moon, Sun, Languages, ShieldCheck, Monitor, Loader2, HardDrive, Save, Trash2, PlayCircle } from "lucide-react";
import { toast } from "sonner";

export default function SettingsPage() {
  const { t, theme, setTheme, lang, setLang, user, setUser } = useApp();
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);

  const start2fa = async () => {
    setLoading(true);
    try { const { data } = await api.post("/auth/2fa/setup"); setSetup(data); } catch (e) { toast.error("Erreur"); } finally { setLoading(false); }
  };
  const verify2fa = async () => {
    try { await api.post("/auth/2fa/verify", { code }); toast.success("2FA activée"); setUser({ ...user, twofa_enabled: true }); setSetup(null); setCode(""); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const disable2fa = async () => { await api.post("/auth/2fa/disable"); toast.success("2FA désactivée"); setUser({ ...user, twofa_enabled: false }); };

  // eslint-disable-next-line react/no-unstable-nested-components
  const Card = ({ title, icon: Icon, children }) => (
    <div className="bg-card border border-border p-5 mb-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4"><Icon size={15} /> {title}</div>
      {children}
    </div>
  );
  // eslint-disable-next-line react/no-unstable-nested-components
  const Opt = ({ active, onClick, icon: Icon, label, tid }) => (
    <button onClick={onClick} data-testid={tid} className={`flex items-center gap-2 px-4 py-2.5 border text-sm transition-colors ${active ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]" : "border-border hover:bg-secondary"}`}>
      <Icon size={16} /> {label}
    </button>
  );

  return (
    <div className="p-4 max-w-3xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-4">{t("settings.title")}</h1>

      <Card title={t("settings.appearance")} icon={Monitor}>
        <div className="text-xs text-muted-foreground mb-2">{t("settings.theme")}</div>
        <div className="flex gap-2 mb-5">
          <Opt active={theme === "dark"} onClick={() => setTheme("dark")} icon={Moon} label="Dark" tid="theme-dark" />
          <Opt active={theme === "light"} onClick={() => setTheme("light")} icon={Sun} label="Light" tid="theme-light" />
        </div>
        <div className="text-xs text-muted-foreground mb-2">{t("settings.language")}</div>
        <div className="flex gap-2">
          <Opt active={lang === "fr"} onClick={() => setLang("fr")} icon={Languages} label="Français" tid="lang-fr" />
          <Opt active={lang === "en"} onClick={() => setLang("en")} icon={Languages} label="English" tid="lang-en" />
        </div>
      </Card>

      <Card title={t("settings.security")} icon={ShieldCheck}>
        <div className="text-sm font-medium mb-1">{t("settings.twofa")}</div>
        <div className="text-xs text-muted-foreground mb-4">
          {user?.twofa_enabled ? <span className="mg-online">● Activée</span> : <span className="mg-offline">● Désactivée</span>}
        </div>
        {user?.twofa_enabled ? (
          <button onClick={disable2fa} data-testid="disable-2fa-btn" className="px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">{t("settings.twofa_disable")}</button>
        ) : setup ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{t("settings.scan")}</p>
            <img src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(setup.otpauth_uri)}`} alt="QR" className="bg-white p-2" />
            <div className="text-[10px] mono text-muted-foreground break-all">SECRET: {setup.secret}</div>
            <div className="flex gap-2">
              <input value={code} onChange={(e) => setCode(e.target.value)} data-testid="2fa-code" placeholder="000000" className="px-3 py-2 bg-card border border-input outline-none mono tracking-[0.3em] text-center w-32" />
              <button onClick={verify2fa} data-testid="verify-2fa-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.confirm")}</button>
            </div>
          </div>
        ) : (
          <button onClick={start2fa} disabled={loading} data-testid="enable-2fa-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{loading && <Loader2 size={15} className="animate-spin" />}{t("settings.twofa_enable")}</button>
        )}
      </Card>

      <Card title="Compte" icon={ShieldCheck}>
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <span className="text-muted-foreground">{t("common.name")}</span><span>{user?.name}</span>
          <span className="text-muted-foreground">{t("common.email")}</span><span className="mono">{user?.email}</span>
          <span className="text-muted-foreground">{t("common.role")}</span><span className="uppercase text-[#0044FF]">{user?.role}</span>
        </div>
      </Card>

      {user?.role === "admin" && <RetentionCard />}
      {user?.role === "admin" && <StorageCard />}
    </div>
  );
}

const RetentionCard2 = ({ title, icon: Icon, children }) => (
  <div className="bg-card border border-border p-5 mb-3">
    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4"><Icon size={15} /> {title}</div>
    {children}
  </div>
);

function RetentionCard() {
  const [state, setState] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [purging, setPurging] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/settings/retention"); setState(data); setForm({ ...data.config }); }
    catch (e) { /* ignore */ }
  };
  useEffect(() => { load(); const iv = setInterval(load, 30000); return () => clearInterval(iv); }, []);

  if (!state || !form) return null;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/settings/retention", {
        retention_days: Number(form.retention_days),
        min_free_gb: Number(form.min_free_gb),
        max_disk_pct: Number(form.max_disk_pct),
      });
      setState(data); toast.success("Rétention mise à jour"); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
    finally { setSaving(false); }
  };

  const purgeNow = async () => {
    if (!window.confirm("Lancer la purge maintenant ? Les enregistrements dépassant les seuils seront supprimés.")) return;
    setPurging(true);
    try {
      const { data } = await api.post("/settings/retention/run");
      toast.success(`Purge terminée : ${data.deleted_by_age} par âge + ${data.deleted_by_quota} par quota, ${data.freed_gb} Go libérés`);
      load();
    } catch (e) { toast.error("Purge échouée"); }
    finally { setPurging(false); }
  };

  const usedPct = state.disk.used_pct;
  const usedColor = usedPct > form.max_disk_pct ? "#FF3333" : usedPct > form.max_disk_pct - 10 ? "#FFB800" : "#00E676";

  return (
    <RetentionCard2 title="Rétention & stockage vidéo" icon={HardDrive}>
      {/* Statut disque + volume enregistrements */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <StatBox label="Disque total" value={`${state.disk.total_gb} Go`} />
        <StatBox label="Utilisé" value={`${state.disk.used_gb} Go`} color={usedColor} />
        <StatBox label="Libre" value={`${state.disk.free_gb} Go`} color={state.disk.free_gb < form.min_free_gb ? "#FF3333" : undefined} />
        <StatBox label="Occupation" value={`${usedPct}%`} color={usedColor} />
      </div>
      <div className="h-2 bg-secondary mb-4 relative overflow-hidden">
        <div className="h-full transition-all" style={{ width: `${Math.min(100, usedPct)}%`, backgroundColor: usedColor }} data-testid="disk-bar" />
        <div className="absolute top-0 h-full w-px bg-white/40" style={{ left: `${form.max_disk_pct}%` }} title={`Seuil ${form.max_disk_pct}%`} />
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatBox label="Enregistrements" value={state.recordings.count} small />
        <StatBox label="Volume total" value={`${state.recordings.size_gb} Go`} small />
        <StatBox label="Plus ancien" value={state.recordings.oldest ? new Date(state.recordings.oldest).toLocaleDateString("fr-FR") : "—"} small />
      </div>

      {/* Édition des seuils */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Conservation (jours)</label>
          <input type="number" min="1" max="365" value={form.retention_days} onChange={(e) => setForm({ ...form, retention_days: e.target.value })} data-testid="retention-days" className="w-full px-3 py-2 bg-background border border-input outline-none mono focus:border-[#0044FF]" />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Espace libre min. (Go)</label>
          <input type="number" min="0.5" step="0.5" value={form.min_free_gb} onChange={(e) => setForm({ ...form, min_free_gb: e.target.value })} data-testid="retention-free" className="w-full px-3 py-2 bg-background border border-input outline-none mono focus:border-[#0044FF]" />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Occupation max. (%)</label>
          <input type="number" min="10" max="99" value={form.max_disk_pct} onChange={(e) => setForm({ ...form, max_disk_pct: e.target.value })} data-testid="retention-pct" className="w-full px-3 py-2 bg-background border border-input outline-none mono focus:border-[#0044FF]" />
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground mt-2 leading-relaxed">
        Les vidéos plus anciennes que <b>{form.retention_days} jours</b> sont supprimées automatiquement. Si l&apos;espace libre passe sous <b>{form.min_free_gb} Go</b> <i>ou</i> si l&apos;occupation dépasse <b>{form.max_disk_pct}%</b>, les <b>plus anciens segments</b> sont supprimés en priorité.
      </p>

      <div className="mt-4 flex gap-2">
        <button onClick={save} disabled={saving} data-testid="retention-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm">
          {saving && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> Enregistrer les seuils
        </button>
        <button onClick={purgeNow} disabled={purging} data-testid="retention-purge" className="flex items-center gap-2 px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">
          {purging ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />} Purger maintenant
        </button>
      </div>
    </RetentionCard2>
  );
}

function StatBox({ label, value, color, small }) {
  return (
    <div className="border border-border p-2 text-center">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={small ? "mono text-xs mt-0.5" : "mono text-lg font-bold mt-0.5"} style={color ? { color } : undefined}>{value}</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Multi-disques : détection auto + ajout manuel + assignation caméras
// ═══════════════════════════════════════════════════════════════════
function StorageCard() {
  const [state, setState] = useState(null);
  const [newPool, setNewPool] = useState({ name: "", path: "", enabled: true, max_size_gb: 0, priority: 0 });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/storage/overview"); setState(data); }
    catch (e) { /* ignore */ }
  };
  useEffect(() => { load(); const iv = setInterval(load, 60000); return () => clearInterval(iv); }, []);

  const addPool = async () => {
    if (!newPool.path.trim()) return toast.error("Chemin requis");
    setSaving(true);
    try {
      await api.post("/storage/pools", {
        ...newPool, max_size_gb: Number(newPool.max_size_gb) || 0, priority: Number(newPool.priority) || 0,
      });
      toast.success("Pool ajouté"); setNewPool({ name: "", path: "", enabled: true, max_size_gb: 0, priority: 0 }); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
    finally { setSaving(false); }
  };

  const updatePool = async (pool, patch) => {
    try { await api.put(`/storage/pools/${pool.id}`, { ...pool, ...patch }); load(); toast.success("Pool mis à jour"); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  const delPool = async (id) => {
    if (!window.confirm("Supprimer ce pool ? (les fichiers ne sont pas effacés)")) return;
    try { await api.delete(`/storage/pools/${id}`); load(); toast.success("Pool supprimé"); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  if (!state) return null;

  return (
    <div className="bg-card border border-border p-5 mb-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4"><HardDrive size={15} /> Stockage multi-disques</div>

      <div className="text-[11px] mono text-muted-foreground mb-2">Dossier d'enregistrement principal : {state.primary_recordings_dir}</div>

      {/* Partitions détectées */}
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Partitions physiques détectées ({state.partitions.length})</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
        {state.partitions.map((p, i) => (
          <div key={i} className="border border-border p-2 text-xs">
            <div className="flex items-center justify-between">
              <div><span className="mono text-[#0044FF]">{p.mountpoint}</span> <span className="text-muted-foreground">({p.fstype})</span></div>
              <button onClick={() => setNewPool({ ...newPool, path: p.mountpoint, name: newPool.name || p.mountpoint })}
                      className="text-[10px] px-2 py-0.5 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10"
                      data-testid={`use-partition-${i}`}>
                Utiliser
              </button>
            </div>
            <div className="mono text-[10px] text-muted-foreground mt-1">{p.device} · {p.total_gb} Go · libre {p.free_gb} Go ({100 - Math.round(p.used_pct)}%)</div>
            <div className="h-1 bg-secondary mt-1"><div className="h-full" style={{ width: `${p.used_pct}%`, backgroundColor: p.used_pct > 85 ? "#FF3333" : p.used_pct > 70 ? "#FFB800" : "#00E676" }} /></div>
          </div>
        ))}
      </div>

      {/* Pools de stockage déclarés */}
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Pools de stockage ({state.pools.length})</div>
      {state.pools.length === 0 && <p className="text-xs text-muted-foreground mb-2">Aucun pool déclaré. Les enregistrements vont dans le dossier principal.</p>}
      <div className="space-y-2 mb-3">
        {state.pools.map((pool) => (
          <div key={pool.id} className="border border-border p-3">
            <div className="flex items-center justify-between mb-2">
              <div>
                <span className="font-medium">{pool.name}</span>
                <span className="mono text-[10px] text-muted-foreground ml-2">{pool.path}</span>
                {!pool.enabled && <span className="ml-2 text-[10px] text-[#FFB800]">DÉSACTIVÉ</span>}
              </div>
              <div className="flex gap-1">
                <button onClick={() => updatePool(pool, { enabled: !pool.enabled })} className="text-[10px] px-2 py-0.5 border border-border hover:bg-secondary" data-testid={`pool-toggle-${pool.id}`}>{pool.enabled ? "Désactiver" : "Activer"}</button>
                <button onClick={() => delPool(pool.id)} className="text-[10px] px-2 py-0.5 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10"><Trash2 size={10} /></button>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-2 text-[10px]">
              <div><div className="text-muted-foreground uppercase">Disque total</div><div className="mono">{pool.usage?.total_gb} Go</div></div>
              <div><div className="text-muted-foreground uppercase">Libre</div><div className="mono">{pool.usage?.free_gb} Go</div></div>
              <div><div className="text-muted-foreground uppercase">Enregistrements</div><div className="mono">{pool.recordings_count} · {pool.recordings_size_gb} Go</div></div>
              <div>
                <div className="text-muted-foreground uppercase">Quota (Go)</div>
                <input type="number" min="0" defaultValue={pool.max_size_gb}
                       onBlur={(e) => updatePool(pool, { max_size_gb: Number(e.target.value) })}
                       className="w-full px-1.5 py-0.5 bg-background border border-input outline-none mono text-[10px]"
                       title="0 = illimité" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Ajout manuel */}
      <div className="border border-dashed border-border p-3">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Ajouter un pool manuellement</div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
          <input placeholder="Nom" value={newPool.name} onChange={(e) => setNewPool({ ...newPool, name: e.target.value })} className="px-2 py-1.5 bg-background border border-input outline-none text-xs" data-testid="pool-new-name" />
          <input placeholder="/mnt/nas/videos" value={newPool.path} onChange={(e) => setNewPool({ ...newPool, path: e.target.value })} className="px-2 py-1.5 bg-background border border-input outline-none text-xs mono md:col-span-2" data-testid="pool-new-path" />
          <input type="number" min="0" placeholder="Quota Go (0=illim)" value={newPool.max_size_gb} onChange={(e) => setNewPool({ ...newPool, max_size_gb: e.target.value })} className="px-2 py-1.5 bg-background border border-input outline-none text-xs mono" />
          <button onClick={addPool} disabled={saving} className="flex items-center justify-center gap-1 px-3 py-1.5 bg-[#0044FF] text-white text-xs" data-testid="pool-add">
            {saving && <Loader2 size={11} className="animate-spin" />}<Save size={11} /> Ajouter
          </button>
        </div>
      </div>
    </div>
  );
}
