import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  Plus, Wifi, WifiOff, Camera as CamIcon, Trash2, Activity, Loader2, Radar,
  CheckCircle2, XCircle, AlertTriangle, Pencil, Wand2, ChevronRight, BrainCircuit,
} from "lucide-react";
import { toast } from "sonner";

const EMPTY_FORM = {
  name: "", site_id: "", mode: "onvif",
  ip: "", rtsp_port: 554, onvif_port: 80,
  protocol: "ONVIF", codec: "H264", model: "", manufacturer: "", firmware: "",
  rtsp_url: "", username: "", password: "",
  profile_token: "", profile_name: "",
  resolution: "", fps: null, bitrate: null,
  ptz_enabled: false, record_enabled: true, detect_enabled: false,
  record_mode: "continuous", storage_pool_id: "", storage_max_size_gb: 0,
  rtsp_transport: "tcp", preferred_codec: "auto",
  // Assistant RTSP
  wiz_brand: "", wiz_model_idx: 0, wiz_stream: "main", wiz_channel: 1,
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
  const [debugSnap, setDebugSnap] = useState(null);
  const [diagState, setDiagState] = useState(null);
  const [discOpen, setDiscOpen] = useState(false);
  const [connCheck, setConnCheck] = useState(null);
  const [checking, setChecking] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [brands, setBrands] = useState([]);
  const [profiles, setProfiles] = useState([]); // profils ONVIF découverts
  const [pools, setPools] = useState([]);
  useEffect(() => { api.get("/storage/overview").then((r) => setPools(r.data.pools || [])).catch(() => {}); }, [open]);

  const load = () => {
    const q = filterSite ? `?site_id=${filterSite}` : "";
    api.get(`/cameras${q}`).then((r) => setCams(r.data)).catch(() => {});
  };
  useEffect(() => { api.get("/sites").then((r) => setSites(r.data)); }, []);
  useEffect(() => { api.get("/cameras/brands").then((r) => setBrands(r.data.brands || [])).catch(() => {}); }, []);
  useEffect(load, [filterSite]);
  useEffect(() => { const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [filterSite]);

  const closeDialog = () => { setOpen(false); setEditingId(null); setForm(EMPTY_FORM); setConnCheck(null); setProfiles([]); };
  const openCreate = () => { setEditingId(null); setForm(EMPTY_FORM); setConnCheck(null); setProfiles([]); setOpen(true); };
  const openEdit = (c) => {
    setEditingId(c.id);
    setForm({
      ...EMPTY_FORM,
      name: c.name || "", site_id: c.site_id || "",
      mode: c.mode || (c.protocol === "ONVIF" ? "onvif" : "rtsp"),
      ip: c.ip || "", rtsp_port: c.rtsp_port || 554, onvif_port: c.onvif_port || 80,
      protocol: c.protocol || "RTSP", codec: c.codec || "H264",
      model: c.model || "", manufacturer: c.manufacturer || "", firmware: c.firmware || "",
      rtsp_url: c.rtsp_url || "", username: c.username || "", password: "",
      profile_token: c.profile_token || "", profile_name: c.profile_name || "",
      resolution: c.resolution || "", fps: c.fps || null, bitrate: c.bitrate || null,
      ptz_enabled: !!c.ptz_enabled, record_enabled: c.record_enabled !== false, detect_enabled: !!c.detect_enabled,
      record_mode: c.record_mode || "continuous",
      storage_pool_id: c.storage_pool_id || "",
      storage_max_size_gb: c.storage_max_size_gb || 0,
      rtsp_transport: c.rtsp_transport || "tcp",
      preferred_codec: c.preferred_codec || "auto",
    });
    setConnCheck(null); setProfiles([]); setOpen(true);
    // Charge assignation de stockage existante
    api.get(`/storage/cameras/${c.id}/assignment`).then((r) => {
      setForm((f) => ({ ...f, record_mode: r.data.record_mode || "continuous",
                        storage_pool_id: r.data.storage_pool_id || "",
                        storage_max_size_gb: r.data.max_size_gb || 0 }));
    }).catch(() => {});
  };

  const runConnectivity = async () => {
    if (!form.ip) { toast.error("Adresse IP obligatoire"); return null; }
    if (form.mode === "rtsp" && !form.rtsp_url) { toast.error("Mode RTSP : renseignez l'URL RTSP"); return null; }
    setChecking(true); setConnCheck(null);
    try {
      const { data } = await api.post("/cameras/test-connectivity", {
        mode: form.mode, ip: form.ip,
        rtsp_port: Number(form.rtsp_port) || 554, onvif_port: Number(form.onvif_port) || 80,
        rtsp_url: form.mode === "rtsp" ? form.rtsp_url : "",
        username: form.username, password: form.password,
        rtsp_transport: form.rtsp_transport || "tcp",
        preferred_codec: form.preferred_codec || "auto",
      });
      setConnCheck(data);
      if (data.profiles && data.profiles.length) {
        setProfiles(data.profiles);
        // Sélectionne automatiquement le premier profil si aucun choisi
        if (!form.profile_token && data.profiles.length > 0) {
          const first = data.profiles.find((p) => p.rtsp_url) || data.profiles[0];
          setForm((f) => ({ ...f, profile_token: first.token || "", profile_name: first.name || "" }));
        }
      }
      return data;
    } catch (e) { toast.error("Test de connectivité échoué"); return null; }
    finally { setChecking(false); }
  };

  const autoDetect = async () => {
    if (!form.ip) { toast.error("Renseignez l'IP pour la détection automatique"); return; }
    setDetecting(true);
    try {
      const { data } = await api.post("/cameras/auto-detect", {
        ip: form.ip, onvif_port: Number(form.onvif_port) || 80,
        username: form.username, password: form.password,
      });
      setProfiles(data.profiles || []);
      const first = (data.profiles || []).find((p) => p.rtsp_url) || (data.profiles || [])[0];
      setForm((f) => ({
        ...f, mode: "onvif", protocol: "ONVIF",
        manufacturer: data.manufacturer || f.manufacturer,
        model: (data.manufacturer && data.model) ? `${data.manufacturer} ${data.model}` : (data.model || f.model),
        firmware: data.firmware || f.firmware,
        ptz_enabled: !!data.ptz_supported,
        profile_token: first?.token || "",
        profile_name: first?.name || "",
        codec: (first?.codec || data.live_codec || f.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264",
        resolution: first?.resolution || data.live_resolution || f.resolution,
        fps: data.live_fps || f.fps,
        name: f.name || `${data.model || "Caméra"} (${data.ip})`,
      }));
      toast.success(`Caméra détectée : ${data.manufacturer} ${data.model} · ${data.profiles?.length || 0} profil(s)`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Détection échouée"); }
    finally { setDetecting(false); }
  };

  const applyWizard = async () => {
    if (!form.wiz_brand || !form.ip) { toast.error("Fabricant + IP requis"); return; }
    try {
      const { data } = await api.post("/cameras/generate-rtsp-url", {
        brand: form.wiz_brand, model_idx: form.wiz_model_idx || 0,
        stream: form.wiz_stream, ip: form.ip,
        port: Number(form.rtsp_port) || 554,
        channel: Number(form.wiz_channel) || 1,
        username: form.username, password: form.password,
      });
      setForm((f) => ({ ...f, rtsp_url: data.rtsp_url }));
      toast.success("URL RTSP générée");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Génération impossible"); }
  };

  const submit = async ({ allow_rtsp_override = false } = {}) => {
    if (!form.name || !form.site_id) return toast.error("Nom et site requis");
    if (!form.ip) return toast.error("Adresse IP requise");
    if (form.mode === "rtsp" && !form.rtsp_url) return toast.error("URL RTSP requise (mode RTSP)");

    setSaving(true);
    try {
      const check = connCheck?.success ? connCheck : (allow_rtsp_override && connCheck ? connCheck : await runConnectivity());
      const onvifOk = check?.steps?.find((s) => s.name === "onvif_auth")?.status === "ok";
      const rtspOk = check?.steps?.find((s) => s.name === "rtsp_open")?.status === "ok";
      if (!allow_rtsp_override) {
        if (!check || !check.success || !check.rtsp_url_validated) {
          if (form.mode === "onvif" && onvifOk && !rtspOk) {
            toast.warning("Test RTSP échoué. ONVIF fonctionne — utilisez « Créer malgré le test RTSP » pour continuer.");
            setSaving(false); return;
          }
          toast.error(check?.message || "URL RTSP non validée — impossible de créer la caméra");
          setSaving(false); return;
        }
      } else if (!onvifOk) {
        toast.error("Impossible de forcer : ONVIF n'a pas répondu correctement");
        setSaving(false); return;
      }
      const { wiz_brand, wiz_model_idx, wiz_stream, wiz_channel, record_mode, storage_pool_id, storage_max_size_gb, ...payload } = form;
      if (form.mode === "onvif") payload.rtsp_url = ""; // backend re-découvre via profile_token
      payload.allow_rtsp_override = allow_rtsp_override;
      let camId = editingId;
      if (editingId) {
        await api.put(`/cameras/${editingId}`, payload);
        toast.success("Caméra mise à jour (go2rtc rechargé)");
      } else {
        const { data: created } = await api.post("/cameras", payload);
        camId = created.id;
        toast.success("Caméra ajoutée (flux vérifié)");
      }
      // Sauvegarde l'assignation stockage / mode enregistrement
      try {
        await api.put(`/storage/cameras/${camId}/assignment`, {
          storage_pool_id: storage_pool_id || "",
          max_size_gb: Number(storage_max_size_gb) || 0,
          record_mode: record_mode || "continuous",
          profile_token: form.profile_token || "",
        });
      } catch (e) { /* ignoré : la caméra a été créée */ }
      closeDialog(); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec de la sauvegarde"); }
    finally { setSaving(false); }
  };

  const test = async (c) => {
    setTesting(c.id);
    try { const { data } = await api.post(`/cameras/${c.id}/test`);
      const extra = data.resolution ? ` (${data.resolution}${data.fps ? ` @ ${data.fps}fps` : ""}${data.codec ? ` ${data.codec}` : ""})` : "";
      data.success ? toast.success(`${c.name}: ${data.message}${extra}`) : toast.error(`${c.name}: ${data.message}`);
      load(); } catch (e) { toast.error("Échec du test"); } finally { setTesting(null); }
  };
  const snapshot = async (c) => {
    try { const { data } = await api.post(`/cameras/${c.id}/snapshot`);
      const token = localStorage.getItem("mg_token");
      const url = `${process.env.REACT_APP_BACKEND_URL}/api${data.snapshot_url}?token=${encodeURIComponent(token || "")}&t=${Date.now()}`;
      setSnap({ ...data, snapshot_url: url, name: c.name }); } catch (e) { toast.error("Échec — flux injoignable"); }
  };
  const del = async (c) => { if (!window.confirm(`Supprimer ${c.name} ?`)) return; await api.delete(`/cameras/${c.id}`); toast.success("Supprimée"); load(); };

  const openDebug = async (c) => {
    try {
      const { data } = await api.get(`/ai/debug/${c.id}`);
      if (!data.available) return toast.error(data.message || "Aucune analyse IA disponible — activez la détection IA sur cette caméra");
      setDebugSnap({ ...data, cam_name: c.name });
    } catch (e) { toast.error("Debug IA indisponible"); }
  };

  const openDiagnostic = async (c) => {
    setDiagState({ loading: true, cam: c });
    try {
      const { data } = await api.get(`/cameras/${c.id}/diagnostic`);
      setDiagState({ loading: false, cam: c, ...data });
    } catch (e) { toast.error("Diagnostic indisponible"); setDiagState(null); }
  };

  const currentBrand = brands.find((b) => b.id === form.wiz_brand);
  const currentModel = currentBrand?.models?.[form.wiz_model_idx];

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("cam.title")}</h1>
        <div className="flex items-center gap-2">
          <select value={filterSite} onChange={(e) => setFilterSite(e.target.value)} data-testid="camera-site-filter" className="px-3 py-2 bg-card border border-input text-sm outline-none">
            <option value="">{t("common.all")} — {t("nav.sites")}</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {can("technician") && <button onClick={() => setDiscOpen(true)} data-testid="onvif-discover-btn" className="flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary"><Radar size={16} /> Scan ONVIF</button>}
          {can("technician") && <button onClick={openCreate} data-testid="add-camera-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("cam.add")}</button>}
        </div>
      </div>

      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-2">{t("common.status")}</th><th className="px-3 py-2">{t("common.name")}</th><th className="px-3 py-2">{t("common.site")}</th>
            <th className="px-3 py-2">{t("cam.ip")}</th><th className="px-3 py-2">Mode</th><th className="px-3 py-2">Résolution</th>
            <th className="px-3 py-2">{t("cam.ptz")}</th><th className="px-3 py-2 text-right">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {cams.map((c) => (
              <tr key={c.id} className="border-b border-border hover:bg-secondary/50" data-testid="camera-row">
                <td className="px-3 py-2"><span className={`inline-flex items-center gap-1.5 text-xs ${c.status === "online" ? "mg-online" : "mg-offline"}`}>
                  {c.status === "online" ? <Wifi size={13} /> : <WifiOff size={13} />}{t(c.status === "online" ? "common.online" : "common.offline")}</span></td>
                <td className="px-3 py-2 font-medium">{c.name}<div className="text-[10px] text-muted-foreground truncate max-w-xs">{c.manufacturer} {c.model}</div></td>
                <td className="px-3 py-2 text-muted-foreground">{c.site_name}</td>
                <td className="px-3 py-2 mono text-xs">{c.ip}</td>
                <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 border border-border uppercase">{c.mode || c.protocol}</span></td>
                <td className="px-3 py-2 mono text-[11px]">{c.resolution || "—"}{c.fps ? ` @ ${c.fps}` : ""} <span className="text-muted-foreground">{c.codec}</span></td>
                <td className="px-3 py-2 text-xs">{c.ptz_enabled ? "✓" : "—"}</td>
                <td className="px-3 py-2"><div className="flex items-center justify-end gap-1">
                  <button onClick={() => test(c)} data-testid="test-camera-btn" title="Tester" className="p-1.5 hover:bg-secondary">{testing === c.id ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}</button>
                  <button onClick={() => openDiagnostic(c)} data-testid="diagnostic-btn" title="Diagnostic complet" className="p-1.5 hover:bg-secondary text-[#00E676]"><Radar size={15} /></button>
                  <button onClick={() => snapshot(c)} data-testid="snapshot-btn" title="Snapshot" className="p-1.5 hover:bg-secondary"><CamIcon size={15} /></button>
                  {c.detect_enabled && <button onClick={() => openDebug(c)} data-testid="debug-ia-btn" title="Debug IA (dernier snapshot d'analyse)" className="p-1.5 hover:bg-secondary text-[#0044FF]"><BrainCircuit size={15} /></button>}
                  {can("technician") && <button onClick={() => openEdit(c)} data-testid="edit-camera-btn" title="Modifier" className="p-1.5 hover:bg-secondary"><Pencil size={15} /></button>}
                  {can("technician") && <button onClick={() => del(c)} data-testid="delete-camera-btn" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={(o) => { if (!o) closeDialog(); }}>
        <DialogContent className="rounded-none border-border max-w-3xl max-h-[92vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-head">{editingId ? "Modifier la caméra" : "Ajouter une caméra"}</DialogTitle></DialogHeader>

          {/* Mode toggle */}
          <div className="flex items-center gap-2 mb-2" data-testid="cam-mode-toggle">
            {[
              { v: "onvif", label: "Mode ONVIF (recommandé)" },
              { v: "rtsp", label: "Mode RTSP manuel" },
            ].map((m) => (
              <button key={m.v} type="button" onClick={() => { setForm({ ...form, mode: m.v, protocol: m.v.toUpperCase() }); setConnCheck(null); }}
                data-testid={`cam-mode-${m.v}`}
                className={`px-3 py-1.5 text-xs uppercase tracking-wider border ${form.mode === m.v ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}>
                {m.label}
              </button>
            ))}
            <span className="text-[11px] text-muted-foreground ml-auto">
              {form.mode === "onvif" ? "L'URL RTSP est découverte automatiquement." : "URL RTSP saisie manuellement ou générée."}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Nom"><input data-testid="cam-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label="Site">
              <select data-testid="cam-form-site" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} className="inp">
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label="Adresse IP"><input data-testid="cam-form-ip" value={form.ip} onChange={(e) => setForm({ ...form, ip: e.target.value })} className="inp" placeholder="192.168.1.10" /></Field>
            <Field label={form.mode === "onvif" ? "Port ONVIF" : "Port RTSP"}>
              <input data-testid="cam-form-port" type="number" min="1" max="65535"
                value={form.mode === "onvif" ? form.onvif_port : form.rtsp_port}
                onChange={(e) => setForm({ ...form, [form.mode === "onvif" ? "onvif_port" : "rtsp_port"]: e.target.value })}
                className="inp mono" />
            </Field>
            <Field label={form.mode === "onvif" ? "Identifiant ONVIF" : "Identifiant (optionnel)"}><input data-testid="cam-form-username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="inp" autoComplete="off" /></Field>
            <Field label={form.mode === "onvif" ? "Mot de passe ONVIF" : "Mot de passe (optionnel)"}><input data-testid="cam-form-password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" autoComplete="new-password" placeholder={editingId ? "(inchangé si vide)" : ""} /></Field>

            {/* --- Bloc ONVIF : auto-détect + profils --- */}
            {form.mode === "onvif" && (
              <div className="col-span-2 border border-border p-3 space-y-2" data-testid="onvif-panel">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Détection automatique</span>
                  <button type="button" onClick={autoDetect} disabled={detecting} data-testid="auto-detect-btn"
                    className="px-3 py-1.5 bg-[#00E676]/20 text-[#00E676] border border-[#00E676] hover:bg-[#00E676]/30 text-xs flex items-center gap-1">
                    {detecting ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} Détecter automatiquement la caméra
                  </button>
                </div>
                {form.manufacturer && (
                  <div className="text-xs mono text-muted-foreground" data-testid="onvif-detected">
                    {form.manufacturer} · {form.model} · FW {form.firmware} {form.ptz_enabled && <span className="ml-1 text-[9px] px-1 bg-[#0044FF] text-white">PTZ</span>}
                  </div>
                )}
                {profiles.length > 0 && (
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground">Profil vidéo</label>
                    <div className="mt-1 space-y-1" data-testid="onvif-profiles">
                      {profiles.map((p, i) => (
                        <label key={p.token || i} className="flex items-center gap-2 p-2 border border-border cursor-pointer hover:bg-secondary/50">
                          <input type="radio" name="profile"
                            checked={form.profile_token === p.token}
                            onChange={() => setForm({ ...form, profile_token: p.token, profile_name: p.name, codec: (p.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264", resolution: p.resolution || form.resolution })}
                            data-testid={`profile-radio-${i}`} />
                          <div className="flex-1 text-xs">
                            <div className="font-medium">{p.name} <span className="text-muted-foreground mono">{p.resolution || ""} {p.codec || ""}</span></div>
                            <div className="text-[10px] text-muted-foreground truncate mono">{p.rtsp_url || "(pas d'URI RTSP)"}</div>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* --- Bloc RTSP : assistant + URL manuelle --- */}
            {form.mode === "rtsp" && (
              <div className="col-span-2 border border-border p-3 space-y-2" data-testid="rtsp-wizard">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Assistant RTSP</span>
                  <span className="text-[10px] text-muted-foreground">Génère l&apos;URL depuis le fabricant. Toujours modifiable.</span>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  <select value={form.wiz_brand} onChange={(e) => setForm({ ...form, wiz_brand: e.target.value, wiz_model_idx: 0, wiz_stream: "main" })} className="inp text-xs" data-testid="wiz-brand">
                    <option value="">Fabricant…</option>
                    {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                  <select value={form.wiz_model_idx} onChange={(e) => setForm({ ...form, wiz_model_idx: Number(e.target.value), wiz_stream: "main" })} className="inp text-xs" disabled={!currentBrand} data-testid="wiz-model">
                    {currentBrand?.models?.map((m, i) => <option key={i} value={i}>{m.name}</option>)}
                  </select>
                  <select value={form.wiz_stream} onChange={(e) => setForm({ ...form, wiz_stream: e.target.value })} className="inp text-xs" disabled={!currentModel} data-testid="wiz-stream">
                    {currentModel?.streams?.map((s) => <option key={s} value={s}>{streamLabel(s)}</option>)}
                  </select>
                  <div className="flex items-center gap-1">
                    <input type="number" min="1" max="64" placeholder="Canal"
                      value={form.wiz_channel} onChange={(e) => setForm({ ...form, wiz_channel: e.target.value })}
                      className="inp text-xs mono" style={{ width: 60 }} title="Numéro de canal (multi-cam)" data-testid="wiz-channel" />
                    <button type="button" onClick={applyWizard} disabled={!form.wiz_brand} data-testid="wiz-generate-btn"
                      className="px-3 py-2 bg-[#0044FF] text-white text-xs flex items-center gap-1 hover:bg-[#0033cc] disabled:opacity-50">
                      <ChevronRight size={12} /> Générer
                    </button>
                  </div>
                </div>
                {currentModel?.help && <p className="text-[10px] text-muted-foreground border-l-2 border-[#FFB800] pl-2 mt-1">{currentModel.help}</p>}
                <div>
                  <label className="text-[10px] uppercase tracking-wider text-muted-foreground">URL RTSP (modifiable)</label>
                  <input data-testid="cam-form-rtsp-url" value={form.rtsp_url}
                    onChange={(e) => setForm({ ...form, rtsp_url: e.target.value })}
                    className="inp mono text-xs mt-1" placeholder="rtsp://..." />
                </div>
              </div>
            )}

            {/* Options avancées enregistrement / IA */}
            <div className="col-span-2 flex items-center gap-5 flex-wrap">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.ptz_enabled} onChange={(e) => setForm({ ...form, ptz_enabled: e.target.checked })} /> PTZ</label>
              <label className="flex items-center gap-2 text-sm" data-testid="record-toggle"><input type="checkbox" checked={form.record_enabled} onChange={(e) => setForm({ ...form, record_enabled: e.target.checked })} /> Enregistrement activé</label>
              <label className="flex items-center gap-2 text-sm" data-testid="detect-toggle"><input type="checkbox" checked={form.detect_enabled} onChange={(e) => setForm({ ...form, detect_enabled: e.target.checked })} /> Détection IA (YOLO + LAPI)</label>
            </div>

            {/* Transport RTSP + codec préféré */}
            <div className="col-span-2 grid grid-cols-2 md:grid-cols-3 gap-3 border border-border p-3 bg-secondary/30">
              <div className="md:col-span-3 text-[10px] uppercase tracking-wider text-muted-foreground">Transport & codec</div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Transport RTSP</label>
                <select value={form.rtsp_transport} onChange={(e) => setForm({ ...form, rtsp_transport: e.target.value })} className="inp" data-testid="rtsp-transport">
                  <option value="tcp">TCP (recommandé)</option>
                  <option value="udp">UDP</option>
                </select>
                <p className="text-[10px] text-muted-foreground mt-0.5">TCP = plus stable, UDP = plus faible latence</p>
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Codec préféré</label>
                <select value={form.preferred_codec} onChange={(e) => setForm({ ...form, preferred_codec: e.target.value })} className="inp" data-testid="preferred-codec">
                  <option value="auto">Auto (recommandé)</option>
                  <option value="h264">H.264 (compatibilité maximale)</option>
                  <option value="h265">H.265 (HEVC — bande passante réduite)</option>
                </select>
                <p className="text-[10px] text-muted-foreground mt-0.5">Live/IA préfèrent H.264, l&apos;enregistrement peut utiliser H.265</p>
              </div>
            </div>

            {/* Config enregistrement avancée : mode + canal ONVIF + disque cible */}
            {form.record_enabled && (
              <div className="col-span-2 border border-border p-3 space-y-3 bg-secondary/30" data-testid="record-cfg">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Configuration d&apos;enregistrement</div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Mode</label>
                    <select value={form.record_mode} onChange={(e) => setForm({ ...form, record_mode: e.target.value })} className="inp" data-testid="record-mode">
                      <option value="continuous">Continu (24/7)</option>
                      <option value="motion">Sur mouvement</option>
                      <option value="ai">Sur événement IA</option>
                      <option value="off">Désactivé</option>
                    </select>
                    <p className="text-[10px] text-muted-foreground mt-0.5">Mouvement/IA : les segments sans détection sont supprimés à l&apos;indexation.</p>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Canal ONVIF (profil)</label>
                    <select value={form.profile_token} onChange={(e) => setForm({ ...form, profile_token: e.target.value })} className="inp" disabled={profiles.length === 0} data-testid="record-profile">
                      <option value="">— Défaut (Main stream) —</option>
                      {profiles.map((p) => (
                        <option key={p.token} value={p.token}>{p.name} {p.resolution ? `· ${p.resolution}` : ""}</option>
                      ))}
                    </select>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{profiles.length === 0 ? "Lancez le test ONVIF pour lister les canaux." : `${profiles.length} profil(s) découverts`}</p>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Disque cible</label>
                    <select value={form.storage_pool_id} onChange={(e) => setForm({ ...form, storage_pool_id: e.target.value })} className="inp" data-testid="record-pool">
                      <option value="">— Défaut ({pools.length} pool(s) déclaré(s)) —</option>
                      {pools.filter((p) => p.enabled).map((p) => (
                        <option key={p.id} value={p.id}>{p.name} — {p.usage?.free_gb ?? "?"} Go libres</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Quota max. (Go)</label>
                    <input type="number" min="0" value={form.storage_max_size_gb} onChange={(e) => setForm({ ...form, storage_max_size_gb: e.target.value })} className="inp mono" placeholder="0 = illimité" data-testid="record-quota" />
                  </div>
                </div>
              </div>
            )}

            {/* Test de connexion multi-étapes */}
            <div className="col-span-2 border border-border p-3 space-y-2" data-testid="conn-test-block">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Test de connexion ({form.mode.toUpperCase()}) — obligatoire</span>
                <button type="button" onClick={runConnectivity} disabled={checking} data-testid="conn-test-btn"
                  className="px-3 py-1.5 border border-border hover:bg-secondary text-xs flex items-center gap-1">
                  {checking && <Loader2 size={12} className="animate-spin" />} Tester la connexion
                </button>
              </div>
              {!connCheck && <p className="text-muted-foreground text-[11px]">Cliquez sur « Tester la connexion » — chaque étape (Ping · ONVIF · RTSP · go2rtc · Aperçu) affichera son statut ci-dessous.</p>}
              {connCheck && (
                <div className="space-y-1" data-testid="conn-test-result">
                  {connCheck.steps.map((s, i) => <StepRow key={i} step={s} />)}
                  <div className="text-[11px] mt-1" style={{ color: connCheck.success ? "#00E676" : "#FF3333" }}>{connCheck.message}</div>
                  {/* Debug RTSP : URLs testées avec password masqué (P0 finalisation) */}
                  {connCheck.debug_attempts && connCheck.debug_attempts.length > 0 && (
                    <details className="mt-2 border border-border bg-background/40 p-2" open={!connCheck.rtsp_url_validated} data-testid="rtsp-debug-panel">
                      <summary className="text-[10px] uppercase tracking-wider text-muted-foreground cursor-pointer">
                        Debug RTSP — {connCheck.debug_attempts.length} tentative(s)
                        {connCheck.rtsp_url_validated && (
                          <span className="ml-2 text-[#00E676]">✓ URL validée</span>
                        )}
                      </summary>
                      <ol className="mt-1.5 space-y-0.5 text-[10px] mono">
                        {connCheck.debug_attempts.map((a, i) => (
                          <li key={i} className={"flex items-center gap-1 " + (a.ok ? "text-[#00E676]" : "text-muted-foreground")}>
                            <span className="text-[9px]">{a.ok ? "✓" : "✗"}</span>
                            <span className="text-[9px] px-1 border border-border">{a.transport}</span>
                            <span className="truncate flex-1" title={a.url_masked}>{a.url_masked}</span>
                            {a.ok && a.codec && <span className="text-[9px]">{a.codec} {a.resolution}</span>}
                          </li>
                        ))}
                      </ol>
                      {connCheck.validated_url && (
                        <div className="mt-2 text-[10px] mono text-[#00E676] border-t border-border pt-1.5" data-testid="validated-url">
                          <span className="text-muted-foreground">URL retenue : </span>{connCheck.validated_url}
                          {connCheck.validated_transport && <span className="text-muted-foreground"> · {connCheck.validated_transport.toUpperCase()}</span>}
                        </div>
                      )}
                    </details>
                  )}
                  {connCheck.steps.find((s) => s.preview_url) && (
                    <div className="mt-2">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Aperçu vidéo</div>
                      <img alt="preview" src={`${process.env.REACT_APP_BACKEND_URL}/api/stream/preview.jpeg?name=${connCheck.steps.find((s) => s.temp_stream).temp_stream}&token=${encodeURIComponent(localStorage.getItem("mg_token") || "")}`}
                        className="max-h-40 border border-border" data-testid="conn-test-preview" />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <button onClick={closeDialog} className="px-4 py-2 border border-border text-sm hover:bg-secondary">Annuler</button>
            {(() => {
              const onvifOk = connCheck?.steps?.find((s) => s.name === "onvif_auth")?.status === "ok";
              const rtspOk = connCheck?.steps?.find((s) => s.name === "rtsp_open")?.status === "ok";
              const canOverride = form.mode === "onvif" && !editingId && connCheck && onvifOk && !rtspOk;
              return canOverride ? (
                <button onClick={() => submit({ allow_rtsp_override: true })} disabled={saving}
                        data-testid="cam-form-override" title="ONVIF est validé mais le test RTSP a échoué — la caméra sera enregistrée hors ligne, corrigez le RTSP manuellement ensuite."
                        className="px-4 py-2 border border-[#FFB800] text-[#FFB800] hover:bg-[#FFB800]/10 text-sm flex items-center gap-2">
                  {saving && <Loader2 size={15} className="animate-spin" />} Créer malgré le test RTSP
                </button>
              ) : null;
            })()}
            <button onClick={() => submit()} disabled={saving} data-testid="cam-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{editingId ? "Enregistrer les modifications" : "Créer la caméra"}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {snap && (
        <Dialog open={!!snap} onOpenChange={(o) => !o && setSnap(null)}>
          <DialogContent className="rounded-none border-border max-w-2xl p-0">
            <DialogHeader className="px-3 py-2 border-b border-border"><DialogTitle className="text-sm mono">{snap.name} — snapshot</DialogTitle></DialogHeader>
            <img src={snap.snapshot_url} alt="snapshot" className="w-full" data-testid="snapshot-image" />
          </DialogContent>
        </Dialog>
      )}

      {debugSnap && (
        <Dialog open={!!debugSnap} onOpenChange={(o) => !o && setDebugSnap(null)}>
          <DialogContent className="rounded-none border-border max-w-3xl max-h-[92vh] overflow-y-auto" data-testid="debug-ia-dialog">
            <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><BrainCircuit size={18} /> Debug IA — {debugSnap.cam_name}</DialogTitle></DialogHeader>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="col-span-2 border border-border p-2 mono">
                <div>Résolution analysée : <b>{debugSnap.resolution}</b> · Device : <b>{debugSnap.device}</b> · Timestamp : {new Date(debugSnap.timestamp).toLocaleString()}</div>
                <div className="mt-1">
                  Timings : YOLO <b>{debugSnap.timings?.yolo_ms}ms</b> · ALPR <b>{debugSnap.timings?.alpr_ms}ms</b>
                  · décodage {debugSnap.timings?.decode_ms}ms · mouvement {debugSnap.timings?.motion_ms}ms · <b>total {debugSnap.timings?.total_ms}ms</b>
                </div>
                <div className="mt-1">Mouvement : <b>{debugSnap.motion_pct}%</b></div>
              </div>
              <div className="col-span-2">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Image analysée</div>
                {debugSnap.frame_preview && <img src={debugSnap.frame_preview} alt="frame" className="w-full border border-border" />}
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Véhicules détectés ({debugSnap.vehicles?.length || 0})</div>
                {(debugSnap.vehicles || []).map((v, i) => (
                  <div key={i} className="mono text-[11px] border border-border p-1.5 mb-1">
                    {v.label} · conf {v.confidence} · couleur {v.vehicle_color || "—"}
                  </div>
                ))}
                {(!debugSnap.vehicles || !debugSnap.vehicles.length) && <p className="text-[11px] text-muted-foreground">(aucun)</p>}
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Plaques OCR ({debugSnap.plate_attempts?.length || 0} tentatives)</div>
                {(debugSnap.plate_attempts || []).map((p, i) => (
                  <div key={i} className="mono text-[11px] border border-border p-1.5 mb-1" style={{ color: p.kept ? "#00E676" : "#FFB800" }}>
                    <b>{p.plate}</b> {p.size && <span>({p.size})</span>}
                    {p.confidence !== undefined && <span> · conf {p.confidence}</span>}
                    {p.skipped && <span className="text-[#FFB800]"> · ignoré : {p.skipped}</span>}
                    {p.expires_in !== undefined && <span> ({p.expires_in}s)</span>}
                  </div>
                ))}
                {(!debugSnap.plate_attempts || !debugSnap.plate_attempts.length) && <p className="text-[11px] text-muted-foreground">(aucune tentative — pas de véhicule)</p>}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}

      <OnvifDiscovery open={discOpen} onClose={() => setDiscOpen(false)}
        onPick={(dev) => { setEditingId(null); setForm({ ...EMPTY_FORM, ip: dev.ip, onvif_port: dev.port || 80, mode: "onvif", protocol: "ONVIF" }); setDiscOpen(false); setOpen(true); }} />
      {diagState && <DiagnosticDialog state={diagState} onClose={() => setDiagState(null)} onRefresh={() => openDiagnostic(diagState.cam)} />}
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function DiagnosticDialog({ state, onClose, onRefresh }) {
  const { cam, loading, camera, flux, ai, stats_24h, last_event, last_plate } = state;
  const ok = (v) => v ? <CheckCircle2 size={13} className="text-[#00E676]" /> : <XCircle size={13} className="text-[#FF3333]" />;
  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl" data-testid="diagnostic-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Radar size={16} className="text-[#00E676]" /> Diagnostic — {cam?.name}</DialogTitle>
        </DialogHeader>
        {loading ? <div className="py-8 text-center text-muted-foreground"><Loader2 size={20} className="animate-spin inline mr-2" /> Chargement…</div> : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <section className="border border-border p-3">
              <div className="font-head font-semibold mb-2">Flux vidéo</div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">{ok(flux?.camera_online)} <span className="text-xs">Caméra {camera?.status?.toUpperCase()}</span></div>
                <div className="flex items-center gap-2">{ok(flux?.go2rtc_registered)} <span className="text-xs">go2rtc — flux enregistré</span></div>
                <div className="text-xs text-muted-foreground mono">Fabricant : <b className="text-foreground">{camera?.manufacturer || "—"}</b> · Modèle : <b className="text-foreground">{camera?.model || "—"}</b></div>
                <div className="text-xs text-muted-foreground mono">Profil : <b className="text-foreground">{camera?.profile_token || "—"}</b></div>
                <div className="text-xs text-muted-foreground mono">Transport : <b>{(flux?.rtsp_transport_used || "tcp").toUpperCase()}</b> · Codec : <b>{(camera?.codec || "auto").toUpperCase()}</b></div>
                <div className="text-xs text-muted-foreground mono">Résolution : {camera?.resolution || "—"}{camera?.fps ? ` @ ${camera.fps} FPS` : ""}</div>
                <div className="text-xs text-muted-foreground mono">Codec préféré (config) : {(camera?.preferred_codec || "auto").toUpperCase()}</div>
                {camera?.rtsp_url_masked && <div className="text-[10px] text-muted-foreground mono truncate" title={camera.rtsp_url_masked}>URL : {camera.rtsp_url_masked}</div>}
              </div>
            </section>
            <section className="border border-border p-3">
              <div className="font-head font-semibold mb-2">Intelligence artificielle</div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">{ok(ai?.detect_enabled)} <span className="text-xs">Détection IA {ai?.detect_enabled ? "active" : "désactivée"}</span></div>
                <div className="text-xs text-muted-foreground mono">Dernière analyse : {ai?.last_analysis_at ? new Date(ai.last_analysis_at).toLocaleTimeString() : "—"}</div>
                <div className="text-xs text-muted-foreground mono">YOLO : {ai?.last_yolo_ms ? `${ai.last_yolo_ms} ms` : "—"} · ALPR : {ai?.last_alpr_ms ? `${ai.last_alpr_ms} ms` : "—"}</div>
                <div className="text-xs text-muted-foreground mono">Mouvement : {ai?.motion_pct != null ? `${ai.motion_pct.toFixed(1)} %` : "—"}</div>
                <div className="text-xs text-muted-foreground mono">Détections dernière frame : <b className="text-foreground">{ai?.last_detections_count || 0}</b></div>
              </div>
            </section>
            <section className="border border-border p-3 md:col-span-2">
              <div className="font-head font-semibold mb-2">Activité (24 h)</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
                <StatBoxD label="Événements" value={stats_24h?.events || 0} />
                <StatBoxD label="Plaques lues" value={stats_24h?.plates || 0} />
                <StatBoxD label="Dernier événement" value={last_event ? new Date(last_event.timestamp).toLocaleTimeString() : "—"} small />
                <StatBoxD label="Dernière plaque" value={last_plate?.plate || "—"} small />
              </div>
              <div className="mt-3 flex items-center gap-2 justify-end">
                <button onClick={onRefresh} className="text-xs px-2.5 py-1.5 border border-border hover:bg-secondary flex items-center gap-1" data-testid="diagnostic-refresh"><Loader2 size={12} /> Actualiser</button>
              </div>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function StatBoxD({ label, value, small }) {
  return (
    <div className="border border-border p-2">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={small ? "mono text-xs mt-0.5" : "mono text-lg font-bold mt-0.5"}>{value}</div>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>;
}

function StepRow({ step }) {
  const map = {
    ok:    { Ic: CheckCircle2,  color: "#00E676", label: "OK" },
    warn:  { Ic: AlertTriangle, color: "#FFB800", label: "!"  },
    error: { Ic: XCircle,       color: "#FF3333", label: "KO" },
    skip:  { Ic: CheckCircle2,  color: "#666",    label: "—"  },
  };
  const meta = map[step.status] || map.skip;
  const Ic = meta.Ic;
  return (
    <div className="flex items-center gap-2 text-[11px]" data-testid={`step-${step.name}`}>
      <Ic size={13} style={{ color: meta.color }} />
      <span className="mono w-24 uppercase text-muted-foreground">{step.name}</span>
      <span className="flex-1" style={{ color: meta.color }}>{step.message}</span>
    </div>
  );
}

function streamLabel(key) {
  const m = {
    main: "Flux principal (Main)", sub: "Flux secondaire (Sub)", third: "3ᵉ flux",
    main_h264: "Main — H.264", sub_h264: "Sub — H.264",
    main_h265: "Main — H.265", sub_h265: "Sub — H.265",
    custom: "URL personnalisée",
  };
  return m[key] || key;
}

function OnvifDiscovery({ open, onClose, onPick }) {
  const [scanning, setScanning] = useState(false);
  const [devices, setDevices] = useState(null);

  const scan = async () => {
    setScanning(true); setDevices(null);
    try { const { data } = await api.post("/cameras/discover"); setDevices(data.devices); }
    catch (e) { toast.error("Échec de la découverte ONVIF"); }
    finally { setScanning(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none border-border max-w-2xl">
        <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><Radar size={18} /> Découverte ONVIF (WS-Discovery)</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <button onClick={scan} disabled={scanning} data-testid="onvif-scan-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">
            {scanning && <Loader2 size={15} className="animate-spin" />}{scanning ? "Scan en cours (multicast)..." : "Lancer le scan"}
          </button>
          {devices !== null && (
            <div className="border border-border">
              {devices.length === 0 && <p className="p-3 text-sm text-muted-foreground" data-testid="onvif-no-devices">Aucun appareil ONVIF détecté sur ce réseau.</p>}
              {devices.map((d) => (
                <div key={d.xaddr} className="flex items-center justify-between px-3 py-2 border-b border-border last:border-0" data-testid="onvif-device-row">
                  <div><span className="mono text-sm">{d.ip}:{d.port}</span>{d.already_added && <span className="ml-2 text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">déjà ajoutée</span>}</div>
                  <button onClick={() => onPick(d)} className="px-3 py-1 bg-[#0044FF] text-white text-xs">Utiliser cette IP</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
