import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Trash2, UserCog, Loader2, Building2, ShieldCheck, ShieldOff, Pencil, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["admin", "technician", "client", "readonly", "guest"];
const ROLE_COLOR = { admin: "#FF3333", technician: "#0044FF", client: "#00E676", readonly: "#FFB800", guest: "#71717a" };
const PERMS = [
  ["view_live", "Visionnage (live)"],
  ["view_recordings", "Lecture des enregistrements"],
  ["read_plates", "Lecture des plaques (ANPR)"],
  ["stream_hd", "Affichage HD (sinon SD)"],
  ["ptz_control", "Contrôle PTZ"],
  ["export_files", "Export de fichiers"],
];

export default function UsersPage() {
  const { t, user: me } = useApp();
  const [users, setUsers] = useState([]);
  const [sites, setSites] = useState([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", name: "", role: "client" });
  const [siteUser, setSiteUser] = useState(null);
  const [selSites, setSelSites] = useState([]);
  const [permUser, setPermUser] = useState(null);
  const [selPerms, setSelPerms] = useState({});
  // Édition utilisateur (nom / email / mot de passe optionnel)
  const [editUser, setEditUser] = useState(null);
  const [editForm, setEditForm] = useState({ name: "", email: "", password: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [showEditPwd, setShowEditPwd] = useState(false);

  const load = () => api.get("/users").then((r) => setUsers(r.data)).catch(() => {});
  useEffect(() => { load(); api.get("/sites").then((r) => setSites(r.data)).catch(() => {}); }, []);

  const submit = async () => {
    if (!form.email || !form.password || !form.name) return toast.error("Tous les champs requis");
    setSaving(true);
    try { await api.post("/users", form); toast.success("Utilisateur créé"); setOpen(false); setForm({ email: "", password: "", name: "", role: "client" }); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };
  const changeRole = async (u, role) => { await api.put(`/users/${u.id}`, { role }); toast.success("Rôle modifié"); load(); };
  const toggleActive = async (u) => { await api.put(`/users/${u.id}`, { active: !u.active }); load(); };
  const del = async (u) => { if (!window.confirm(`Supprimer ${u.email} ?`)) return; try { await api.delete(`/users/${u.id}`); toast.success("Supprimé"); load(); } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } };
  const disableMfa = async (u) => {
    if (!window.confirm(`Désactiver la MFA de ${u.email} ?\n\nL'utilisateur pourra se reconnecter avec son seul mot de passe et devra refaire un enrollement MFA depuis son compte.`)) return;
    try {
      await api.delete(`/users/${u.id}/mfa`);
      toast.success(`MFA désactivée pour ${u.email}`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const openSites = (u) => { setSiteUser(u); setSelSites(u.site_ids || []); };
  const toggleSite = (id) => setSelSites((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  const saveSites = async () => { await api.put(`/users/${siteUser.id}`, { site_ids: selSites }); toast.success(t("users.sites")); setSiteUser(null); load(); };

  const openPerms = (u) => { setPermUser(u); setSelPerms({ ...(u.permissions || {}) }); };
  const togglePerm = (k) => setSelPerms((p) => ({ ...p, [k]: !p[k] }));
  const savePerms = async () => { await api.put(`/users/${permUser.id}`, { permissions: selPerms }); toast.success("Permissions mises à jour"); setPermUser(null); load(); };

  // ── Édition profil utilisateur ────────────────────────────────────
  const openEdit = (u) => {
    setEditUser(u);
    setEditForm({ name: u.name || "", email: u.email || "", password: "" });
    setShowEditPwd(false);
  };
  const saveEdit = async () => {
    if (!editForm.name.trim() || !editForm.email.trim()) return toast.error("Nom et email requis");
    // Construit le payload : ne pas envoyer les champs inchangés
    const payload = {};
    if (editForm.name.trim() !== editUser.name) payload.name = editForm.name.trim();
    if (editForm.email.trim().toLowerCase() !== editUser.email) payload.email = editForm.email.trim();
    if (editForm.password) {
      if (editForm.password.length < 8) return toast.error("Mot de passe : minimum 8 caractères");
      payload.password = editForm.password;
    }
    if (Object.keys(payload).length === 0) { setEditUser(null); return toast.info("Aucune modification"); }
    setEditSaving(true);
    try {
      await api.put(`/users/${editUser.id}`, payload);
      toast.success("Utilisateur modifié");
      setEditUser(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setEditSaving(false); }
  };

  const siteLabel = (u) => {
    if (u.role === "admin" || u.role === "technician") return t("users.sites_all");
    const ids = u.site_ids || [];
    if (!ids.length) return "—";
    return ids.map((id) => sites.find((s) => s.id === id)?.name || "?").join(", ");
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><UserCog size={22} /> {t("users.title")}</h1>
        <button onClick={() => setOpen(true)} data-testid="add-user-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("users.add")}</button>
      </div>

      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-2">{t("common.name")}</th><th className="px-3 py-2">{t("common.email")}</th><th className="px-3 py-2">{t("common.role")}</th><th className="px-3 py-2">{t("users.sites")}</th><th className="px-3 py-2">MFA</th><th className="px-3 py-2">{t("common.status")}</th><th className="px-3 py-2 text-right">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-border hover:bg-secondary/50" data-testid="user-row">
                <td className="px-3 py-2 font-medium">{u.name}</td>
                <td className="px-3 py-2 mono text-xs">{u.email}</td>
                <td className="px-3 py-2">
                  <select value={u.role} onChange={(e) => changeRole(u, e.target.value)} disabled={u.id === me.id} data-testid="user-role-select"
                    className="text-xs px-2 py-1 bg-card border border-input outline-none uppercase tracking-wider font-medium" style={{ color: ROLE_COLOR[u.role] }}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground max-w-[180px] truncate" title={siteLabel(u)}>{siteLabel(u)}</td>
                <td className="px-3 py-2">
                  {u.twofa_enabled ? (
                    <span className="inline-flex items-center gap-1 text-[10px] mono uppercase tracking-wider px-1.5 py-0.5 bg-[#00E676]/15 text-[#00E676] border border-[#00E676]/40" data-testid={`user-mfa-${u.id}`}>
                      <ShieldCheck size={10} /> Activée
                    </span>
                  ) : (
                    <span className="text-[10px] mono uppercase tracking-wider text-muted-foreground" data-testid={`user-mfa-${u.id}`}>—</span>
                  )}
                </td>
                <td className="px-3 py-2"><button onClick={() => toggleActive(u)} disabled={u.id === me.id} className={`text-xs px-2 py-0.5 border ${u.active ? "mg-online border-[#00E676]/40" : "mg-offline border-[#FF3333]/40"}`}>{u.active ? t("common.active") : "Inactif"}</button></td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => openEdit(u)} data-testid="edit-user-btn" title="Modifier" className="p-1.5 hover:bg-secondary text-[#00E5FF]"><Pencil size={15} /></button>
                    {u.role !== "admin" && <button onClick={() => openPerms(u)} data-testid="user-perms-btn" title="Permissions" className="p-1.5 hover:bg-secondary text-[#0044FF]"><ShieldCheck size={15} /></button>}
                    {!["admin", "technician"].includes(u.role) && <button onClick={() => openSites(u)} data-testid="user-sites-btn" title={t("users.sites")} className="p-1.5 hover:bg-secondary"><Building2 size={15} /></button>}
                    {u.twofa_enabled && u.id !== me.id && (
                      <button onClick={() => disableMfa(u)} data-testid={`user-disable-mfa-${u.id}`} title="Désactiver la MFA (perte du téléphone)" className="p-1.5 hover:bg-secondary text-[#FFB800]">
                        <ShieldOff size={15} />
                      </button>
                    )}
                    {u.id !== me.id && <button onClick={() => del(u)} data-testid="delete-user-btn" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none border-border">
          <DialogHeader><DialogTitle className="font-head">{t("users.add")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <input placeholder={t("common.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-form-name" className="w-full px-3 py-2 bg-card border border-input outline-none text-sm" />
            <input placeholder={t("common.email")} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="user-form-email" className="w-full px-3 py-2 bg-card border border-input outline-none text-sm" />
            <input placeholder={t("common.password")} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-form-password" className="w-full px-3 py-2 bg-card border border-input outline-none text-sm" />
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="user-form-role" className="w-full px-3 py-2 bg-card border border-input outline-none text-sm uppercase">{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 border border-border text-sm">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="user-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!siteUser} onOpenChange={(o) => !o && setSiteUser(null)}>
        <DialogContent className="rounded-none border-border">
          <DialogHeader><DialogTitle className="font-head">{t("users.sites")} — {siteUser?.name}</DialogTitle></DialogHeader>
          <div className="space-y-1 max-h-72 overflow-y-auto">
            {sites.map((s) => (
              <label key={s.id} className="flex items-center gap-2 px-2 py-2 border border-border hover:bg-secondary text-sm cursor-pointer" data-testid="site-checkbox">
                <input type="checkbox" checked={selSites.includes(s.id)} onChange={() => toggleSite(s.id)} />
                <span className="flex-1">{s.name}</span>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{s.type}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <button onClick={() => setSiteUser(null)} className="px-4 py-2 border border-border text-sm">{t("common.cancel")}</button>
            <button onClick={saveSites} data-testid="user-sites-save" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!permUser} onOpenChange={(o) => !o && setPermUser(null)}>
        <DialogContent className="rounded-none border-border" data-testid="user-perms-dialog">
          <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><ShieldCheck size={18} className="text-[#0044FF]" /> Permissions — {permUser?.name}</DialogTitle></DialogHeader>
          <p className="text-xs text-muted-foreground">Activez ou désactivez chaque accès pour cet utilisateur. Les administrateurs disposent de tous les accès.</p>
          <div className="space-y-1 max-h-80 overflow-y-auto mt-2">
            {PERMS.map(([key, label]) => (
              <label key={key} className="flex items-center gap-3 px-3 py-2.5 border border-border hover:bg-secondary text-sm cursor-pointer" data-testid={`perm-${key}`}>
                <input type="checkbox" checked={!!selPerms[key]} onChange={() => togglePerm(key)} data-testid={`perm-toggle-${key}`} />
                <span className="flex-1">{label}</span>
                <span className="text-[9px] uppercase tracking-wider mono text-muted-foreground">{key}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <button onClick={() => setPermUser(null)} className="px-4 py-2 border border-border text-sm">{t("common.cancel")}</button>
            <button onClick={savePerms} data-testid="user-perms-save" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog modification utilisateur (nom + email + mot de passe optionnel) */}
      <Dialog open={!!editUser} onOpenChange={(o) => !o && setEditUser(null)}>
        <DialogContent className="rounded-none border-border" data-testid="user-edit-dialog">
          <DialogHeader>
            <DialogTitle className="font-head flex items-center gap-2">
              <Pencil size={18} className="text-[#00E5FF]" /> Modifier — {editUser?.name}
            </DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground mb-2">
            Modifiez le nom, l&apos;email ou le mot de passe. Laissez le champ mot de passe vide pour le conserver.
          </p>
          <div className="space-y-3">
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Nom complet</label>
              <input value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                data-testid="user-edit-name"
                className="w-full px-3 py-2 bg-card border border-input outline-none focus:border-[#00E5FF] text-sm" />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Email</label>
              <input type="email" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                data-testid="user-edit-email"
                className="w-full px-3 py-2 bg-card border border-input outline-none focus:border-[#00E5FF] text-sm mono" />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                Nouveau mot de passe <span className="text-muted-foreground/60">(optionnel · min. 8 caractères)</span>
              </label>
              <div className="relative">
                <input type={showEditPwd ? "text" : "password"} value={editForm.password}
                  onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                  placeholder="Laisser vide pour ne pas changer"
                  data-testid="user-edit-password" autoComplete="new-password"
                  className="w-full px-3 py-2 pr-10 bg-card border border-input outline-none focus:border-[#00E5FF] text-sm" />
                <button type="button" onClick={() => setShowEditPwd((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground"
                  title={showEditPwd ? "Masquer" : "Afficher"} tabIndex={-1}>
                  {showEditPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>
            {editUser?.id === me?.id && (
              <div className="text-[11px] p-2 border border-[#FFB800]/40 bg-[#FFB800]/10 text-[#FFB800]">
                Vous modifiez votre propre compte. Si vous changez l&apos;email ou le mot de passe, vous devrez vous reconnecter.
              </div>
            )}
          </div>
          <DialogFooter>
            <button onClick={() => setEditUser(null)} className="px-4 py-2 border border-border text-sm">{t("common.cancel")}</button>
            <button onClick={saveEdit} disabled={editSaving} data-testid="user-edit-save"
              className="px-4 py-2 bg-[#00E5FF] text-black font-medium text-sm flex items-center gap-2 hover:bg-[#00d4eb] disabled:opacity-60">
              {editSaving && <Loader2 size={15} className="animate-spin" />}
              {t("common.save")}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
