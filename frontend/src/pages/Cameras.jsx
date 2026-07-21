import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  Plus, Wifi, WifiOff, Camera as CamIcon, Trash2, Activity, Loader2, Radar,
  CheckCircle2, XCircle, Pencil,
} from "lucide-react";
import { toast } from "sonner";

const CODECS = ["H264", "H265", "MJPEG"];

const EMPTY_FORM = {
  name: "", site_id: "", mode: "rtsp",
  ip: "", rtsp_port: 554, onvif_port: 80,
  protocol: "RTSP", codec: "H264", model: "",
  rtsp_url: "", username: "", password: "",
  ptz_enabled: false, record_enabled: true, detect_enabled: false,
};

export default function Cameras() {
  const { t, can } = useApp();
  const [cams, setCams] = useState([]);
  const [sites, setSites] = useState([]);
  const [filterSite, setFilterSite] = useState("");
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(null);
  const [snap, setSnap] = useState(null);
  const [discOpen, setDiscOpen] = useState(false);
  const [connCheck, setConnCheck] = useState(null);
  const [checking, setChecking] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const load = () => {
    const q = filterSite ? `?site_id=${filterSite}` : "";
    api.get(`/cameras${q}`).then((r) => setCams(r.data)).catch(() => {});
  };
  useEffect(() => { api.get("/sites").then((r) => setSites(r.data)); }, []);
  useEffect(load, [filterSite]);
  useEffect(() => { const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [filterSite]);

  const closeDialog = () => { setOpen(false); setEditingId(null); setForm(EMPTY_FORM); setConnCheck(null); };

  const openCreate = () => { setEditingId(null); setForm(EMPTY_FORM); setConnCheck(null); setOpen(true); };
  const openEdit = (c) => {
    setEditingId(c.id);
    setForm({
      ...EMPTY_FORM,
      name: c.name || "", site_id: c.site_id || "",
      mode: c.mode || (c.protocol === "ONVIF" ? "onvif" : "rtsp"),
      ip: c.ip || "", rtsp_port: c.rtsp_port || 554, onvif_port: c.onvif_port || 80,
      protocol: c.protocol || "RTSP", codec: c.codec || "H264", model: c.model || "",
      rtsp_url: c.rtsp_url || "", username: c.username || "", password: "",
      ptz_enabled: !!c.ptz_enabled, record_enabled: !!c.record_enabled, detect_enabled: !!c.detect_enabled,
    });
    setConnCheck(null); setOpen(true);
  };

  const runConnectivity = async () => {
    if (!form.ip) { toast.error("L'adresse IP est obligatoire"); return null; }
    if (form.mode === "rtsp" && !form.rtsp_url) {
      toast.error("Mode RTSP : renseignez l'URL RTSP");
      return null;
    }
    setChecking(true); setConnCheck(null);
    try {
      const { data } = await api.post("/cameras/test-connectivity", {
        mode: form.mode,
        ip: form.ip,
        rtsp_port: Number(form.rtsp_port) || 554,
        onvif_port: Number(form.onvif_port) || 80,
        rtsp_url: form.mode === "rtsp" ? form.rtsp_url : "",
        username: form.username,
        password: form.password,
      });
      setConnCheck(data);
      return data;
    } catch (e) {
      toast.error("Test de connectivité échoué");
      return null;
    } finally { setChecking(false); }
  };

  const submit = async () => {
    if (!form.name || !form.site_id) return toast.error("Nom et site requis");
    if (!form.ip) return toast.error("Adresse IP requise");
    if (form.mode === "rtsp" && !form.rtsp_url) return toast.error("URL RTSP requise (mode RTSP)");

    setSaving(true);
    try {
      const check = await runConnectivity();
      if (!check || !check.success) {
        toast.error(check?.message || "Connectivité invalide — caméra non sauvegardée");
        setSaving(false); return;
      }
      const payload = { ...form };
      if (form.mode === "onvif") payload.rtsp_url = ""; // laisse le backend le découvrir
      if (editingId) {
        await api.put(`/cameras/${editingId}`, payload);
        toast.success("Caméra mise à jour (flux rechargé)");
      } else {
        await api.post("/cameras", payload);
        toast.success("Caméra ajoutée (flux vérifié)");
      }
      closeDialog();
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec de la sauvegarde");
    } finally { setSaving(false); }
  };

  const test = async (c) => {
    setTesting(c.id);
    try {
      const { data } = await api.post(`/cameras/${c.id}/test`);
      const extra = data.resolution
        ? ` (${data.resolution}${data.fps ? ` @ ${data.fps}fps` : ""}${data.codec ? ` ${data.codec}` : ""})`
        : "";
      data.success
        ? toast.success(`${c.name}: ${data.message}${extra}`)
        : toast.error(`${c.name}: ${data.message}`);
      load();
    } catch (e) { toast.error("Échec du test"); } finally { setTesting(null); }
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
            <button onClick={openCreate} data-testid="add-camera-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("cam.add")}</button>
          )}
        </div>
      </div>

      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-2">{t("common.status")}</th><th className="px-3 py-2">{t("common.name")}</th><th className="px-3 py-2">{t("common.site")}</th>
            <th className="px-3 py-2">{t("cam.ip")}</th><th className="px-3 py-2">Mode</th><th className="px-3 py-2">{t("cam.codec")}</th>
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
                <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 border border-border uppercase">{c.mode || c.protocol}</span></td>
                <td className="px-3 py-2 mono text-xs">{c.codec}</td>
                <td className="px-3 py-2 text-xs">{c.ptz_enabled ? "✓" : "—"}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => test(c)} data-testid="test-camera-btn" title={t("common.test")} className="p-1.5 hover:bg-secondary">{testing === c.id ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}</button>
                    <button onClick={() => snapshot(c)} data-testid="snapshot-btn" title={t("common.snapshot")} className="p-1.5 hover:bg-secondary"><CamIcon size={15} /></button>
                    {can("technician") && <button onClick={() => openEdit(c)} data-testid="edit-camera-btn" title="Modifier" className="p-1.5 hover:bg-secondary"><Pencil size={15} /></button>}
                    {can("technician") && <button onClick={() => del(c)} data-testid="delete-camera-btn" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={(o) => { if (!o) closeDialog(); }}>
        <DialogContent className="rounded-none border-border max-w-lg">
          <DialogHeader><DialogTitle className="font-head">{editingId ? "Modifier la caméra" : t("cam.add")}</DialogTitle></DialogHeader>

          {/* Sélecteur de mode RTSP vs ONVIF */}
          <div className="flex items-center gap-2 mb-2" data-testid="cam-mode-toggle">
            {[
              { v: "rtsp", label: "Mode RTSP" },
              { v: "onvif", label: "Mode ONVIF" },
            ].map((m) => (
              <button key={m.v} type="button" onClick={() => { setForm({ ...form, mode: m.v }); setConnCheck(null); }}
                data-testid={`cam-mode-${m.v}`}
                className={`px-3 py-1.5 text-xs uppercase tracking-wider border ${form.mode === m.v ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}>
                {m.label}
              </button>
            ))}
            <span className="text-[11px] text-muted-foreground ml-auto">
              {form.mode === "onvif"
                ? "L'URL RTSP sera découverte automatiquement via ONVIF."
                : "Fournissez directement l'URL RTSP."}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label={t("common.name")}><input data-testid="cam-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label={t("common.site")}>
              <select data-testid="cam-form-site" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} className="inp">
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label={t("cam.ip")}><input data-testid="cam-form-ip" value={form.ip} onChange={(e) => setForm({ ...form, ip: e.target.value })} className="inp" placeholder="192.168.1.10" /></Field>
            <Field label={t("cam.model")}><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="inp" /></Field>

            {/* Ports conditionnels selon le mode */}
            {form.mode === "rtsp" && (
              <Field label="Port RTSP">
                <input data-testid="cam-form-rtsp-port" type="number" min="1" max="65535"
                  value={form.rtsp_port} onChange={(e) => setForm({ ...form, rtsp_port: e.target.value })}
                  className="inp mono" />
              </Field>
            )}
            {form.mode === "onvif" && (
              <Field label="Port ONVIF">
                <input data-testid="cam-form-onvif-port" type="number" min="1" max="65535"
                  value={form.onvif_port} onChange={(e) => setForm({ ...form, onvif_port: e.target.value })}
                  className="inp mono" />
              </Field>
            )}
            <Field label={t("cam.codec")}><select value={form.codec} onChange={(e) => setForm({ ...form, codec: e.target.value })} className="inp">{CODECS.map((p) => <option key={p}>{p}</option>)}</select></Field>

            {/* URL RTSP uniquement en mode RTSP */}
            {form.mode === "rtsp" && (
              <div className="col-span-2">
                <Field label="URL RTSP (obligatoire)">
                  <input data-testid="cam-form-rtsp-url" value={form.rtsp_url}
                    onChange={(e) => setForm({ ...form, rtsp_url: e.target.value })}
                    className="inp mono text-xs" placeholder="rtsp://..." />
                </Field>
              </div>
            )}

            <Field label={form.mode === "onvif" ? "Login ONVIF" : "Login (optionnel)"}>
              <input data-testid="cam-form-username" value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })} className="inp" autoComplete="off" />
            </Field>
            <Field label={form.mode === "onvif" ? "Mot de passe ONVIF" : "Mot de passe (optionnel)"}>
              <input data-testid="cam-form-password" type="password" value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" autoComplete="new-password"
                placeholder={editingId ? "(inchangé si vide)" : ""} />
            </Field>

            <div className="col-span-2 flex items-center gap-5">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.ptz_enabled} onChange={(e) => setForm({ ...form, ptz_enabled: e.target.checked })} /> {t("cam.ptz")}</label>
              <label className="flex items-center gap-2 text-sm" data-testid="record-toggle"><input type="checkbox" checked={form.record_enabled} onChange={(e) => setForm({ ...form, record_enabled: e.target.checked })} /> Enregistrement continu</label>
              <label className="flex items-center gap-2 text-sm" data-testid="detect-toggle"><input type="checkbox" checked={form.detect_enabled} onChange={(e) => setForm({ ...form, detect_enabled: e.target.checked })} /> Détection IA</label>
            </div>

            <div className="col-span-2 border border-border p-2.5 text-xs" data-testid="conn-test-block">
              <div className="flex items-center justify-between mb-1.5">
                <span className="uppercase tracking-wider text-muted-foreground">
                  Test de connexion ({form.mode.toUpperCase()}) — obligatoire
                </span>
                <button type="button" onClick={runConnectivity} disabled={checking} data-testid="conn-test-btn" className="px-2 py-1 border border-border hover:bg-secondary flex items-center gap-1">
                  {checking && <Loader2 size={12} className="animate-spin" />} Tester la connexion
                </button>
              </div>
              {!connCheck && (
                <p className="text-muted-foreground text-[11px]">
                  {form.mode === "onvif"
                    ? "Renseignez IP + port ONVIF + identifiants puis cliquez sur « Tester la connexion »."
                    : "Renseignez IP + port RTSP + URL RTSP puis cliquez sur « Tester la connexion »."}
                </p>
              )}
              {connCheck && (
                <div className="grid grid-cols-2 gap-1 mono" data-testid="conn-test-result">
                  <Result ok={connCheck.ip_reachable} label={`Ping (${form.mode === "onvif" ? "ONVIF:" + form.onvif_port : "RTSP:" + form.rtsp_port})`} />
                  {form.mode === "onvif"
                    ? <Result ok={connCheck.onvif_reachable} label="ONVIF" />
                    : <Result ok={connCheck.rtsp_reachable} label="RTSP" />
                  }
                  <div className="col-span-2 mt-1 text-[11px]" style={{ color: connCheck.success ? "#00E676" : "#FF3333" }}>
                    {connCheck.message}
                    {connCheck.model && <span className="text-muted-foreground ml-2">({connCheck.manufacturer || ""} {connCheck.model}{connCheck.profiles_count ? ` · ${connCheck.profiles_count} profil(s)` : ""})</span>}
                    {connCheck.resolution && <span className="text-muted-foreground ml-2">({connCheck.resolution}{connCheck.fps ? ` @ ${connCheck.fps}fps` : ""} {connCheck.codec || ""})</span>}
                    {connCheck.discovered_rtsp && <div className="text-[10px] text-muted-foreground truncate mt-0.5">→ {connCheck.discovered_rtsp}</div>}
                  </div>
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <button onClick={closeDialog} className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="cam-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{editingId ? "Enregistrer les modifications" : t("common.save")}</button>
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
        onPrefill={(vals) => { setEditingId(null); setForm((f) => ({ ...EMPTY_FORM, ...f, ...vals, mode: "onvif" })); setDiscOpen(false); setOpen(true); }} />
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>;
}

function Result({ ok, label, soft }) {
  const color = ok ? "#00E676" : (soft ? "#FFB800" : "#FF3333");
  const Ic = ok ? CheckCircle2 : XCircle;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 border border-border text-[11px]" style={{ color }}>
      <Ic size={12} /> {label}
    </span>
  );
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
      setProbeResult({ ...data, ip: d.ip, port: d.port });
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
            <input placeholder="Login ONVIF" value={creds.username} onChange={(e) => setCreds({ ...creds, username: e.target.value })} className="inp" style={{ maxWidth: 140 }} autoComplete="off" />
            <input placeholder="Mot de passe" type="password" value={creds.password} onChange={(e) => setCreds({ ...creds, password: e.target.value })} className="inp" style={{ maxWidth: 140 }} autoComplete="new-password" />
          </div>
          {devices !== null && (
            <div className="border border-border">
              {devices.length === 0 && <p className="p-3 text-sm text-muted-foreground" data-testid="onvif-no-devices">Aucun appareil ONVIF détecté sur ce réseau.</p>}
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
              <p className="text-sm font-medium">
                {probeResult.manufacturer} {probeResult.model}
                <span className="text-muted-foreground mono text-xs ml-2">FW {probeResult.firmware}</span>
                {probeResult.ptz_supported && <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-[#0044FF] text-white">PTZ</span>}
              </p>
              {probeResult.profiles.map((p) => (
                <div key={p.token} className="flex items-center justify-between text-xs">
                  <span className="mono truncate mr-2">{p.name} — {p.resolution || "?"} {p.codec || ""}</span>
                  <button
                    onClick={() => onPrefill({
                      name: `${probeResult.model} (${probeResult.ip})`,
                      ip: probeResult.ip,
                      onvif_port: probeResult.port || 80,
                      model: probeResult.model,
                      protocol: "ONVIF",
                      codec: (p.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264",
                      ptz_enabled: probeResult.ptz_supported,
                      username: creds.username, password: creds.password,
                    })}
                    className="px-2 py-1 bg-[#0044FF] text-white shrink-0">Pré-remplir (ONVIF)</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
