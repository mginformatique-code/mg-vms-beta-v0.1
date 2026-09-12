/**
 * ReportSettings.jsx — v3.57 · Réglages du rapport PDF (Carte interactive)
 *
 * Deux réglages consommés par frontend/src/lib/mapReportPdf.js :
 *   1. Identité société + textes de couverture/pied de page
 *      (GET/PUT /api/site-manager/report-template)
 *   2. Bibliothèque de caméras — UNE photo + UN nombre d'objectifs par
 *      (fabricant, modèle), réutilisés pour toutes les caméras de ce
 *      modèle sur n'importe quel plan (GET/PUT/DELETE
 *      /api/site-manager/camera-catalog) — à ne pas confondre avec les
 *      photos d'installation (map_position.photos[]), différentes par
 *      caméra installée.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { toast } from "sonner";
import { FileText, Image as ImageIcon, Check, Plus, Trash2, Pencil, X, Camera as CamIcon } from "lucide-react";
import { useApp } from "@/context/AppContext";

const Field = ({ label, hint, children }) => (
  <label className="block">
    <span className="block text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">{label}</span>
    {children}
    {hint && <span className="block text-[10px] text-muted-foreground/70 mt-1">{hint}</span>}
  </label>
);

const Input = (p) => (
  <input className="w-full bg-secondary/30 border border-border px-3 py-2 text-sm focus:outline-none focus:border-[#0044FF] transition" {...p} />
);

const Textarea = (p) => (
  <textarea className="w-full bg-secondary/30 border border-border px-3 py-2 text-sm focus:outline-none focus:border-[#0044FF] transition" rows={2} {...p} />
);

const Btn = ({ variant = "primary", children, className = "", ...p }) => {
  const base = "inline-flex items-center gap-2 px-3 py-2 text-xs font-medium tracking-wide border transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-[#0044FF] hover:bg-[#0033CC] text-white border-[#0044FF]",
    ghost: "bg-transparent border-border hover:bg-secondary/50 text-foreground",
    danger: "bg-transparent border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10",
  };
  return <button className={`${base} ${styles[variant] || styles.primary} ${className}`} {...p}>{children}</button>;
};

function fileToDataUri(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

function IdentitySection() {
  const { t } = useApp();
  const [tpl, setTpl] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = () => api.get("/site-manager/report-template").then((r) => setTpl(r.data)).catch(() => setTpl({}));
  useEffect(() => { load(); }, []);

  const set = (k, v) => setTpl((prev) => ({ ...prev, [k]: v }));

  const onLogo = async (file) => {
    if (!file) return;
    if (file.size > 3_500_000) { toast.error(t("repset.err_logo_too_large")); return; }
    set("logo_data_uri", await fileToDataUri(file));
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/site-manager/report-template", tpl);
      toast.success(t("repset.saved_toast"));
    } catch (e) {
      toast.error(e.response?.data?.detail || t("repset.err_save_generic"));
    } finally {
      setSaving(false);
    }
  };

  if (!tpl) return null;

  return (
    <div className="bg-card border border-border p-4 space-y-4" data-testid="report-identity-section">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <FileText size={14} className="text-[#0044FF]" />
        <h2 className="font-head font-black text-sm tracking-tight">{t("repset.identity_title")}</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-3">
          <Field label={t("repset.company_name_label")}>
            <Input value={tpl.company_name || ""} onChange={(e) => set("company_name", e.target.value)} placeholder="MG Informatique" data-testid="report-company-name" />
          </Field>
          <Field label={t("repset.address_label")}>
            <Textarea value={tpl.company_address || ""} onChange={(e) => set("company_address", e.target.value)} placeholder="16 bis rue Fanny Duvivier, 60870 Rieux" data-testid="report-company-address" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("repset.phone_label")}>
              <Input value={tpl.company_phone || ""} onChange={(e) => set("company_phone", e.target.value)} data-testid="report-company-phone" />
            </Field>
            <Field label={t("repset.email_label")}>
              <Input value={tpl.company_email || ""} onChange={(e) => set("company_email", e.target.value)} data-testid="report-company-email" />
            </Field>
          </div>
          <Field label={t("repset.website_label")}>
            <Input value={tpl.company_website || ""} onChange={(e) => set("company_website", e.target.value)} placeholder="mginformatique.com" data-testid="report-company-website" />
          </Field>
          <Field label={t("repset.logo_label")} hint={t("repset.logo_hint")}>
            <div className="flex items-center gap-3">
              {tpl.logo_data_uri
                ? <img src={tpl.logo_data_uri} alt="Logo" className="w-16 h-16 object-contain bg-secondary/30 border border-border" />
                : <div className="w-16 h-16 flex items-center justify-center bg-secondary/30 border border-border text-muted-foreground"><ImageIcon size={18} /></div>}
              <input type="file" accept="image/*" onChange={(e) => onLogo(e.target.files?.[0])} data-testid="report-logo-upload" />
            </div>
          </Field>
        </div>

        <div className="space-y-3">
          <Field label={t("repset.cover_title_label")}>
            <Input value={tpl.cover_title || ""} onChange={(e) => set("cover_title", e.target.value)} placeholder={t("repset.cover_title_placeholder")} data-testid="report-cover-title" />
          </Field>
          <Field label={t("repset.cover_subtitle_label")}>
            <Input value={tpl.cover_subtitle || ""} onChange={(e) => set("cover_subtitle", e.target.value)} placeholder={t("repset.cover_subtitle_placeholder")} data-testid="report-cover-subtitle" />
          </Field>
          <Field label={t("repset.footer_text_label")} hint={t("repset.footer_text_hint")}>
            <Input value={tpl.footer_text || ""} onChange={(e) => set("footer_text", e.target.value)} placeholder="MG Informatique — Confidentiel" data-testid="report-footer-text" />
          </Field>
        </div>
      </div>

      <div className="pt-2 border-t border-border flex justify-end">
        <Btn onClick={save} disabled={saving} data-testid="report-identity-save">
          {saving ? t("repset.saving") : (<><Check size={13} /> {t("repset.save")}</>)}
        </Btn>
      </div>
    </div>
  );
}

function CatalogForm({ initial, onSaved, onCancel }) {
  const { t } = useApp();
  const [manufacturer, setManufacturer] = useState(initial?.manufacturer || "");
  const [model, setModel] = useState(initial?.model || "");
  const [lensCount, setLensCount] = useState(initial?.lens_count ?? 1);
  const [photo, setPhoto] = useState(initial?.photo_data_uri || null);
  const [saving, setSaving] = useState(false);

  const onPhoto = async (file) => {
    if (!file) return;
    if (file.size > 3_500_000) { toast.error(t("repset.err_photo_too_large")); return; }
    setPhoto(await fileToDataUri(file));
  };

  const save = async () => {
    if (!manufacturer.trim() || !model.trim()) { toast.error(t("repset.err_manufacturer_model_required")); return; }
    setSaving(true);
    try {
      await api.put("/site-manager/camera-catalog", {
        manufacturer: manufacturer.trim(), model: model.trim(),
        lens_count: Number(lensCount) || 1, photo_data_uri: photo,
      });
      toast.success(t("repset.entry_saved_toast"));
      onSaved();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("repset.err_save_generic"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-secondary/20 border border-border p-3 grid grid-cols-1 md:grid-cols-5 gap-3 items-end" data-testid="report-catalog-form">
      <Field label={t("repset.manufacturer_label")}>
        <Input value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} placeholder="Dahua" data-testid="report-catalog-manufacturer" />
      </Field>
      <Field label={t("repset.model_label")}>
        <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="DHI-ITC413-PW4D-IZ1" data-testid="report-catalog-model" />
      </Field>
      <Field label={t("repset.lens_count_label")}>
        <Input type="number" min={1} max={16} value={lensCount} onChange={(e) => setLensCount(e.target.value)} data-testid="report-catalog-lens-count" />
      </Field>
      <Field label={t("repset.product_photo_label")}>
        <div className="flex items-center gap-2">
          {photo && <img src={photo} alt="" className="w-10 h-10 object-contain bg-card border border-border" />}
          <input type="file" accept="image/*" onChange={(e) => onPhoto(e.target.files?.[0])} data-testid="report-catalog-photo-upload" />
        </div>
      </Field>
      <div className="flex gap-2">
        <Btn onClick={save} disabled={saving} data-testid="report-catalog-save">{saving ? "…" : <Check size={13} />}</Btn>
        <Btn variant="ghost" onClick={onCancel} data-testid="report-catalog-cancel"><X size={13} /></Btn>
      </div>
    </div>
  );
}

function CatalogSection() {
  const { t } = useApp();
  const [entries, setEntries] = useState([]);
  const [editing, setEditing] = useState(null); // null | {} | entry
  const [loading, setLoading] = useState(true);

  const load = () => api.get("/site-manager/camera-catalog").then((r) => setEntries(r.data)).catch(() => {}).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const remove = async (id) => {
    if (!window.confirm(t("repset.confirm_delete_entry"))) return;
    try {
      await api.delete(`/site-manager/camera-catalog/${id}`);
      load();
    } catch {
      toast.error(t("repset.err_delete_failed"));
    }
  };

  return (
    <div className="bg-card border border-border p-4 space-y-3" data-testid="report-catalog-section">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <div className="flex items-center gap-2">
          <CamIcon size={14} className="text-[#0044FF]" />
          <h2 className="font-head font-black text-sm tracking-tight">{t("repset.catalog_title")}</h2>
        </div>
        {!editing && (
          <Btn onClick={() => setEditing({})} data-testid="report-catalog-add">
            <Plus size={13} /> {t("repset.add_model_btn")}
          </Btn>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t("repset.catalog_description")}
      </p>

      {editing && (
        <CatalogForm
          initial={editing.id ? editing : null}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}

      {loading ? (
        <div className="text-xs text-muted-foreground">{t("repset.loading")}</div>
      ) : entries.length === 0 ? (
        <div className="text-xs text-muted-foreground">{t("repset.no_entries")}</div>
      ) : (
        <div className="divide-y divide-border">
          {entries.map((e) => (
            <div key={e.id} className="flex items-center gap-3 py-2" data-testid={`report-catalog-row-${e.id}`}>
              {e.photo_data_uri
                ? <img src={e.photo_data_uri} alt="" className="w-12 h-12 object-contain bg-secondary/30 border border-border shrink-0" />
                : <div className="w-12 h-12 flex items-center justify-center bg-secondary/30 border border-border text-muted-foreground shrink-0"><ImageIcon size={14} /></div>}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{e.manufacturer} — {e.model}</div>
                <div className="text-xs text-muted-foreground">{e.lens_count} {e.lens_count > 1 ? t("repset.lens_plural") : t("repset.lens_singular")}</div>
              </div>
              <Btn variant="ghost" onClick={() => setEditing(e)} data-testid={`report-catalog-edit-${e.id}`}><Pencil size={12} /></Btn>
              <Btn variant="danger" onClick={() => remove(e.id)} data-testid={`report-catalog-delete-${e.id}`}><Trash2 size={12} /></Btn>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ReportSettings() {
  const { t } = useApp();
  return (
    <div className="p-4 space-y-4 max-w-5xl mx-auto" data-testid="report-settings">
      <div className="border-b border-border pb-3">
        <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">{t("repset.breadcrumb")}</div>
        <h1 className="font-head font-black text-2xl tracking-tight">{t("repset.page_title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("repset.intro_prefix")} <Link to="/map" className="text-[#0044FF] hover:underline">{t("repset.map_link_label")}</Link>.
        </p>
      </div>
      <IdentitySection />
      <CatalogSection />
    </div>
  );
}
