import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Wifi, WifiOff, Camera as CamIcon, Trash2, Activity, Loader2, X, Radar } from "lucide-react";
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
  const [discOpen, setDiscOpen] = useState(false);
  const [form, setForm] = useState({ name: "", site_id: "", ip: "", protocol: "RTSP", codec: "H264", model: "", rtsp_url: "", username: "", password: "", ptz_enabled: false, record_enabled: true, detect_enabled: false });

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
      setForm({ name: "", site_id: "", ip: "", protocol: "RTSP", codec: "H264", model: "", rtsp_url: "", username: "", password: "", ptz_enabled: false, record_enabled: true, detect_enabled: false });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const test = async (c) => {
    setTesting(c.id);
    try {
      const { data } = await api.post(`/cameras/${c.id}/test`);
      const extra = data.resolution ? ` (${data.resolution}${data.fps ? ` @ ${data.fps}fps` : ""}${data.codec ? ` ${data.codec}` : ""})` : "";
      data.success ? toast.success(`${c.name}: ${data.message}${extra}`) : toast.error(`${c.name}: ${data.message}`);
      load();
    }
    catch (e) { toast.error("Échec du test"); } finally { setTesting(null); }
  };
  const snapshot = async (c) => {
    try {
      const { data } = await api.post(`/cameras/${c.id}/snapshot`);
      const token = localStorage.getItem("mg_token");
      const url = `${process.env.REACT_APP_BACKEND_URL}/api${data.snapshot_url}?token=${encodeURIComponent(token || "")}&t=${Date.now()}`;
      setSnap({ ...data, snapshot_url: url, name: c.name });
    } catch (e) { toast.error("Échec — flux injoignable"); }
  };
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
            <button onClick={() => setDiscOpen(true)} data-testid="onvif-discover-btn" className="flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary"><Radar size={16} /> ONVIF</button>
          )}
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
            <div className="col-span-2 flex items-center gap-5">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.ptz_enabled} onChange={(e) => setForm({ ...form, ptz_enabled: e.target.checked })} /> {t("cam.ptz")}</label>
              <label className="flex items-center gap-2 text-sm" data-testid="record-toggle"><input type="checkbox" checked={form.record_enabled} onChange={(e) => setForm({ ...form, record_enabled: e.target.checked })} /> Enregistrement continu</label>
              <label className="flex items-center gap-2 text-sm" data-testid="detect-toggle"><input type="checkbox" checked={form.detect_enabled} onChange={(e) => setForm({ ...form, detect_enabled: e.target.checked })} /> Détection IA (YOLO + LAPI)</label>
            </div>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="cam-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {snap && (
        <Dialog open={!!snap} onOpenChange={(o) => !o && setSnap(null)}>
          <DialogContent className="rounded-none border-border max-w-2xl p-0">
            <DialogHeader className="px-3 py-2 border-b border-border"><DialogTitle className="text-sm mono">{snap.name} — {t("common.snapshot")}</DialogTitle></DialogHeader>
            <img src={snap.snapshot_url} alt="snapshot" className="w-full" data-testid="snapshot-image" />
            <div className="px-3 py-2 text-[10px] mono text-muted-foreground">{new Date(snap.captured_at).toLocaleString()}</div>
          </DialogContent>
        </Dialog>
      )}

      <OnvifDiscovery open={discOpen} onClose={() => setDiscOpen(false)}
        onPrefill={(vals) => { setForm((f) => ({ ...f, ...vals })); setDiscOpen(false); setOpen(true); }} />
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>;
}

function OnvifDiscovery({ open, onClose, onPrefill }) {
  const [scanning, setScanning] = useState(false);
  const [devices, setDevices] = useState(null);
  const [probing, setProbing] = useState(null);
  const [creds, setCreds] = useState({ username: "", password: "" });
  const [probeResult, setProbeResult] = useState(null);

  const scan = async () => {
    setScanning(true); setDevices(null); setProbeResult(null);
    try { const { data } = await api.post("/cameras/discover"); setDevices(data.devices); }
    catch (e) { toast.error("Échec de la découverte ONVIF"); }
    finally { setScanning(false); }
  };

  const probe = async (d) => {
    setProbing(d.ip); setProbeResult(null);
    try {
      const { data } = await api.post("/cameras/onvif-probe", { ip: d.ip, port: d.port, ...creds });
      setProbeResult({ ...data, ip: d.ip });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setProbing(null); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none border-border max-w-2xl">
        <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><Radar size={18} /> Découverte ONVIF (réseau local)</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <button onClick={scan} disabled={scanning} data-testid="onvif-scan-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">
              {scanning && <Loader2 size={15} className="animate-spin" />}{scanning ? "Scan en cours (multicast)..." : "Lancer le scan"}
            </button>
            <input placeholder="Login ONVIF" value={creds.username} onChange={(e) => setCreds({ ...creds, username: e.target.value })} className="inp" style={{ maxWidth: 140 }} />
            <input placeholder="Mot de passe" type="password" value={creds.password} onChange={(e) => setCreds({ ...creds, password: e.target.value })} className="inp" style={{ maxWidth: 140 }} />
          </div>
          {devices !== null && (
            <div className="border border-border">
              {devices.length === 0 && <p className="p-3 text-sm text-muted-foreground" data-testid="onvif-no-devices">Aucun appareil ONVIF détecté sur ce réseau. (Les caméras doivent être sur le même LAN que le serveur.)</p>}
              {devices.map((d) => (
                <div key={d.xaddr} className="flex items-center justify-between px-3 py-2 border-b border-border last:border-0" data-testid="onvif-device-row">
                  <div>
                    <span className="mono text-sm">{d.ip}:{d.port}</span>
                    {d.already_added && <span className="ml-2 text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">déjà ajoutée</span>}
                  </div>
                  <button onClick={() => probe(d)} disabled={probing === d.ip} className="px-3 py-1 border border-border text-xs hover:bg-secondary flex items-center gap-1">
                    {probing === d.ip && <Loader2 size={12} className="animate-spin" />}Interroger
                  </button>
                </div>
              ))}
            </div>
          )}
          {probeResult && (
            <div className="border border-border p-3 space-y-2" data-testid="onvif-probe-result">
              <p className="text-sm font-medium">{probeResult.manufacturer} {probeResult.model} <span className="text-muted-foreground mono text-xs">FW {probeResult.firmware}</span>{probeResult.ptz_supported && <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-[#0044FF] text-white">PTZ</span>}</p>
              {probeResult.profiles.map((p) => (
                <div key={p.token} className="flex items-center justify-between text-xs">
                  <span className="mono truncate mr-2">{p.name} — {p.resolution || "?"} {p.codec || ""} — {p.rtsp_url || "URI indisponible"}</span>
                  {p.rtsp_url && (
                    <button onClick={() => onPrefill({ name: `${probeResult.model} (${probeResult.ip})`, ip: probeResult.ip, model: probeResult.model, rtsp_url: p.rtsp_url, protocol: "RTSP", codec: (p.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264", ptz_enabled: probeResult.ptz_supported, ...creds })}
                      className="px-2 py-1 bg-[#0044FF] text-white shrink-0">Pré-remplir</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
