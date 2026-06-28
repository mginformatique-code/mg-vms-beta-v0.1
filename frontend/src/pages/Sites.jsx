import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Building2, MapPin, Cctv, Trash2, Pencil, Loader2 } from "lucide-react";
import { toast } from "sonner";

const TYPES = ["Mairie", "Parking", "École", "Stade", "Zone industrielle", "Zone commerciale", "Entreprise", "Site sensible"];

export default function Sites() {
  const { t, can } = useApp();
  const [sites, setSites] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", type: "Mairie", address: "", lat: 45.764, lng: 4.8357 });

  const load = () => api.get("/sites").then((r) => setSites(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing(null); setForm({ name: "", type: "Mairie", address: "", lat: 45.764, lng: 4.8357 }); setOpen(true); };
  const openEdit = (s) => { setEditing(s); setForm({ name: s.name, type: s.type, address: s.address, lat: s.lat, lng: s.lng }); setOpen(true); };

  const submit = async () => {
    if (!form.name) return toast.error("Nom requis");
    setSaving(true);
    try {
      if (editing) await api.put(`/sites/${editing.id}`, { ...form, lat: parseFloat(form.lat), lng: parseFloat(form.lng) });
      else await api.post("/sites", { ...form, lat: parseFloat(form.lat), lng: parseFloat(form.lng) });
      toast.success(editing ? "Site modifié" : "Site ajouté"); setOpen(false); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };
  const del = async (s) => { if (!window.confirm(`Supprimer ${s.name} et ses caméras ?`)) return; await api.delete(`/sites/${s.id}`); toast.success("Supprimé"); load(); };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("sites.title")}</h1>
        {can("technician") && <button onClick={openNew} data-testid="add-site-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("sites.add")}</button>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {sites.map((s) => (
          <div key={s.id} className="bg-card border border-border p-4 hover:border-[#0044FF] transition-colors group" data-testid="site-card">
            <div className="flex items-start justify-between mb-3">
              <div className="w-9 h-9 bg-secondary flex items-center justify-center"><Building2 size={18} className="text-[#0044FF]" /></div>
              {can("technician") && (
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => openEdit(s)} className="p-1 hover:bg-secondary"><Pencil size={14} /></button>
                  {can("admin") && <button onClick={() => del(s)} className="p-1 hover:bg-secondary text-[#FF3333]"><Trash2 size={14} /></button>}
                </div>
              )}
            </div>
            <div className="font-head font-bold text-lg tracking-tight">{s.name}</div>
            <div className="text-[10px] uppercase tracking-wider text-[#0044FF] mb-2">{s.type}</div>
            <div className="text-xs text-muted-foreground flex items-center gap-1 mb-3"><MapPin size={12} /> {s.address}</div>
            <div className="flex items-center gap-1 text-sm pt-2 border-t border-border"><Cctv size={14} className="text-muted-foreground" /> <span className="mono font-medium">{s.camera_count}</span> <span className="text-muted-foreground text-xs">{t("sites.cameras")}</span></div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none border-border">
          <DialogHeader><DialogTitle className="font-head">{editing ? t("common.edit") : t("sites.add")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <F label={t("common.name")}><input data-testid="site-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp2" /></F>
            <F label={t("common.type")}><select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="inp2">{TYPES.map((x) => <option key={x}>{x}</option>)}</select></F>
            <F label={t("common.address")}><input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="inp2" /></F>
            <div className="grid grid-cols-2 gap-3">
              <F label="Latitude"><input value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} className="inp2 mono" /></F>
              <F label="Longitude"><input value={form.lng} onChange={(e) => setForm({ ...form, lng: e.target.value })} className="inp2 mono" /></F>
            </div>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="site-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <style>{`.inp2{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp2:focus{border-color:#0044FF}`}</style>
    </div>
  );
}
function F({ label, children }) { return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>; }
