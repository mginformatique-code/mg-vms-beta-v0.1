import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import CodecSwitch from "@/components/CodecSwitch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import CameraPluginsConfig from "@/pages/CameraPluginsConfig";
import {
  Plus, Wifi, WifiOff, Camera as CamIcon, Trash2, Activity, Loader2, Radar,
  CheckCircle2, XCircle, AlertTriangle, Pencil, Wand2, ChevronRight,
  Stethoscope, Clock,
} from "lucide-react";
import { toast } from "sonner";
import HoldToRevealInput from "@/components/ui/hold-to-reveal-input";

// v3.1.3 · Injecte user:pass dans une URL RTSP nue (profils ONVIF renvoyés
// sans identifiants) — webrtc_rtsp_url est utilisée telle quelle côté
// backend (video_core/manager.py::_webrtc_rtsp_url_of), pas de fusion
// automatique avec cam.username/password comme pour rtsp_url.
function withRtspCredentials(bareUrl, username, password) {
  if (!bareUrl) return "";
  const m = /^(rtsps?:\/\/)(.*)$/i.exec(bareUrl.trim());
  if (!m) return bareUrl;
  const [, scheme, rest] = m;
  if (!username) return bareUrl;
  const auth = password
    ? `${encodeURIComponent(username)}:${encodeURIComponent(password)}@`
    : `${encodeURIComponent(username)}@`;
  return `${scheme}${auth}${rest}`;
}

