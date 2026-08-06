/**
 * RbacCenter.jsx — v0.5.5.d (Phase D)
 *
 * Matrice interactive RBAC (Role-Based Access Control).
 *
 * Colonnes = rôles (admin, technician, client, readonly, guest)
 * Lignes = permissions groupées (Vidéo, Gestion, Sécurité)
 *
 * L'admin peut cocher/décocher chaque case (sauf colonne admin qui est
 * toujours grisée à `true`). Le save applique uniquement les changements
 * du rôle édité (bouton par colonne). Un bouton « Réinitialiser » ramène
 * la colonne aux valeurs par défaut du code.
 */
import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  ShieldCheck, Save, RotateCcw, Loader2, Info, Users, Eye, Cog, ShieldAlert,
} from "lucide-react";

const GROUP_ICON = { video: Eye, manage: Cog, security: ShieldAlert };
const ROLE_COLOR = { admin: "#FF3333", technician: "#0044FF", client: "#00E676", readonly: "#FFB800", guest: "#71717a" };

export default function RbacCenter() {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});    // {role: {perm: bool}}
  const [saving, setSaving] = useState({});  // {role: bool}
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/security/rbac");
      setData(r.data);
      // Init draft = effective (ce qui est vraiment appliqué).
      setDraft(JSON.parse(JSON.stringify(r.data.effective)));
    } catch (e) { toast.error("Impossible de charger la matrice RBAC"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggle = (role, perm) => {
    if (role === "admin") return;
    setDraft((prev) => ({
      ...prev,
      [role]: { ...prev[role], [perm]: !prev[role][perm] },
    }));
  };

  const isDirty = (role) => {
    if (role === "admin" || !data) return false;
    const eff = data.effective[role];
    const d = draft[role] || {};
    return data.permissions.some((p) => Boolean(eff[p]) !== Boolean(d[p]));
  };

  const save = async (role) => {
    setSaving((s) => ({ ...s, [role]: true }));
    try {
      const r = await api.put("/security/rbac", { role, permissions: draft[role] });
      setData(r.data);
      setDraft(JSON.parse(JSON.stringify(r.data.effective)));
      toast.success(`Permissions du rôle ${role} enregistrées`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving((s) => ({ ...s, [role]: false })); }
  };

  const resetRole = async (role) => {
    if (!window.confirm(`Réinitialiser le rôle ${role} à ses valeurs par défaut ?`)) return;
    setSaving((s) => ({ ...s, [role]: true }));
    try {
      const r = await api.delete(`/security/rbac/${role}`);
      setData(r.data);
      setDraft(JSON.parse(JSON.stringify(r.data.effective)));
      toast.success(`Rôle ${role} réinitialisé`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving((s) => ({ ...s, [role]: false })); }
  };

  if (loading || !data) return (
    <div className="p-6 flex items-center gap-2 text-muted-foreground">
      <Loader2 size={16} className="animate-spin" /> Chargement de la matrice RBAC...
    </div>
  );

  const permsByGroup = data.permission_groups.map((g) => ({
    ...g,
    perms: data.permissions.filter((p) => data.permission_meta[p]?.group === g.id),
  }));

  return (
    <div className="p-6 max-w-6xl mx-auto" data-testid="rbac-center-page">
      <div className="flex items-center gap-3 mb-6">
        <ShieldCheck size={26} className="text-[#0044FF]" />
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight">Rôles & Permissions</h1>
          <p className="text-xs text-muted-foreground">
            Contrôle d&apos;accès basé sur les rôles (RBAC) — les valeurs
            s&apos;appliquent à tous les utilisateurs du rôle, sauf overrides individuels.
          </p>
        </div>
      </div>

      <div className="border border-border p-3 bg-card flex items-start gap-2 mb-4">
        <Info size={14} className="text-[#0044FF] mt-0.5 shrink-0" />
        <p className="text-xs text-muted-foreground leading-relaxed">
          Le rôle <b>admin</b> conserve toujours toutes les permissions et ne peut
          pas être modifié. Les permissions individuelles (page Utilisateurs)
          <b> surchargent</b> les valeurs de rôle. Pensez à cliquer sur
          <b> Enregistrer</b> pour chaque colonne modifiée.
        </p>
      </div>

      {/* Matrice */}
      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm" data-testid="rbac-matrix">
          <thead>
            <tr className="border-b border-border bg-muted">
              <th className="px-3 py-2 text-left text-[10px] uppercase tracking-widest text-muted-foreground min-w-[280px]">
                Permission
              </th>
              {data.roles.map((r) => (
                <th key={r} className="px-3 py-2 text-center text-[10px] uppercase tracking-widest">
                  <div className="flex flex-col items-center gap-1">
                    <span style={{ color: ROLE_COLOR[r] }} className="font-bold">{r}</span>
                    <Users size={11} className="text-muted-foreground" />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {permsByGroup.map((g) => (
              <React.Fragment key={g.id}>
                <tr className="bg-secondary/40">
                  <td colSpan={data.roles.length + 1} className="px-3 py-1.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold flex items-center gap-2">
                    {(() => { const Ic = GROUP_ICON[g.id] || Info; return <Ic size={12} />; })()}
                    {g.label}
                  </td>
                </tr>
                {g.perms.map((p) => (
                  <tr key={p} className="border-b border-border/40 hover:bg-secondary/20">
                    <td className="px-3 py-2">
                      <div className="text-sm">{data.permission_meta[p]?.label || p}</div>
                      <div className="text-[10px] mono text-muted-foreground">{p}</div>
                    </td>
                    {data.roles.map((r) => {
                      const val = Boolean(draft[r]?.[p]);
                      const changed = Boolean(data.effective[r][p]) !== val;
                      const isAdmin = r === "admin";
                      return (
                        <td key={r} className="px-3 py-2 text-center">
                          <label className={`inline-flex items-center justify-center ${isAdmin ? "opacity-50" : "cursor-pointer"}`}>
                            <input
                              type="checkbox"
                              checked={isAdmin ? true : val}
                              onChange={() => toggle(r, p)}
                              disabled={isAdmin}
                              data-testid={`rbac-${r}-${p}`}
                              className={`w-4 h-4 accent-[#0044FF] ${changed ? "ring-2 ring-[#FFB800] ring-offset-1" : ""}`}
                            />
                          </label>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-border bg-muted">
              <td className="px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground">Actions</td>
              {data.roles.map((r) => {
                const dirty = isDirty(r);
                const busy = saving[r];
                const hasOverride = !!data.overrides[r] && Object.keys(data.overrides[r]).length > 0;
                if (r === "admin") {
                  return <td key={r} className="px-3 py-2 text-center text-[10px] text-muted-foreground">immuable</td>;
                }
                return (
                  <td key={r} className="px-3 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <button onClick={() => save(r)} disabled={!dirty || busy}
                        className={`px-2 py-1 text-[10px] flex items-center gap-1 border ${dirty ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] hover:bg-[#0044FF]/20" : "border-border text-muted-foreground opacity-60"}`}
                        data-testid={`rbac-save-${r}`}>
                        {busy ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
                        Enregistrer
                      </button>
                      {hasOverride && (
                        <button onClick={() => resetRole(r)} disabled={busy}
                          className="text-[10px] text-muted-foreground hover:text-[#FF3333] flex items-center gap-1"
                          data-testid={`rbac-reset-${r}`}>
                          <RotateCcw size={9} /> Reset
                        </button>
                      )}
                    </div>
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="mt-3 text-[10px] text-muted-foreground flex items-center gap-4 flex-wrap">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 border-2 border-[#FFB800] inline-block" /> Modifié (non enregistré)
        </span>
        <span>·</span>
        <span>Les changements sont enregistrés par rôle (colonne).</span>
      </div>
    </div>
  );
}
