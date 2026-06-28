import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Wifi, WifiOff, Camera as CamIcon, Trash2, Activity, Loader2, X } from "lucide-react";
import { toast } from "sonner";

const PROTOCOLS = ["RTSP", "ONVIF", "HTTP", "HTTPS"];
const CODECS = ["H264", "H265", "MJPEG"];

export default function Cameras() {
  const { t, can } = useApp();
  const [cams, setCams] = useState([]);
  const [sites, setSites] = useState([]);
  const [filterSite, setFilterSite] = useState("");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(null);
  const [snap, setSnap] = useState(null);
  const [form, setForm] = useState({ name: "", site_id: "", ip: "", protocol: "RTSP", codec: "H264", model: "", rtsp_url: "", username: "", password: "", ptz_enabled: false });

  const load = () => {
    const q = filterSite ? `?site_id=${filterSite}` : "";
    api.get(`/cameras${q}`).then((r) => setCams(r.data)).catch(() => {});
  };
  useEffect(() => { api.get("/sites").then((r) => setSites(r.data)); }, []);
  useEffect(load, [filterSite]);

  const submit = async () => {
    if (!form.name || !form.site_id) return toast.error("Nom et site requis");
    setSaving(true);
    try {
      await api.post("/cameras", form);
      toast.success("Caméra ajoutée"); setOpen(false); load();
      setForm({ name: "", site_id: "", ip: "", protocol: "RTSP", codec: "H264", model: "", rtsp_url: "", username: "", password: "", ptz_enabled: false });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const test = async (c) => {
    setTesting(c.id);
    try { const { data } = await api.post(`/cameras/${c.id}/test`); data.success ? toast.success(`${c.name}: ${data.message} (${data.resolution} @ ${data.fps}fps)`) : toast.error(`${c.name}: ${data.message}`); load(); }
    catch (e) { toast.error("Échec du test"); } finally { setTesting(null); }
  };
  const snapshot = async (c) => { try { const { data } = await api.post(`/cameras/${c.id}/snapshot`); setSnap({ ...data, name: c.name }); } catch (e) { toast.error("Échec"); } };
  const del = async (c) => { if (!window.confirm(`Supprimer ${c.name} ?`)) return; await api.delete(`/cameras/${c.id}`); toast.success("Supprimée"); load(); };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("cam.title")}</h1>
        <div className="flex items-center gap-2">
          <select value={filterSite} onChange={(e) => setFilterSite(e.target.value)} data-testid="camera-site-filter" className="px-3 py-2 bg-card border border-input text-sm outline-none">
            <option value="">{t("common.all")} — {t("nav.sites")}</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {can("technician") && (
            <button onClick={() => setOpen(true)} data-testid="add-camera-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("cam.add")}</button>
          )}
        </div>
      </div>

      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-2">{t("common.status")}</th><th className="px-3 py-2">{t("common.name")}</th><th className="px-3 py-2">{t("common.site")}</th>
            <th className="px-3 py-2">{t("cam.ip")}</th><th className="px-3 py-2">{t("cam.protocol")}</th><th className="px-3 py-2">{t("cam.codec")}</th>
            <th className="px-3 py-2">{t("cam.ptz")}</th><th className="px-3 py-2 text-right">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {cams.map((c) => (
              <tr key={c.id} className="border-b border-border hover:bg-secondary/50" data-testid="camera-row">
                <td className="px-3 py-2">
                  <span className={`inline-flex items-center gap-1.5 text-xs ${c.status === "online" ? "mg-online" : "mg-offline"}`}>
                    {c.status === "online" ? <Wifi size={13} /> : <WifiOff size={13} />}{t(c.status === "online" ? "common.online" : "common.offline")}
                  </span>
                </td>
                <td className="px-3 py-2 font-medium">{c.name}</td>
                <td className="px-3 py-2 text-muted-foreground">{c.site_name}</td>
                <td className="px-3 py-2 mono text-xs">{c.ip}</td>
                <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 border border-border">{c.protocol}</span></td>
                <td className="px-3 py-2 mono text-xs">{c.codec}</td>
                <td className="px-3 py-2 text-xs">{c.ptz_enabled ? "✓" : "—"}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => test(c)} data-testid="test-camera-btn" title={t("common.test")} className="p-1.5 hover:bg-secondary">{testing === c.id ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}</button>
                    <button onClick={() => snapshot(c)} data-testid="snapshot-btn" title={t("common.snapshot")} className="p-1.5 hover:bg-secondary"><CamIcon size={15} /></button>
                    {can("technician") && <button onClick={() => del(c)} data-testid="delete-camera-btn" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none border-border max-w-lg">
          <DialogHeader><DialogTitle className="font-head">{t("cam.add")}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("common.name")}><input data-testid="cam-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label={t("common.site")}>
              <select data-testid="cam-form-site" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} className="inp">
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label={t("cam.ip")}><input data-testid="cam-form-ip" value={form.ip} onChange={(e) => setForm({ ...form, ip: e.target.value })} className="inp" placeholder="192.168.1.10" /></Field>
            <Field label={t("cam.model")}><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="inp" /></Field>
            <Field label={t("cam.protocol")}><select value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })} className="inp">{PROTOCOLS.map((p) => <option key={p}>{p}</option>)}</select></Field>
            <Field label={t("cam.codec")}><select value={form.codec} onChange={(e) => setForm({ ...form, codec: e.target.value })} className="inp">{CODECS.map((p) => <option key={p}>{p}</option>)}</select></Field>
            <div className="col-span-2"><Field label="RTSP URL"><input value={form.rtsp_url} onChange={(e) => setForm({ ...form, rtsp_url: e.target.value })} className="inp mono text-xs" placeholder="rtsp://..." /></Field></div>
            <Field label="Login"><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="inp" /></Field>
            <Field label={t("common.password")}><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" /></Field>
            <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={form.ptz_enabled} onChange={(e) => setForm({ ...form, ptz_enabled: e.target.checked })} /> {t("cam.ptz")}</label>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="cam-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {snap && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6" onClick={() => setSnap(null)}>
          <div className="bg-card border border-border max-w-2xl w-full" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-border"><span className="text-sm mono">{snap.name} — {t("common.snapshot")}</span><button onClick={() => setSnap(null)}><X size={18} /></button></div>
            <img src={snap.snapshot_url} alt="" className="w-full" />
            <div className="px-3 py-2 text-[10px] mono text-muted-foreground">{new Date(snap.captured_at).toLocaleString()}</div>
          </div>
        </div>
      )}
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>;
}