const EMPTY_FORM = {
  name: "", site_id: "", mode: "onvif",
  ip: "", rtsp_port: 554, onvif_port: 80,
  protocol: "ONVIF", codec: "H264", model: "", manufacturer: "", firmware: "",
  rtsp_url: "", username: "", password: "",
  profile_token: "", profile_name: "",
  resolution: "", fps: null, bitrate: null,
  ptz_enabled: false, record_enabled: true, detect_enabled: false,
  enabled_plugins: [],
  record_mode: "continuous", storage_pool_id: "", storage_max_size_gb: 0,
  rtsp_transport: "tcp", preferred_codec: "auto", stream_mode: "auto",
  stream_pipeline: "rtsp_native", webrtc_rtsp_url: "", ai_rtsp_url: "",
  ai_resolution: "720p",
  // camera-api-v2.2 · Couche API HTTP/HTTPS (indépendante du pipeline vidéo)
  api_host: "", api_port: null, api_scheme: "https", api_verify_ssl: false,
  api_username: "", api_password: "", api_provider: "",
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
  const [settingNtp, setSettingNtp] = useState(false);
  const [testNtp, setTestNtp] = useState(false);
  const [testing, setTesting] = useState(null);
  const [snap, setSnap] = useState(null);
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
      enabled_plugins: Array.isArray(c.enabled_plugins) ? c.enabled_plugins : [],
      record_mode: c.record_mode || "continuous",
      storage_pool_id: c.storage_pool_id || "",
      storage_max_size_gb: c.storage_max_size_gb || 0,
      rtsp_transport: c.rtsp_transport || "tcp",
      preferred_codec: c.preferred_codec || "auto",
      stream_mode: c.stream_mode || "auto",
      stream_pipeline: "rtsp_native",
      webrtc_rtsp_url: c.webrtc_rtsp_url || "",
      ai_rtsp_url: c.ai_rtsp_url || "",
      ai_resolution: c.ai_resolution || "720p",
      // camera-api-v2.2 · API caméra (HTTP/HTTPS)
      api_host: c.api_host || "",
      api_port: c.api_port || null,
      api_scheme: c.api_scheme || "https",
      api_verify_ssl: c.api_verify_ssl === true,
      api_username: c.api_username || "",
      api_password: "",     // jamais renvoyé par le backend, à re-saisir si changé
      api_provider: c.api_provider || "",
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
        stream_mode: form.stream_mode || "auto",
        profile_token: form.mode === "onvif" ? (form.profile_token || "") : "",
        test_ntp: form.mode === "onvif" ? testNtp : false,
      });
      setConnCheck(data);
      if (data.profiles && data.profiles.length) {
        setProfiles(data.profiles);
        // Sélectionne par défaut le profil de plus haute résolution (typiquement Main),
        // pas le premier de la liste (Reolink renvoie Sub en premier). L'utilisateur
        // peut toujours changer manuellement via les radios.
        if (!form.profile_token && data.profiles.length > 0) {
          const parseRes = (r) => {
            const m = /(\d+)\s*x\s*(\d+)/i.exec(r || "");
            return m ? (parseInt(m[1], 10) * parseInt(m[2], 10)) : 0;
          };
          const best = [...data.profiles]
            .filter((p) => p.rtsp_url)
            .sort((a, b) => parseRes(b.resolution) - parseRes(a.resolution))[0]
            || data.profiles[0];
          setForm((f) => ({ ...f, profile_token: best.token || "", profile_name: best.name || "",
                            codec: (best.codec || f.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264",
                            resolution: best.resolution || f.resolution }));
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
      const parseRes = (r) => {
        const m = /(\d+)\s*x\s*(\d+)/i.exec(r || "");
        return m ? (parseInt(m[1], 10) * parseInt(m[2], 10)) : 0;
      };
      const first = [...(data.profiles || [])]
        .filter((p) => p.rtsp_url)
        .sort((a, b) => parseRes(b.resolution) - parseRes(a.resolution))[0]
        || (data.profiles || [])[0];
      setForm((f) => ({
        ...f, mode: "onvif", protocol: "ONVIF",
        // v3.7.2 · Le backend essaie plusieurs ports ONVIF (80/8000/2020/8899)
        // et renvoie celui qui a RÉELLEMENT répondu — on le réinjecte dans le
        // formulaire, sinon la création qui suit repartirait sur le port saisi
        // (faux) alors que la détection a réussi sur un autre.
        onvif_port: data.onvif_port || f.onvif_port,
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
      const portNote = (data.onvif_port && Number(data.onvif_port) !== (Number(form.onvif_port) || 80))
        ? ` · port ONVIF corrigé → ${data.onvif_port}` : "";
      toast.success(`Caméra détectée : ${data.manufacturer} ${data.model} · ${data.profiles?.length || 0} profil(s)${portNote}`);
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

  const submit = async ({ allow_rtsp_override = false, force_stream_mode = null } = {}) => {
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
      } else if (!onvifOk && !rtspOk) {
        // v1.0-rc4 · L'override est autorisé si AU MOINS ONVIF OU RTSP marche.
        // Cas "ONVIF OK + RTSP OK + Go2RTC KO" doit pouvoir passer même en mode rtsp.
        toast.error("Impossible de forcer : ni ONVIF ni RTSP n'ont répondu correctement");
        setSaving(false); return;
      }
      const { wiz_brand, wiz_model_idx, wiz_stream, wiz_channel, record_mode, storage_pool_id, storage_max_size_gb, ...payload } = form;
      if (form.mode === "onvif") payload.rtsp_url = ""; // backend re-découvre via profile_token
      payload.allow_rtsp_override = allow_rtsp_override;
      // v1.0-rc4 · Override explicite du stream_mode (utilisé par le fallback
      // "Créer malgré l'erreur Go2RTC" qui force direct_rtsp).
      if (force_stream_mode) payload.stream_mode = force_stream_mode;
      let camId = editingId;
      if (editingId) {
        await api.put(`/cameras/${editingId}`, payload);
        toast.success("Caméra mise à jour");
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
    } catch (e) {
      // v1.0-rc4 · Fallback "Créer malgré l'erreur Go2RTC" :
      // Si le backend refuse à cause de Go2RTC (mais ONVIF + RTSP étaient OK),
      // proposer explicitement la création en mode direct_rtsp.
      const detail = e.response?.data?.detail;
      const detailMsg = typeof detail === "string" ? detail : (detail?.message || "");
      const isGo2rtcFailure = /go2rtc/i.test(detailMsg) && !allow_rtsp_override;
      if (isGo2rtcFailure && !editingId) {
        const proceed = window.confirm(
          "Go2RTC ne parvient pas à exploiter ce flux.\n\n" +
          "La caméra peut néanmoins être créée avec le pipeline RTSP → MG-VMS " +
          "direct (indépendant de Go2RTC, l'IA lira le flux directement).\n\n" +
          "Créer malgré l'erreur Go2RTC ?"
        );
        if (proceed) {
          // Force direct_rtsp + allow_rtsp_override, sans dépendre du re-render setForm
          setSaving(false);
          setTimeout(() => submit({
            allow_rtsp_override: true,
            force_stream_mode: "direct_rtsp",
          }), 50);
          return;
        }
      }
      toast.error(formatApiErrorDetail(detail) || "Échec de la sauvegarde");
    }
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

  const openDiagnostic = async (c) => {
    setDiagState({ loading: true, cam: c });
    try {
      const { data } = await api.get(`/cameras/${c.id}/diagnostic`);
      setDiagState({ loading: false, cam: c, ...data });
    } catch (e) { toast.error("Diagnostic indisponible"); setDiagState(null); }
  };

  // v1.0-rc4 · Diagnostic pipeline vidéo multi-étages (RTSP → Go2RTC → WebRTC)
  const [pipelineDiag, setPipelineDiag] = useState(null);
  const openPipelineDiagnostic = async (c) => {
    setPipelineDiag({ loading: true, cam: c });
    try {
      const { data } = await api.get(`/cameras/${c.id}/pipeline-diagnostic`);
      setPipelineDiag({ loading: false, cam: c, ...data });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Diagnostic pipeline indisponible");
      setPipelineDiag(null);
    }
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
            <th className="px-3 py-2">{t("common.status")}</th>
            <th className="px-3 py-2">{t("common.name")}</th>
            <th className="px-3 py-2">Site</th>
            <th className="px-3 py-2">Adresse IP</th>
            <th className="px-3 py-2">Mode</th>
            <th className="px-3 py-2">{t("cam.video_mode")}</th>
            <th className="px-3 py-2">{t("cam.resolution")}</th>
            <th className="px-3 py-2">Codec</th>
            <th className="px-3 py-2">PTZ</th>
            <th className="px-3 py-2 text-right">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {cams.map((c) => (
              <tr key={c.id} className="border-b border-border hover:bg-secondary/50 cursor-pointer" data-testid="camera-row" onClick={(e) => { if (e.target.closest("button,a,input,select")) return; window.location.href = `/camera-center/${c.id}`; }}>
                <td className="px-3 py-2"><span className={`inline-flex items-center gap-1.5 text-xs ${c.status === "online" ? "mg-online" : "mg-offline"}`}>
                  {c.status === "online" ? <Wifi size={13} /> : <WifiOff size={13} />}{t(c.status === "online" ? "common.online" : "common.offline")}</span></td>
                <td className="px-3 py-2 font-medium">{c.name}<div className="text-[10px] text-muted-foreground truncate max-w-xs">{c.manufacturer} {c.model}</div></td>
                <td className="px-3 py-2 text-muted-foreground">{c.site_name || "—"}</td>
                <td className="px-3 py-2 mono text-[11px]">{c.ip || "—"}</td>
                <td className="px-3 py-2">
                  <span className="text-[10px] px-1.5 py-0.5 border border-[#0044FF]/50 text-[#0044FF] font-semibold">
                    {(c.protocol || c.mode || "—").toUpperCase()}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {(() => {
                    // P0-fix · Solution B (Go2RTC + MJPEG) : badge dérivé de stream_mode
                    // uniquement — stream_pipeline est un champ vestige (compat DB, plus
                    // de sens fonctionnel depuis le retour à Go2RTC).
                    const isDirect = (c.stream_mode || "auto").toLowerCase() === "direct_rtsp";
                    const [label, color] = isDirect ? ["DIRECT RTSP", "#FFB800"] : ["GO2RTC", "#FFAA00"];
                    return (
                      <span
                        className="text-[10px] px-1.5 py-0.5 border font-semibold"
                        style={{ color, borderColor: `${color}80` }}
                        data-testid="video-mode-badge"
                      >
                        {label}
                      </span>
                    );
                  })()}
                </td>
                <td className="px-3 py-2 mono text-[11px]">
                  {c.resolution || "—"}{c.fps ? ` @ ${c.fps}` : ""} <span className="text-muted-foreground">{c.codec}</span>
                </td>
                <td className="px-3 py-2"><CodecSwitch camera={c} onChanged={() => load()} /></td>
                <td className="px-3 py-2 text-center">{c.ptz_enabled ? <CheckCircle2 size={14} className="text-[#00E676] inline" /> : "—"}</td>
                <td className="px-3 py-2"><div className="flex items-center justify-end gap-1">
                  <button onClick={() => test(c)} disabled={testing === c.id} data-testid="test-camera-btn" title="Tester la connexion" className="p-1.5 hover:bg-secondary">
                    {testing === c.id ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />}
                  </button>
                  <button onClick={() => openDiagnostic(c)} data-testid="diagnostic-camera-btn" title="Diagnostic" className="p-1.5 hover:bg-secondary text-[#00E676]"><Radar size={15} /></button>
                  <button onClick={() => snapshot(c)} data-testid="snapshot-camera-btn" title="Snapshot" className="p-1.5 hover:bg-secondary"><CamIcon size={15} /></button>
                  {can("technician") && <button onClick={() => openEdit(c)} data-testid="edit-camera-btn" title="Modifier" className="p-1.5 hover:bg-secondary"><Pencil size={15} /></button>}
                  {can("technician") && <button onClick={() => del(c)} data-testid="delete-camera-btn" title="Supprimer" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
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
            <Field label={form.mode === "onvif" ? "Mot de passe ONVIF" : "Mot de passe (optionnel)"}><HoldToRevealInput data-testid="cam-form-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" autoComplete="new-password" placeholder={editingId ? "(inchangé si vide)" : ""} /></Field>

            {/* --- Bloc ONVIF : auto-détect + profils --- */}
            {form.mode === "onvif" && (
              <div className="col-span-2 border border-border p-3 space-y-2" data-testid="onvif-panel">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("cam.autodetect")}</span>
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
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("cam.profile_hint")}</label>
                    <div className="mt-1 space-y-1" data-testid="onvif-profiles">
                      {profiles.map((p, i) => {
                        const label = (p.name || "").toLowerCase();
                        const isMain = /main|hd|high|primary|profile_?1|_01_main|channel1|principal/i.test(label + " " + (p.rtsp_url || ""));
                        const isSub = /sub|low|secondary|_01_sub|_02_sub|preview/i.test(label + " " + (p.rtsp_url || ""));
                        const badge = isMain ? "MAIN" : (isSub ? "SUB" : "");
                        return (
                          <label key={p.token || i} className={`flex items-center gap-2 p-2 border cursor-pointer hover:bg-secondary/50 ${form.profile_token === p.token ? "border-[#00E5FF] bg-[#00E5FF]/5" : "border-border"}`}>
                            <input type="radio" name="profile"
                              checked={form.profile_token === p.token}
                              onChange={() => { setForm({ ...form, profile_token: p.token, profile_name: p.name, codec: (p.codec || "H264").toUpperCase().replace("VIDEO", "").trim() || "H264", resolution: p.resolution || form.resolution }); setConnCheck(null); }}
                              data-testid={`profile-radio-${i}`} />
                            <div className="flex-1 text-xs">
                              <div className="font-medium flex items-center gap-2">
                                <span>{p.name}</span>
                                {badge && <span className={`text-[9px] px-1.5 py-0.5 font-bold ${isMain ? "bg-[#0044FF] text-white" : "bg-muted text-muted-foreground"}`}>{badge}</span>}
                                <span className="text-muted-foreground mono">{p.resolution || ""} {p.codec || ""}</span>
                              </div>
                              <div className="text-[10px] text-muted-foreground truncate mono">{p.rtsp_url || "(pas d'URI RTSP)"}</div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Aucune substitution de flux — l&apos;URL exacte du profil coché est persistée et utilisée par go2rtc. Cliquez sur « Tester la connexion » après avoir changé de profil pour re-valider.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* --- Bloc RTSP : assistant + URL manuelle --- */}
            {form.mode === "rtsp" && (
              <div className="col-span-2 border border-border p-3 space-y-2" data-testid="rtsp-wizard">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Assistant RTSP</span>
                  <span className="text-[10px] text-muted-foreground">{t("cam.wizard_hint")}</span>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  <select value={form.wiz_brand} onChange={(e) => setForm({ ...form, wiz_brand: e.target.value, wiz_model_idx: 0, wiz_stream: "main" })} className="inp text-xs" data-testid="wiz-brand">
                    <option value="">{t("cam.manufacturer_ph")}</option>
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
                      className="inp text-xs mono" style={{ width: 60 }} title={t("cam.channel_title")} data-testid="wiz-channel" />
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
              <label className="flex items-center gap-2 text-sm" data-testid="record-toggle"><input type="checkbox" checked={form.record_enabled} onChange={(e) => setForm({ ...form, record_enabled: e.target.checked })} /> {t("cam.record_enabled")}</label>
              <label className="flex items-center gap-2 text-sm" data-testid="detect-toggle">
                <input type="checkbox" checked={form.detect_enabled} onChange={(e) => setForm({ ...form, detect_enabled: e.target.checked })} />
                Analyse IA activée
                <span className="text-[10px] text-muted-foreground">{t("cam.ai_killswitch")}</span>
              </label>
            </div>

            {/* v0.3 · Config IA modulaire — 50 plugins activables individuellement */}
            {form.detect_enabled && (
              <div className="col-span-2">
                <CameraPluginsConfig
                  value={form.enabled_plugins}
                  onChange={(next) => setForm({ ...form, enabled_plugins: next })}
                />
              </div>
            )}

            {/* v3.9.1 · Les sélecteurs « Transport RTSP » (TCP/UDP) et « Codec
                préféré » ont été retirés : ils n'avaient plus aucun effet réel
                sur le pipeline. Le transport est forcé en TCP partout —
                `recorder.py` et `frame_source.py` passent `-rtsp_transport tcp`
                en dur, et go2rtc pull ses sources via `ffmpeg:` qui impose TCP
                également. Quant au codec, il est imposé par la caméra : le live
                prend le sous-flux (H264, seul transportable par WebRTC vers un
                navigateur) et l'enregistrement copie le flux natif sans le
                réencoder (`-c copy`). Ces deux réglages ne pouvaient donc que
                donner l'illusion d'un choix. Les valeurs par défaut (tcp/auto)
                restent envoyées au backend, rien ne change côté API. */}
            <div className="col-span-2 grid grid-cols-1 gap-3 border border-border p-3 bg-secondary/30">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Analyse IA</div>
              <div>
                {/* v3.1.1 · Résolution envoyée à YOLO/ANPR uniquement — l'enregistrement
                    est toujours natif (recorder.py fait `-c copy`, jamais concerné). */}
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                  Résolution IA / ANPR
                </label>
                <select
                  value={form.ai_resolution}
                  onChange={(e) => setForm({ ...form, ai_resolution: e.target.value })}
                  className="inp"
                  data-testid="ai-resolution-select"
                >
                  <option value="720p">{t("cam.ai_res_720")}</option>
                  <option value="1080p">{t("cam.ai_res_1080")}</option>
                  <option value="native">{t("cam.ai_res_native")}</option>
                </select>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Le scan continu (détection véhicule) tourne toujours en résolution légère, quel que
                  soit ce réglage — pas d&apos;impact sur la fluidité du live. Au-dessus de 720p, une image
                  haute résolution est récupérée UNIQUEMENT au moment où un véhicule est détecté, pour
                  générer des crops (véhicule/plaque) nets. N&apos;affecte pas l&apos;enregistrement (toujours
                  natif). &laquo; Native &raquo; nécessite que la résolution ait déjà été détectée
                  ci-dessus (bouton Tester la connexion).
                </p>
              </div>
              {/* v3.9.1 · Sélecteur « Mode vidéo » retiré : « Direct RTSP »
                  ouvrait une connexion ffmpeg PAR visionnage, là où le mode
                  Go2RTC n'en ouvre qu'une seule, partagée. C'était un mode de
                  dépannage historique, devenu contre-productif depuis le
                  passage au passthrough WebRTC — et coûteux sur les caméras
                  qui n'acceptent que quelques sessions RTSP simultanées.
                  `stream_mode` reste envoyé à "auto" par défaut, et le backend
                  continue d'honorer "direct_rtsp" pour les caméras existantes
                  qui l'auraient déjà en base (aucune migration nécessaire). */}
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
                      <option value="ai">{t("cam.rec_ai_event")}</option>
                      <option value="off">{t("cam.rec_off")}</option>
                    </select>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{t("cam.rec_mode_hint")}</p>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Canal ONVIF (profil)</label>
                    <select value={form.profile_token} onChange={(e) => setForm({ ...form, profile_token: e.target.value })} className="inp" disabled={profiles.length === 0} data-testid="record-profile">
                      <option value="">{t("cam.default_main")}</option>
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
                    <input type="number" min="0" value={form.storage_max_size_gb} onChange={(e) => setForm({ ...form, storage_max_size_gb: e.target.value })} className="inp mono" placeholder={t("cam.quota_ph")} data-testid="record-quota" />
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
              {form.mode === "onvif" && (
                <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <input type="checkbox" checked={testNtp} onChange={(e) => setTestNtp(e.target.checked)} data-testid="conn-test-ntp-checkbox" />
                  Tester aussi l'API NTP (vérifie la bonne API selon le constructeur — Reolink natif / ONVIF)
                </label>
              )}
              {!connCheck && <p className="text-muted-foreground text-[11px]">{t("cam.test_hint")}</p>}
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
                          <span className="ml-2 text-[#00E676]">{t("cam.url_validated")}</span>
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
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("cam.video_preview")}</div>
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
            {editingId && form.mode === "onvif" && (
              <button
                onClick={async () => {
                  setSettingNtp(true);
                  try {
                    await api.post(`/cameras/${editingId}/ntp`, { ntp_server: window.location.hostname });
                    toast.success("Serveur de temps défini — MG-VMS resynchronisera cette caméra automatiquement toutes les 24h");
                  } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
                  finally { setSettingNtp(false); }
                }}
                disabled={settingNtp} data-testid="cam-form-set-ntp"
                title="Définit MG-VMS comme source d'heure (NTP) de cette caméra"
                className="px-4 py-2 border border-border text-sm hover:bg-secondary flex items-center gap-2">
                {settingNtp ? <Loader2 size={15} className="animate-spin" /> : <Clock size={15} />} Définir comme serveur de temps
              </button>
            )}
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

      <OnvifDiscovery open={discOpen} onClose={() => setDiscOpen(false)}
        onPick={(dev) => { setEditingId(null); setForm({ ...EMPTY_FORM, ip: dev.ip, onvif_port: dev.port || 80, mode: "onvif", protocol: "ONVIF" }); setDiscOpen(false); setOpen(true); }} />
      {diagState && <DiagnosticDialog state={diagState} onClose={() => setDiagState(null)} onRefresh={() => openDiagnostic(diagState.cam)} />}
      {pipelineDiag && <PipelineDiagnosticDialog state={pipelineDiag} onClose={() => setPipelineDiag(null)} onRefresh={() => openPipelineDiagnostic(pipelineDiag.cam)} />}
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function PipelineDiagnosticDialog({ state, onClose, onRefresh }) {
  const { t } = useApp();
  const { cam, loading, steps, verdict, stream_mode, stream_name, go2rtc_url } = state;
  const [refreshing, setRefreshing] = useState(false);
  const doRefresh = async () => {
    setRefreshing(true);
    try { await onRefresh?.(); } finally { setRefreshing(false); }
  };
  const badge = (s) => {
    const map = {
      PASS: { bg: "bg-[#00E676]/15", fg: "text-[#00E676]", border: "border-[#00E676]/40", icon: <CheckCircle2 size={12} /> },
      FAIL: { bg: "bg-[#FF3333]/15", fg: "text-[#FF3333]", border: "border-[#FF3333]/40", icon: <XCircle size={12} /> },
      WARN: { bg: "bg-[#FFB800]/15", fg: "text-[#FFB800]", border: "border-[#FFB800]/40", icon: <AlertTriangle size={12} /> },
      SKIP: { bg: "bg-secondary", fg: "text-muted-foreground", border: "border-border", icon: null },
    }[s] || { bg: "bg-secondary", fg: "text-muted-foreground", border: "border-border", icon: null };
    return (
      <span className={`inline-flex items-center gap-1 text-[10px] mono uppercase tracking-wider px-2 py-0.5 border ${map.bg} ${map.fg} ${map.border}`}>
        {map.icon} {s}
      </span>
    );
  };
  const verdictColor = verdict === "PASS" ? "text-[#00E676]" : verdict === "WARN" ? "text-[#FFB800]" : "text-[#FF3333]";

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none border-border max-w-3xl" data-testid="pipeline-diag-dialog">
        <DialogHeader>
          <DialogTitle className="font-head flex items-center gap-2">
            <Stethoscope size={18} /> Diagnostic pipeline vidéo — {cam?.name}
          </DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="flex items-center gap-2 py-6 text-muted-foreground"><Loader2 size={18} className="animate-spin" /> {t("cam.probing")}</div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="border border-border p-2">
                <div className="text-[10px] uppercase text-muted-foreground">Verdict global</div>
                <div className={`text-lg font-bold ${verdictColor}`} data-testid="pipeline-diag-verdict">{verdict}</div>
              </div>
              <div className="border border-border p-2">
                <div className="text-[10px] uppercase text-muted-foreground">Stream Mode</div>
                <div className="mono text-sm">{stream_mode}</div>
              </div>
              <div className="border border-border p-2">
                <div className="text-[10px] uppercase text-muted-foreground">Nom stream Go2RTC</div>
                <div className="mono text-xs truncate" title={stream_name}>{stream_name}</div>
              </div>
            </div>
            <div className="border border-border">
              {(steps || []).map((s, i) => (
                <div key={s.step} className={`p-3 ${i < steps.length - 1 ? "border-b border-border" : ""}`} data-testid={`pipeline-diag-step-${s.step}`}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] mono text-muted-foreground w-4">{i + 1}.</span>
                      <span className="text-sm font-medium mono">{s.step}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {s.latency_ms != null && <span className="text-[10px] mono text-muted-foreground">{s.latency_ms} ms</span>}
                      {badge(s.status)}
                    </div>
                  </div>
                  {s.detail && <div className="text-xs text-muted-foreground pl-6">{s.detail}</div>}
                  {s.data && Object.keys(s.data).length > 0 && (
                    <details className="pl-6 mt-1">
                      <summary className="text-[10px] mono text-muted-foreground cursor-pointer hover:text-foreground">{t("cam.tech_details")}</summary>
                      <pre className="text-[10px] mono text-muted-foreground mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap">{JSON.stringify(s.data, null, 2)}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
            <div className="text-[10px] text-muted-foreground mono">Go2RTC URL: {go2rtc_url}</div>
          </div>
        )}
        <DialogFooter>
          <button onClick={doRefresh} disabled={refreshing || loading} className="text-xs px-3 py-1.5 border border-border hover:bg-secondary flex items-center gap-1" data-testid="pipeline-diag-refresh">
            {refreshing ? <Loader2 size={12} className="animate-spin" /> : <Activity size={12} />} Relancer
          </button>
          <button onClick={onClose} className="text-xs px-3 py-1.5 border border-border hover:bg-secondary" data-testid="pipeline-diag-close">Fermer</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DiagnosticDialog({ state, onClose, onRefresh }) {
  const { t } = useApp();
  const { cam, loading, camera, flux, ai, stats_24h, last_event, last_plate } = state;
  const ok = (v) => v ? <CheckCircle2 size={13} className="text-[#00E676]" /> : <XCircle size={13} className="text-[#FF3333]" />;
  const [refreshing, setRefreshing] = useState(false);
  const forceRegister = async () => {
    setRefreshing(true);
    try {
      await api.post(`/cameras/${cam.id}/refresh-stream`);
      toast.success("Flux ré-enregistré dans go2rtc — variantes HD/SD recréées");
      onRefresh?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec du ré-enregistrement du flux");
    } finally { setRefreshing(false); }
  };
  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl" data-testid="diagnostic-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Radar size={16} className="text-[#00E676]" /> Diagnostic — {cam?.name}</DialogTitle>
        </DialogHeader>
        {loading ? <div className="py-8 text-center text-muted-foreground"><Loader2 size={20} className="animate-spin inline mr-2" /> {t("cam.loading")}</div> : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <section className="border border-border p-3">
              <div className="font-head font-semibold mb-2">{t("cam.video_stream")}</div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">{ok(flux?.camera_online)} <span className="text-xs">Caméra {camera?.status?.toUpperCase()}</span></div>
                <div className="flex items-center gap-2">{ok(flux?.go2rtc_registered)} <span className="text-xs">{t("cam.g2r_source")}</span></div>
                <div className="flex items-center gap-2">{ok(flux?.go2rtc_hd_registered)} <span className="text-xs">{t("cam.g2r_variant")}<b>HD</b>{t("cam.native_res")}</span></div>
                <div className="flex items-center gap-2">{ok(flux?.go2rtc_sd_registered)} <span className="text-xs">{t("cam.g2r_variant")}<b>SD</b> (640 px)</span></div>
                <div className="text-xs text-muted-foreground mono">Fabricant : <b className="text-foreground">{camera?.manufacturer || "—"}</b> · Modèle : <b className="text-foreground">{camera?.model || "—"}</b></div>
                <div className="text-xs text-muted-foreground mono">Profil : <b className="text-foreground">{camera?.profile_name || camera?.profile_token || "—"}</b></div>
                <div className="text-xs text-muted-foreground mono">Transport : <b>{(flux?.rtsp_transport_used || "tcp").toUpperCase()}</b> · Codec : <b>{(camera?.codec || "auto").toUpperCase()}</b></div>
                <div className="text-xs text-muted-foreground mono">Résolution source : {camera?.resolution || "—"}{camera?.fps ? ` @ ${camera.fps} FPS` : ""}</div>
                {(() => {
                  const [w, h] = (camera?.resolution || "").split(/x/i).map((n) => parseInt(n, 10) || 0);
                  if (w > 0 && h > 0 && (w < 1280 || h < 720)) {
                    return (
                      <div className="text-[11px] text-[#FFB800] mt-1 p-1.5 border border-[#FFB800]/40 bg-[#FFB800]/10" data-testid="substream-warning">
                        ⚠ <b>{t("cam.substream_detected")}</b> ({camera.resolution}) — la caméra utilise probablement le profil <i>sub</i>. Fermez ce diagnostic, cliquez sur « Modifier » et re-cochez le profil <b>MAIN</b> (résolution &ge; 1280×720).
                      </div>
                    );
                  }
                  return null;
                })()}
                {camera?.rtsp_url_masked && <div className="text-[10px] text-muted-foreground mono truncate" title={camera.rtsp_url_masked}>URL RTSP : {camera.rtsp_url_masked}</div>}
                {(!flux?.go2rtc_hd_registered || !flux?.go2rtc_sd_registered) && (
                  <div className="text-[11px] text-[#FFB800] mt-1">
                    ⚠ Variantes HD/SD manquantes dans go2rtc. Cliquez sur « Ré-enregistrer le flux » ci-dessous.
                  </div>
                )}
              </div>
              <div className="mt-2 pt-2 border-t border-border">
                <button onClick={forceRegister} disabled={refreshing}
                        className="text-xs px-2.5 py-1.5 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF] hover:text-white flex items-center gap-1"
                        data-testid="stream-force-register">
                  {refreshing ? <Loader2 size={12} className="animate-spin" /> : <Radar size={12} />}
                  Ré-enregistrer le flux (HD + SD)
                </button>
              </div>
            </section>
            <section className="border border-border p-3">
              <div className="font-head font-semibold mb-2">Intelligence artificielle</div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">{ok(ai?.detect_enabled)} <span className="text-xs">Détection IA {ai?.detect_enabled ? "active" : "désactivée"}</span></div>
                <div className="text-xs text-muted-foreground mono">Dernière analyse : {ai?.last_analysis_at ? new Date(ai.last_analysis_at).toLocaleTimeString() : "—"}</div>
                <div className="text-xs text-muted-foreground mono">YOLO : {ai?.last_yolo_ms ? `${ai.last_yolo_ms} ms` : "—"} · ALPR : {ai?.last_alpr_ms ? `${ai.last_alpr_ms} ms` : "—"}</div>
                <div className="text-xs text-muted-foreground mono">Mouvement : {ai?.motion_pct != null ? `${ai.motion_pct.toFixed(1)} %` : "—"}</div>
                <div className="text-xs text-muted-foreground mono">{t("cam.last_frame_det")}<b className="text-foreground">{ai?.last_detections_count || 0}</b></div>
              </div>
            </section>
            <section className="border border-border p-3 md:col-span-2">
              <div className="font-head font-semibold mb-2">{t("cam.activity_24h")}</div>
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
  const { t } = useApp();
  // ─────────────── State ───────────────
  const [phase, setPhase] = useState("config"); // config | scanning | done
  const [interfaces, setInterfaces] = useState([]);
  const [selected, setSelected] = useState({}); // {ifname: true}
  const [showVirtual, setShowVirtual] = useState(false);
  const [customCidrs, setCustomCidrs] = useState([""]);
  const [logs, setLogs] = useState([]); // [{time, line}]
  const [progress, setProgress] = useState({ tested: 0, total: 0, percent: 0, elapsed_sec: 0, eta_sec: 0 });
  const [devices, setDevices] = useState([]); // caméras
  const [others, setOthers] = useState([]);   // équipements non-caméras
  const [summary, setSummary] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const [error, setError] = useState("");
  const consoleRef = React.useRef(null);
  const esRef = React.useRef(null);

  // ─────────────── Load interfaces on open ───────────────
  useEffect(() => {
    if (!open) return;
    resetAll();
    (async () => {
      try {
        const { data } = await api.get("/discovery/interfaces");
        setInterfaces(data.interfaces || []);
        // Sélectionne par défaut les physiques 'up' avec CIDR /16 à /30
        const pre = {};
        (data.interfaces || []).forEach((i) => {
          if (!i.virtual && i.state === "up" && i.cidr) {
            const mask = parseInt(i.cidr.split("/")[1] || "0", 10);
            if (mask >= 16 && mask <= 30) pre[i.name] = true;
          }
        });
        setSelected(pre);
      } catch (e) {
        setError("Impossible de récupérer les interfaces réseau");
      }
    })();
    return () => { cleanupStream(); };
  }, [open]);

  useEffect(() => {
    // Auto-scroll console.
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [logs]);

  const resetAll = () => {
    setPhase("config"); setLogs([]); setDevices([]); setOthers([]);
    setSummary(null); setTaskId(null); setError(""); setProgress({ tested: 0, total: 0, percent: 0, elapsed_sec: 0, eta_sec: 0 });
  };

  const cleanupStream = () => {
    if (esRef.current) { try { esRef.current.close(); } catch (_) {/* ignore */} esRef.current = null; }
  };

  const visibleIfaces = interfaces.filter((i) => showVirtual || !i.virtual);

  // ─────────────── Start scan ───────────────
  const startScan = async () => {
    const nets = [];
    interfaces.forEach((i) => { if (selected[i.name] && i.cidr) nets.push(i.cidr); });
    customCidrs.forEach((c) => { const v = c.trim(); if (v) nets.push(v); });
    if (nets.length === 0) { toast.error("Sélectionnez au moins un réseau"); return; }

    resetAll();
    setPhase("scanning");
    setLogs([{ time: hms(), line: "Preparing scan..." }]);

    try {
      const ifNames = interfaces.filter((i) => selected[i.name]).map((i) => i.name);
      const { data } = await api.post("/discovery/start", {
        networks: nets, interfaces: ifNames, max_hosts_per_network: 256,
      });
      setTaskId(data.task_id);
      openStream(data.task_id);
    } catch (e) {
      setError("Échec démarrage : " + (e?.response?.data?.detail || e.message));
      setPhase("config");
    }
  };

  // ─────────────── SSE stream ───────────────
  const openStream = (tid) => {
    const token = localStorage.getItem("mg_token");
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/discovery/${tid}/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;

    const pushLog = (time, line) => setLogs((prev) => [...prev, { time, line }]);

    es.addEventListener("hello", () => { pushLog(hms(), "Connected to scan stream."); });
    es.addEventListener("log", (ev) => {
      try { const d = JSON.parse(ev.data); pushLog(d.time || hms(), d.line); } catch (_) {/* ignore */}
    });
    es.addEventListener("progress", (ev) => {
      try { setProgress(JSON.parse(ev.data)); } catch (_) {/* ignore */}
    });
    es.addEventListener("device", (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d.type === "camera") setDevices((prev) => [...prev, d]);
        else setOthers((prev) => [...prev, d]);
      } catch (_) {/* ignore */}
    });
    es.addEventListener("summary", (ev) => {
      try { setSummary(JSON.parse(ev.data)); } catch (_) {/* ignore */}
    });
    es.addEventListener("done", () => {
      setPhase("done"); cleanupStream();
    });
    es.onerror = () => {
      // Le stream se ferme naturellement en fin — ne pas afficher d'erreur si done.
      if (phase === "scanning") pushLog(hms(), "Stream error / disconnected.");
    };
  };

  // ─────────────── Cancel ───────────────
  const cancelScan = async () => {
    if (!taskId) return;
    try {
      await api.post(`/discovery/${taskId}/cancel`);
      setLogs((prev) => [...prev, { time: hms(), line: "Cancellation requested..." }]);
    } catch (_) {/* ignore */}
  };

  // ─────────────── Export logs ───────────────
  const logText = () => logs.map((l) => `[${l.time}] ${l.line}`).join("\n");
  const copyLog = async () => {
    try { await navigator.clipboard.writeText(logText()); toast.success("Journal copié"); }
    catch (_) { toast.error("Échec de la copie"); }
  };
  const clearLog = () => setLogs([]);
  const downloadLog = (ext) => {
    const blob = new Blob([logText()], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url;
    a.download = `mgvms-discovery-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.${ext}`;
    a.click(); URL.revokeObjectURL(url);
  };

  // ─────────────── Custom CIDR helpers ───────────────
  const updCidr = (i, v) => setCustomCidrs((prev) => prev.map((c, k) => (k === i ? v : c)));
  const addCidr = () => setCustomCidrs((prev) => [...prev, ""]);
  const rmCidr = (i) => setCustomCidrs((prev) => prev.filter((_, k) => k !== i));

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { cleanupStream(); onClose(); } }}>
      <DialogContent className="rounded-none border-border max-w-4xl" data-testid="onvif-discover-dialog">
        <DialogHeader>
          <DialogTitle className="font-head flex items-center gap-2">
            <Radar size={18} /> Assistant de découverte réseau
          </DialogTitle>
        </DialogHeader>

        {/* ═══════════════ Phase 1 : Configuration ═══════════════ */}
        {phase === "config" && (
          <div className="space-y-3 max-h-[70vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">{t("disc.select_hint")}</p>
              <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="show-virtual-toggle">
                <input type="checkbox" checked={showVirtual} onChange={(e) => setShowVirtual(e.target.checked)} />
                Afficher les interfaces virtuelles
              </label>
            </div>

            {/* Interfaces */}
            <div className="border border-border">
              <div className="grid grid-cols-[24px_1fr_140px_140px_100px_70px] gap-2 px-3 py-2 bg-muted text-[10px] uppercase tracking-widest text-muted-foreground border-b border-border">
                <div></div><div>Interface</div><div>Adresse / CIDR</div><div>Passerelle</div><div>Vitesse</div><div>{t("disc.state")}</div>
              </div>
              {visibleIfaces.length === 0 && <div className="p-3 text-sm text-muted-foreground">{t("disc.no_iface")}</div>}
              {visibleIfaces.map((i) => (
                <label key={i.name} className={`grid grid-cols-[24px_1fr_140px_140px_100px_70px] gap-2 items-center px-3 py-2 border-b border-border last:border-0 cursor-pointer hover:bg-secondary/50 ${i.virtual ? "opacity-60" : ""}`} data-testid={`iface-row-${i.name}`}>
                  <input type="checkbox" checked={!!selected[i.name]} onChange={(e) => setSelected((s) => ({ ...s, [i.name]: e.target.checked }))} disabled={!i.cidr} />
                  <div className="text-sm font-mono flex items-center gap-2">
                    <span>{i.name}</span>
                    {i.virtual && <span className="text-[9px] px-1 border border-border text-muted-foreground">virtual</span>}
                  </div>
                  <div className="text-xs font-mono">{i.cidr || i.ip}</div>
                  <div className="text-xs font-mono text-muted-foreground">{i.gateway || "—"}</div>
                  <div className="text-xs font-mono text-muted-foreground">{i.speed_mbps ? `${i.speed_mbps} Mb/s` : "—"}</div>
                  <div className={`text-xs font-mono ${i.state === "up" ? "text-[#00CC66]" : "text-muted-foreground"}`}>{i.state}</div>
                </label>
              ))}
            </div>

            {/* Custom networks */}
            <div className="border border-border p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{t("disc.custom_nets")}</div>
                <button onClick={addCidr} className="text-[11px] px-2 py-1 border border-border hover:bg-secondary" data-testid="add-custom-cidr">+ Ajouter</button>
              </div>
              {customCidrs.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input value={c} onChange={(e) => updCidr(i, e.target.value)} placeholder="192.168.50.0/24"
                    className="inp font-mono text-sm flex-1" data-testid={`custom-cidr-${i}`} />
                  {customCidrs.length > 1 && <button onClick={() => rmCidr(i)} className="px-2 py-1 border border-border text-xs hover:bg-secondary">−</button>}
                </div>
              ))}
            </div>

            {error && <p className="text-xs text-[#FF4C4C] border border-[#FF4C4C]/40 bg-[#FF4C4C]/10 p-2">{error}</p>}
          </div>
        )}

        {/* ═══════════════ Phase 2/3 : Console ═══════════════ */}
        {(phase === "scanning" || phase === "done") && (
          <div className="space-y-3">
            {/* Progress bar */}
            <div className="grid grid-cols-4 gap-3 text-xs">
              <div className="border border-border p-2"><div className="text-[10px] uppercase tracking-widest text-muted-foreground">{t("disc.tested")}</div><div className="font-mono text-sm">{progress.tested} / {progress.total || "?"}</div></div>
              <div className="border border-border p-2"><div className="text-[10px] uppercase tracking-widest text-muted-foreground">{t("disc.cameras")}</div><div className="font-mono text-sm text-[#00CC66]">{devices.length}</div></div>
              <div className="border border-border p-2"><div className="text-[10px] uppercase tracking-widest text-muted-foreground">{t("disc.elapsed")}</div><div className="font-mono text-sm">{progress.elapsed_sec}s</div></div>
              <div className="border border-border p-2"><div className="text-[10px] uppercase tracking-widest text-muted-foreground">Restant</div><div className="font-mono text-sm">{phase === "done" ? "—" : `${progress.eta_sec}s`}</div></div>
            </div>
            <div className="h-2 bg-muted relative overflow-hidden border border-border">
              <div className="h-full bg-[#0044FF] transition-all" style={{ width: `${Math.min(progress.percent, 100)}%` }} data-testid="scan-progress-bar" />
            </div>

            {/* Console */}
            <div ref={consoleRef} className="bg-black text-[#4bff4b] font-mono text-[11px] p-3 h-[300px] overflow-y-auto border border-border" data-testid="scan-console">
              {logs.map((l, i) => (
                <div key={i}><span className="text-[#6d6d6d]">[{l.time}]</span> <span className={l.line.includes("Camera detected") ? "text-white" : ""}>{l.line}</span></div>
              ))}
              {phase === "scanning" && <div className="text-[#4bff4b] animate-pulse">▋</div>}
            </div>

            {/* Console actions */}
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <button onClick={copyLog} className="px-2 py-1 border border-border hover:bg-secondary" data-testid="log-copy">Copier</button>
              <button onClick={clearLog} className="px-2 py-1 border border-border hover:bg-secondary" data-testid="log-clear">Vider</button>
              <button onClick={() => downloadLog("txt")} className="px-2 py-1 border border-border hover:bg-secondary" data-testid="log-save-txt">Sauver .txt</button>
              <button onClick={() => downloadLog("log")} className="px-2 py-1 border border-border hover:bg-secondary" data-testid="log-save-log">Sauver .log</button>
              <div className="flex-1" />
              {phase === "scanning" && <button onClick={cancelScan} className="px-3 py-1 border border-[#FF4C4C]/40 text-[#FF4C4C] hover:bg-[#FF4C4C]/10" data-testid="cancel-scan-btn">Annuler le scan</button>}
            </div>

            {/* Summary */}
            {phase === "done" && summary && (
              <div className="border border-border p-3 text-xs space-y-1" data-testid="scan-summary">
                <div className="font-semibold text-sm uppercase tracking-widest mb-1">{t("disc.summary")}</div>
                <div>{t("disc.ifaces_scanned")}<span className="font-mono">{summary.interfaces_scanned}</span></div>
                <div>{t("disc.addr_tested")}<span className="font-mono">{summary.addresses_tested}</span></div>
                <div>{t("disc.cams_found")}<span className="font-mono text-[#00CC66]">{summary.cameras_found}</span> (ONVIF : {summary.onvif_count})</div>
                {Object.entries(summary.by_manufacturer || {}).map(([k, v]) => (<div key={k} className="pl-3 text-muted-foreground">• {k} : {v}</div>))}
                <div>{t("disc.non_cams")}<span className="font-mono">{summary.other_devices_found}</span></div>
                <div>Erreurs : <span className="font-mono">{summary.errors}</span></div>
                <div>{t("disc.duration")}<span className="font-mono">{summary.elapsed_sec}s</span> · Statut : <span className="font-mono">{summary.status}</span></div>
              </div>
            )}

            {/* Devices found */}
            {phase === "done" && devices.length > 0 && (
              <div className="border border-border" data-testid="scan-devices-cameras">
                <div className="px-3 py-2 bg-muted text-[10px] uppercase tracking-widest text-muted-foreground border-b border-border">{t("disc.cams_found_title")}</div>
                {devices.map((d, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 border-b border-border last:border-0">
                    <div className="flex items-center gap-3 text-xs">
                      <span className="font-mono">{d.ip}</span>
                      <span>{d.manufacturer || "ONVIF"}</span>
                      {d.model && <span className="text-muted-foreground">{d.model}</span>}
                      {d.onvif && <span className="text-[9px] px-1 border border-[#00CC66]/40 text-[#00CC66]">ONVIF</span>}
                      {d.auth_required && <span className="text-[9px] px-1 border border-[#FFB800]/40 text-[#FFB800]">auth</span>}
                      {d.already_added && <span className="text-[9px] px-1 border border-border text-muted-foreground">{t("disc.already_added")}</span>}
                    </div>
                    <button onClick={() => onPick({ ip: d.ip, port: d.onvif_port || 80 })} className="px-3 py-1 bg-[#0044FF] text-white text-xs" data-testid={`pick-device-${d.ip}`}>Utiliser cette IP</button>
                  </div>
                ))}
              </div>
            )}
            {phase === "done" && others.length > 0 && (
              <div className="border border-border" data-testid="scan-devices-others">
                <div className="px-3 py-2 bg-muted text-[10px] uppercase tracking-widest text-muted-foreground border-b border-border">{t("disc.other_devices")}</div>
                {others.map((d, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-2 border-b border-border last:border-0 text-xs opacity-70">
                    <span className="font-mono">{d.ip}</span>
                    <span>{d.manufacturer || "Unknown"}</span>
                    <span className="text-muted-foreground">{t("disc.not_compatible")}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <DialogFooter className="pt-3">
          {phase === "config" && (
            <>
              <button onClick={onClose} className="px-3 py-2 border border-border text-sm hover:bg-secondary">Fermer</button>
              <button onClick={startScan} className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2" data-testid="onvif-scan-btn">
                <Radar size={15} /> Lancer la découverte
              </button>
            </>
          )}
          {phase === "scanning" && (
            <button onClick={onClose} className="px-3 py-2 border border-border text-sm hover:bg-secondary">Masquer</button>
          )}
          {phase === "done" && (
            <>
              <button onClick={() => { resetAll(); }} className="px-3 py-2 border border-border text-sm hover:bg-secondary" data-testid="rescan-btn">Nouveau scan</button>
              <button onClick={onClose} className="px-3 py-2 bg-[#0044FF] text-white text-sm">Fermer</button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function hms() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
