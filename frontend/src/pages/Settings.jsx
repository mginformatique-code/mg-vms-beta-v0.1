import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import {
  Loader2, HardDrive, Save, Trash2, PlayCircle, Database, RefreshCw,
  CheckCircle2, XCircle, AlertTriangle, Server, Film, Info,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Page Stockage — v0.5.7
 *
 * Trois disques dédiés recommandés :
 *   1. Application VMS (système où tourne MG-VMS)
 *   2. Base de données (MongoDB)
 *   3. Enregistrements vidéo (pool caméras)
 *
 * Les préférences d'apparence & de langue sont accessibles dans la
 * barre supérieure droite du Layout — elles ne sont plus dupliquées ici.
 */
export default function SettingsPage() {
  const { t, user } = useApp();
  return (
    <div className="p-4 max-w-4xl" data-testid="storage-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("storage.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("storage.subtitle")}</p>
      </div>

      <Tip text={t("storage.tip")} />

      <VMSDiskCard />
      {user?.role === "admin" && <DatabaseCard />}
      {user?.role === "admin" && <RetentionCard />}
      {user?.role === "admin" && <VideoPoolsCard />}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// UI helpers
// ═══════════════════════════════════════════════════════════════════
function SectionCard({ id, title, subtitle, icon: Icon, badge, children }) {
  return (
    <div id={id} className="bg-card border border-border p-5 mb-4 scroll-mt-4">
      <div className="flex items-start justify-between mb-3 gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground">
            <Icon size={15} /> {title}
          </div>
          {subtitle && <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{subtitle}</p>}
        </div>
        {badge}
      </div>
      {children}
    </div>
  );
}

function Tip({ text }) {
  return (
    <div className="border border-border bg-secondary/40 p-3 mb-4 flex items-start gap-2 text-xs text-muted-foreground" data-testid="storage-tip">
      <Info size={14} className="text-[#0044FF] mt-0.5 flex-shrink-0" />
      <span>{text}</span>
    </div>
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

function UsageBar({ pct, threshold }) {
  const color = pct > 85 ? "#FF3333" : pct > 70 ? "#FFB800" : "#00E676";
  return (
    <div className="h-2 bg-secondary mb-3 relative overflow-hidden">
      <div className="h-full transition-all" style={{ width: `${Math.min(100, pct || 0)}%`, backgroundColor: color }} />
      {threshold && <div className="absolute top-0 h-full w-px bg-white/40" style={{ left: `${threshold}%` }} title={`Seuil ${threshold}%`} />}
    </div>
  );
}

function DedicatedBadge({ ok, labelOk = "Dédié", labelWarn = "Partagé" }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 border ${ok ? "text-[#00E676] border-[#00E676]/60 bg-[#00E676]/10" : "text-[#FFB800] border-[#FFB800]/60 bg-[#FFB800]/10"}`}
      data-testid={ok ? "badge-dedicated" : "badge-shared"}
    >
      {ok ? labelOk : labelWarn}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Utils : détecte le disque (déjà dédupliqué par device) qui contient un
// chemin donné, en cherchant le préfixe le plus long parmi TOUS ses points
// de montage (un disque physique peut être bind-monté à plusieurs endroits).
// ═══════════════════════════════════════════════════════════════════
function partitionFor(partitions, targetPath) {
  if (!partitions?.length || !targetPath) return null;
  let best = null, bestLen = -1;
  for (const p of partitions) {
    for (const mp of (p.mountpoints && p.mountpoints.length ? p.mountpoints : [p.mountpoint || "/"])) {
      if (targetPath === mp || targetPath.startsWith(mp === "/" ? "/" : mp + "/")) {
        if (mp.length > bestLen) { best = p; bestLen = mp.length; }
      }
    }
  }
  // Pas de fallback sur partitions[0] : mieux vaut "non détecté" qu'un
  // disque sans rapport affiché avec confiance (ex: bug historique où
  // "/app" ne matchait jamais rien et retombait sur une partition random).
  return best;
}

const DISK_TYPE_LABEL = { nvme: "NVMe", ssd: "SSD", hdd: "HDD", unknown: "Inconnu" };
const DISK_TYPE_COLOR = { nvme: "#0044FF", ssd: "#00E676", hdd: "#FFB800", unknown: "#8892a0" };

function DiskTypeBadge({ type }) {
  const t = type || "unknown";
  const color = DISK_TYPE_COLOR[t] || DISK_TYPE_COLOR.unknown;
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 border font-bold"
      style={{ color, borderColor: `${color}99`, backgroundColor: `${color}1A` }}
      data-testid={`disk-type-${t}`}
    >
      {DISK_TYPE_LABEL[t] || t}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 1. Disque VMS (application)
// ═══════════════════════════════════════════════════════════════════
function VMSDiskCard() {
  const { t } = useApp();
  const [state, setState] = useState(null);

  useEffect(() => {
    let mounted = true;
    api.get("/storage/overview")
      .then(({ data }) => { if (mounted) setState(data); })
      .catch(() => {});
    return () => { mounted = false; };
  }, []);

  // "/app" (racine du conteneur) n'est jamais un point de montage détectable
  // séparément — on utilise /logs, garanti présent et sur le même disque.
  const vmsPart = useMemo(() => partitionFor(state?.partitions, "/logs"), [state]);
  const videoPart = useMemo(() => partitionFor(state?.partitions, state?.primary_recordings_dir), [state]);
  const isDedicated = vmsPart && videoPart && vmsPart.device !== videoPart.device;

  const usedPct = vmsPart?.used_pct ?? 0;

  return (
    <SectionCard
      id="vms-disk"
      title={t("storage.vms")}
      subtitle={t("storage.vms_desc")}
      icon={Server}
      badge={vmsPart && <DedicatedBadge ok={isDedicated} />}
    >
      {!state && <div className="text-xs text-muted-foreground flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Chargement…</div>}
      {state && !vmsPart && <p className="text-xs text-muted-foreground">Impossible de détecter la partition système.</p>}
      {vmsPart && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
            <StatBox label={t("storage.vms_mount")} value={vmsPart.mountpoint} small />
            <StatBox label="Type" value={<DiskTypeBadge type={vmsPart.type} />} small />
            <StatBox label={t("storage.vms_total")} value={`${vmsPart.total_gb} Go`} />
            <StatBox label={t("storage.vms_used")} value={`${vmsPart.used_gb} Go`} color={usedPct > 85 ? "#FF3333" : usedPct > 70 ? "#FFB800" : undefined} />
            <StatBox label={t("storage.vms_free")} value={`${vmsPart.free_gb} Go`} color={usedPct > 85 ? "#FF3333" : undefined} />
          </div>
          <UsageBar pct={usedPct} />
          <div className="mono text-[10px] text-muted-foreground" data-testid="vms-device">
            {vmsPart.device} ({vmsPart.fstype}) · {usedPct}% utilisé
          </div>
          {!isDedicated && (
            <div className="mt-3 text-[11px] text-[#FFB800] flex items-start gap-1.5">
              <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
              <span>
                L&apos;application et les enregistrements vidéo partagent la même partition. Pour un déploiement production,
                montez un disque dédié aux enregistrements (voir la section <b>Enregistrements vidéo</b> ci-dessous).
              </span>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 2. Base de données (Mongo dédié)
// ═══════════════════════════════════════════════════════════════════
function DatabaseCard() {
  const { t } = useApp();
  const [state, setState] = useState(null);
  const [form, setForm] = useState({ mongo_url: "", db_name: "" });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/settings/database"); setState(data); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Erreur chargement"); }
  };
  useEffect(() => { load(); }, []);

  const test = async () => {
    if (!form.mongo_url || !form.db_name) { toast.error("URI et nom de base requis"); return; }
    setTesting(true); setTestResult(null);
    try {
      const { data } = await api.post("/settings/database/test", form);
      setTestResult({ ok: true, ...data });
    } catch (e) {
      setTestResult({ ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message });
    } finally { setTesting(false); }
  };

  const save = async () => {
    if (!testResult?.ok) { toast.error("Testez d'abord la connexion avec succès avant d'enregistrer"); return; }
    if (!window.confirm("Confirmer l'enregistrement ?\n\nLe fichier /app/backend/.env sera modifié.\nLe backend devra être redémarré pour appliquer la nouvelle URI.")) return;
    setSaving(true);
    try {
      await api.put("/settings/database", form);
      toast.success("Config sauvegardée — redémarrage requis");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
    finally { setSaving(false); }
  };

  const restart = async () => {
    if (!window.confirm("Redémarrer le backend ?\n\nVous serez déconnecté quelques secondes. Reconnectez-vous ensuite.")) return;
    setRestarting(true);
    try {
      await api.post("/settings/database/restart-backend", { confirm: true });
      toast.info("Redémarrage en cours…");
      setTimeout(() => window.location.reload(), 6000);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
      setRestarting(false);
    }
  };

  const c = state?.current;
  // Une DB « dédiée » côté frontend = URI hors localhost / hors 127.0.0.1 (donc serveur distant).
  const isDedicated = c?.mongo_url_redacted &&
    !/localhost|127\.0\.0\.1|::1/.test(c.mongo_url_redacted);

  return (
    <SectionCard
      id="database"
      title={t("storage.db")}
      subtitle={t("storage.db_desc")}
      icon={Database}
      badge={c && <DedicatedBadge ok={isDedicated} labelOk="Serveur dédié" labelWarn="Serveur local" />}
    >
      <div className="border border-[#0044FF]/40 bg-[#0044FF]/5 p-3 mb-4 flex items-start gap-2" data-testid="db-nvme-warning">
        <AlertTriangle size={14} className="text-[#0044FF] flex-shrink-0 mt-0.5" />
        <div className="text-[11px] text-muted-foreground leading-relaxed">
          <b className="text-foreground">MongoDB fait beaucoup d&apos;écritures aléatoires</b> (un événement/plaque = plusieurs
          écritures). Un disque <b className="text-[#0044FF]">NVMe (ou SSD à défaut)</b> dédié à la base change directement la
          latence de toute l&apos;API — un HDD la ralentit fortement. Emplacement disque local :
          variable <code className="mono">MONGO_DATA_PATH</code> dans <code className="mono">deploy-app/.env</code>, appliquée
          via <code className="mono">./install.sh</code> (le conteneur MongoDB étant séparé, ce n&apos;est pas modifiable ici en un clic).
          {" "}<b className="text-[#FF3333]">⚠ Changer ce chemin sur une install existante ne déplace PAS les données</b> :
          copiez d&apos;abord le contenu de l&apos;ancien dossier vers le nouveau, sinon MongoDB redémarre avec une base vide.
        </div>
      </div>
      {c && (
        <div className="border border-border p-3 mb-4 bg-background">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Connexion active</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            <div>
              <div className="text-[10px] text-muted-foreground">URI (masquée)</div>
              <div className="mono text-xs break-all" data-testid="db-current-uri">{c.mongo_url_redacted || "—"}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground">Nom de base</div>
              <div className="mono text-xs" data-testid="db-current-name">{c.db_name || "—"}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground">Statut</div>
              <div className="flex items-center gap-1.5 text-xs">
                {c.status === "ok"
                  ? <><CheckCircle2 size={12} className="mg-online" /> <span className="mg-online mono">OK</span></>
                  : <><XCircle size={12} className="mg-error" /> <span className="mg-error mono">{c.status}</span></>}
                {c.ping_ms !== null && c.ping_ms !== undefined && <span className="text-muted-foreground mono">· {c.ping_ms}ms</span>}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground">Collections</div>
              <div className="mono text-xs">{c.collections ?? "—"}</div>
            </div>
          </div>
        </div>
      )}

      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Nouvelle configuration</div>
      <div className="grid grid-cols-1 gap-2 mb-3">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">URI MongoDB</label>
          <input type="text" placeholder="mongodb://user:password@serveur-mongo:27017 · mongodb+srv://..." value={form.mongo_url}
                 onChange={(e) => { setForm({ ...form, mongo_url: e.target.value }); setTestResult(null); }}
                 data-testid="db-new-uri"
                 className="w-full px-3 py-2 bg-background border border-input outline-none mono text-xs focus:border-[#0044FF]" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Nom de base</label>
          <input type="text" placeholder="mg_vms_prod" value={form.db_name}
                 onChange={(e) => { setForm({ ...form, db_name: e.target.value }); setTestResult(null); }}
                 data-testid="db-new-name"
                 className="w-full px-3 py-2 bg-background border border-input outline-none mono text-xs focus:border-[#0044FF]" />
        </div>
      </div>

      {testResult && (
        <div className="border p-3 mb-3 text-xs mono"
             style={{ borderColor: testResult.ok ? "#00E676" : "#FF3333",
                       background: testResult.ok ? "rgba(0,230,118,0.05)" : "rgba(255,51,51,0.05)" }}
             data-testid="db-test-result">
          {testResult.ok ? (
            <div>
              <div className="flex items-center gap-1.5 mg-online mb-1"><CheckCircle2 size={12} /> Connexion réussie</div>
              <div className="text-muted-foreground">Ping : <b>{testResult.ping_ms}ms</b> · Collections : <b>{testResult.collections}</b> · Caméras : <b>{testResult.cameras_count}</b></div>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 mg-error"><XCircle size={12} /> {testResult.error}</div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-3">
        <button onClick={test} disabled={testing || !form.mongo_url || !form.db_name}
                data-testid="db-test-btn"
                className="flex items-center gap-2 px-4 py-2 border border-[#0044FF] text-[#0044FF] text-sm hover:bg-[#0044FF]/10 disabled:opacity-40">
          {testing ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />} Tester la connexion
        </button>
        <button onClick={save} disabled={saving || !testResult?.ok}
                data-testid="db-save-btn"
                className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Enregistrer
        </button>
        <button onClick={restart} disabled={restarting}
                data-testid="db-restart-btn"
                className="flex items-center gap-2 px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10 disabled:opacity-40">
          {restarting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Redémarrer backend
        </button>
      </div>

      <div className="text-[11px] text-muted-foreground border-t border-border pt-3 flex items-start gap-1.5">
        <AlertTriangle size={12} className="mg-warning flex-shrink-0 mt-0.5" />
        <span>
          Pour une installation production, hébergez la base sur un <b>serveur ou disque dédié</b> (SSD recommandé).
          Testez toujours la connexion avant d&apos;enregistrer. Backup automatique dans <code className="mono">/app/backend/.env.bak</code>.
        </span>
      </div>
    </SectionCard>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 3a. Rétention vidéo (seuils + purge)
// ═══════════════════════════════════════════════════════════════════
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
      toast.success(`Purge : ${data.deleted_by_age} par âge + ${data.deleted_by_quota} par quota, ${data.freed_gb} Go libérés`);
      load();
    } catch (e) { toast.error("Purge échouée"); }
    finally { setPurging(false); }
  };

  const usedPct = state.disk.used_pct;
  const usedColor = usedPct > form.max_disk_pct ? "#FF3333" : usedPct > form.max_disk_pct - 10 ? "#FFB800" : "#00E676";

  return (
    <SectionCard id="video-retention" title="Rétention vidéo" subtitle="Politique automatique de conservation et purge." icon={Film}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        <StatBox label="Disque total" value={`${state.disk.total_gb} Go`} />
        <StatBox label="Utilisé" value={`${state.disk.used_gb} Go`} color={usedColor} />
        <StatBox label="Libre" value={`${state.disk.free_gb} Go`} color={state.disk.free_gb < form.min_free_gb ? "#FF3333" : undefined} />
        <StatBox label="Occupation" value={`${usedPct}%`} color={usedColor} />
      </div>
      <UsageBar pct={usedPct} threshold={form.max_disk_pct} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
        <StatBox label="Enregistrements" value={state.recordings.count} small />
        <StatBox label="Volume total" value={`${state.recordings.size_gb} Go`} small />
        <StatBox label="Plus ancien" value={state.recordings.oldest ? new Date(state.recordings.oldest).toLocaleDateString("fr-FR") : "—"} small />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
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
      <p className="text-[11px] text-muted-foreground mb-3 leading-relaxed">
        Les vidéos plus anciennes que <b>{form.retention_days} jours</b> sont supprimées automatiquement. Si l&apos;espace libre passe sous <b>{form.min_free_gb} Go</b> <i>ou</i> si l&apos;occupation dépasse <b>{form.max_disk_pct}%</b>, les <b>plus anciens segments</b> sont supprimés en priorité.
      </p>

      <div className="flex gap-2">
        <button onClick={save} disabled={saving} data-testid="retention-save" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm">
          {saving && <Loader2 size={14} className="animate-spin" />}<Save size={14} /> Enregistrer les seuils
        </button>
        <button onClick={purgeNow} disabled={purging} data-testid="retention-purge" className="flex items-center gap-2 px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">
          {purging ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />} Purger maintenant
        </button>
      </div>
    </SectionCard>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 3b. Pools vidéo (multi-disques)
// ═══════════════════════════════════════════════════════════════════
function VideoPoolsCard() {
  const { t } = useApp();
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
    <SectionCard
      id="video-pools"
      title={t("storage.videos")}
      subtitle={t("storage.videos_desc")}
      icon={HardDrive}
    >
      <div className="text-[11px] mono text-muted-foreground mb-3">
        Dossier principal : <span className="text-foreground">{state.primary_recordings_dir}</span>
      </div>

      <div className="border border-[#00E676]/40 bg-[#00E676]/5 p-3 mb-4 flex items-start gap-2" data-testid="video-hdd-tip">
        <Info size={14} className="text-[#00E676] flex-shrink-0 mt-0.5" />
        <div className="text-[11px] text-muted-foreground leading-relaxed">
          Les enregistrements sont surtout de <b className="text-foreground">gros volumes séquentiels</b> — un
          <b className="text-[#FFB800]"> HDD</b> convient très bien et coûte bien moins cher au Go qu&apos;un NVMe/SSD, qu&apos;il
          vaut mieux réserver à la base de données (voir plus haut).
        </div>
      </div>

      {/* Disques détectés — choix rapide */}
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Disques détectés ({state.partitions.length})</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
        {state.partitions.map((p, i) => {
          const isRecordingsDisk = state.recordings_disk?.device === p.device;
          const isAppDisk = state.app_disk?.device === p.device;
          // Ce mountpoint EST déjà le dossier principal d'enregistrement (ou
          // un pool existant pointe déjà dessus) — créer un pool identique
          // serait redondant, on masque le bouton plutôt que de le proposer.
          const alreadyUsed = p.mountpoint === state.primary_recordings_dir
            || state.pools.some((pool) => pool.path === p.mountpoint);
          return (
            <div key={i} className="border border-border p-2 text-xs" data-testid={`partition-${i}`}>
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="mono text-[#0044FF]">{p.mountpoint}</span>
                  <DiskTypeBadge type={p.type} />
                  {isRecordingsDisk && <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-border text-muted-foreground">Enregistrements</span>}
                  {isAppDisk && <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-border text-muted-foreground">Application</span>}
                </div>
                {alreadyUsed ? (
                  <span className="text-[10px] text-muted-foreground shrink-0">Déjà utilisé</span>
                ) : (
                  <button onClick={() => setNewPool({ ...newPool, path: p.mountpoint, name: newPool.name || p.mountpoint })}
                          className="text-[10px] px-2 py-0.5 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10 shrink-0"
                          data-testid={`use-partition-${i}`}>
                    Utiliser pour vidéo
                  </button>
                )}
              </div>
              <div className="mono text-[10px] text-muted-foreground">{p.device} ({p.fstype}) · {p.total_gb} Go · libre {p.free_gb} Go ({100 - Math.round(p.used_pct)}%)</div>
              <div className="h-1 bg-secondary mt-1"><div className="h-full" style={{ width: `${p.used_pct}%`, backgroundColor: p.used_pct > 85 ? "#FF3333" : p.used_pct > 70 ? "#FFB800" : "#00E676" }} /></div>
            </div>
          );
        })}
      </div>

      {/* Pools déclarés */}
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Pools déclarés ({state.pools.length})</div>
      {state.pools.length === 0 && <p className="text-xs text-muted-foreground mb-3">Aucun pool déclaré — les enregistrements vont dans le dossier principal.</p>}
      <div className="space-y-2 mb-3">
        {state.pools.map((pool) => (
          <div key={pool.id} className="border border-border p-3" data-testid={`pool-${pool.id}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{pool.name}</span>
                <span className="mono text-[10px] text-muted-foreground">{pool.path}</span>
                <DiskTypeBadge type={pool.disk_type} />
                {!pool.enabled && <span className="text-[10px] text-[#FFB800]">DÉSACTIVÉ</span>}
              </div>
              <div className="flex gap-1">
                <button onClick={() => updatePool(pool, { enabled: !pool.enabled })} className="text-[10px] px-2 py-0.5 border border-border hover:bg-secondary" data-testid={`pool-toggle-${pool.id}`}>{pool.enabled ? "Désactiver" : "Activer"}</button>
                <button onClick={() => delPool(pool.id)} className="text-[10px] px-2 py-0.5 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10" data-testid={`pool-del-${pool.id}`}><Trash2 size={10} /></button>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
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
    </SectionCard>
  );
}

