import React, { useState, useEffect } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { toast } from "sonner";
import { Plus, Trash2, Edit2, Save, X, Play, MapPin, Loader2, RefreshCw, RotateCcw } from "lucide-react";

const EMPTY_ZONE = {
  name: "",
  camera_id: "",
  enabled: true,
  polygon: [],
  detect: { classes: [], min_confidence: 0.5, min_dwell_seconds: 0, cooldown_seconds: 60 },
  trigger_on: ["enter"],
  actions: [],
};

export default function SmartZones() {
  const { t } = useApp();
  const [zones, setZones] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [actuatorTypes, setActuatorTypes] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [z, c, a] = await Promise.all([
        api.get("/smart-zones"),
        api.get("/cameras"),
        api.get("/smart-zones/actuators/available"),
      ]);
      setZones(z.data.zones || []);
      setCameras(c.data || []);
      setActuatorTypes(a.data.actuators || []);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadAll(); }, []);

  const startEdit = (z) => setEditing(z ? { ...z, detect: { ...z.detect } } : { ...EMPTY_ZONE, camera_id: cameras[0]?.id || "" });

  const save = async () => {
    if (!editing.name || !editing.camera_id) {
      toast.error("Nom et caméra requis");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: editing.name,
        camera_id: editing.camera_id,
        enabled: editing.enabled,
        polygon: editing.polygon || [],
        detect: editing.detect,
        trigger_on: editing.trigger_on,
        actions: editing.actions || [],
      };
      if (editing.id) {
        await api.put(`/smart-zones/${editing.id}`, payload);
        toast.success("Zone mise à jour");
      } else {
        await api.post("/smart-zones", payload);
        toast.success("Zone créée");
      }
      setEditing(null);
      loadAll();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setSaving(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("Supprimer cette zone ?")) return;
    try {
      await api.delete(`/smart-zones/${id}`);
      toast.success("Zone supprimée");
      loadAll();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
  };

  const testAction = async (zoneId, idx) => {
    try {
      const { data } = await api.post(`/smart-zones/${zoneId}/test-action/${idx}`);
      const ok = data.result?.ok;
      toast[ok ? "success" : "error"](`Action ${data.result?.type} → ${ok ? "OK" : (data.result?.error || "échec")}`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
  };

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto" data-testid="smart-zones-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-head font-bold text-2xl flex items-center gap-2">
            <MapPin size={22} className="text-[#00E676]" /> Smart Zones
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Zones intelligentes : détecter · mesurer · déclencher (webhook, MQTT, Home Assistant, Tuya, plugins, TTS)
          </p>
        </div>
        <button
          onClick={() => startEdit(null)}
          data-testid="zone-create-btn"
          className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0044FF]/90"
        >
          <Plus size={14} /> Nouvelle zone
        </button>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-12">
          <Loader2 size={20} className="animate-spin inline mr-2" /> Chargement…
        </div>
      ) : zones.length === 0 ? (
        <div className="border border-dashed border-border p-8 text-center text-muted-foreground text-sm">
          Aucune zone configurée. Cliquez sur &quot;Nouvelle zone&quot; pour commencer.
        </div>
      ) : (
        <div className="space-y-2" data-testid="zones-list">
          {zones.map((z) => {
            const cam = cameras.find((c) => c.id === z.camera_id);
            return (
              <div key={z.id} className="border border-border p-3 flex items-start gap-3 bg-card"
                   data-testid={`zone-row-${z.id}`}>
                <div className="w-1.5 h-full self-stretch" style={{ background: z.enabled ? "#00E676" : "#FF3333" }} />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold flex items-center gap-2">
                    {z.name}
                    <span className="text-[10px] mono text-muted-foreground">· {cam?.name || z.camera_id}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mono mt-1 flex flex-wrap gap-x-3">
                    <span>classes: {z.detect?.classes?.join(",") || "—"}</span>
                    <span>triggers: {z.trigger_on?.join(",") || "—"}</span>
                    <span>actions: {(z.actions || []).length}</span>
                    <span>déclenchée: {z.trigger_count || 0}×</span>
                  </div>
                  {(z.actions || []).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {z.actions.map((a, i) => (
                        <button key={i} onClick={() => testAction(z.id, i)}
                                data-testid={`zone-${z.id}-action-${i}-test`}
                                className="flex items-center gap-1 px-1.5 py-0.5 border border-border text-[10px] mono hover:bg-secondary">
                          <Play size={9} /> {a.type}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex gap-1">
                  <button onClick={() => startEdit(z)}
                          data-testid={`zone-${z.id}-edit`}
                          className="p-1.5 border border-border hover:bg-secondary text-xs">
                    <Edit2 size={11} />
                  </button>
                  <button onClick={() => remove(z.id)}
                          data-testid={`zone-${z.id}-delete`}
                          className="p-1.5 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10 text-xs">
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {editing && (
        <ZoneEditor
          zone={editing}
          cameras={cameras}
          actuatorTypes={actuatorTypes}
          onChange={setEditing}
          onSave={save}
          onCancel={() => setEditing(null)}
          saving={saving}
        />
      )}
    </div>
  );
}


function ZoneEditor({ zone, cameras, actuatorTypes, onChange, onSave, onCancel, saving }) {
  const update = (patch) => onChange({ ...zone, ...patch });
  const updateDetect = (patch) => onChange({ ...zone, detect: { ...zone.detect, ...patch } });

  const addAction = (type) => {
    onChange({ ...zone, actions: [...(zone.actions || []), { type, config: {} }] });
  };
  const updateAction = (idx, cfg) => {
    const arr = [...(zone.actions || [])];
    arr[idx] = { ...arr[idx], config: cfg };
    onChange({ ...zone, actions: arr });
  };
  const removeAction = (idx) => {
    onChange({ ...zone, actions: (zone.actions || []).filter((_, i) => i !== idx) });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
         onClick={onCancel}
         data-testid="zone-editor-modal">
      <div className="bg-card border border-border max-w-2xl w-full max-h-[90vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-card">
          <div className="font-head font-semibold">
            {zone.id ? "Modifier" : "Nouvelle"} zone intelligente
          </div>
          <button onClick={onCancel} data-testid="zone-editor-close"><X size={16} /></button>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Nom</label>
              <input value={zone.name} onChange={(e) => update({ name: e.target.value })}
                     data-testid="zone-name-input"
                     className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Caméra</label>
              <select value={zone.camera_id} onChange={(e) => update({ camera_id: e.target.value })}
                      data-testid="zone-camera-select"
                      className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm">
                <option value="">— Sélectionner —</option>
                {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={zone.enabled}
                   onChange={(e) => update({ enabled: e.target.checked })}
                   data-testid="zone-enabled-toggle" />
            Zone active
          </label>

          <div className="border border-border p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Détection</div>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">
                  Classes (séparées par virgule — ex: person,car,plate:AB-123-CD)
                </label>
                <input
                  value={(zone.detect.classes || []).join(",")}
                  onChange={(e) => updateDetect({ classes: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })}
                  data-testid="zone-classes-input"
                  className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm mono"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Confidence min</label>
                  <input type="number" step="0.05" min="0" max="1"
                         value={zone.detect.min_confidence}
                         onChange={(e) => updateDetect({ min_confidence: parseFloat(e.target.value) })}
                         className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm mono" />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Dwell min (s)</label>
                  <input type="number" min="0"
                         value={zone.detect.min_dwell_seconds}
                         onChange={(e) => updateDetect({ min_dwell_seconds: parseInt(e.target.value || 0) })}
                         className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm mono" />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Cooldown (s)</label>
                  <input type="number" min="0"
                         value={zone.detect.cooldown_seconds}
                         onChange={(e) => updateDetect({ cooldown_seconds: parseInt(e.target.value || 0) })}
                         className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm mono" />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Déclencheurs</label>
                <div className="flex gap-3">
                  {["enter", "present", "exit"].map((k) => (
                    <label key={k} className="flex items-center gap-1 text-sm">
                      <input type="checkbox"
                             checked={(zone.trigger_on || []).includes(k)}
                             onChange={(e) => {
                               const set = new Set(zone.trigger_on || []);
                               e.target.checked ? set.add(k) : set.delete(k);
                               update({ trigger_on: Array.from(set) });
                             }}
                             data-testid={`zone-trigger-${k}`}
                      /> {k}
                    </label>
                  ))}
                </div>
              </div>
              <PolygonEditor
                cameraId={zone.camera_id}
                polygon={zone.polygon || []}
                onChange={(pg) => update({ polygon: pg })}
              />
            </div>
          </div>

          <div className="border border-border p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Actions</div>
              <select onChange={(e) => { if (e.target.value) { addAction(e.target.value); e.target.value = ""; } }}
                      data-testid="zone-add-action-select"
                      defaultValue=""
                      className="text-xs px-2 py-1 bg-background border border-input">
                <option value="">+ Ajouter action…</option>
                {actuatorTypes.map((a) => <option key={a.type} value={a.type}>{a.label}</option>)}
              </select>
            </div>
            {(zone.actions || []).length === 0 ? (
              <div className="text-xs text-muted-foreground py-2 text-center">Aucune action</div>
            ) : (
              <div className="space-y-2">
                {(zone.actions || []).map((a, i) => (
                  <div key={i} className="border border-border p-2" data-testid={`zone-action-${i}`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm mono font-semibold">{a.type}</div>
                      <button onClick={() => removeAction(i)}
                              data-testid={`zone-action-${i}-remove`}
                              className="text-[#FF3333] hover:opacity-80"><Trash2 size={12} /></button>
                    </div>
                    <textarea
                      value={JSON.stringify(a.config || {}, null, 2)}
                      onChange={(e) => {
                        try {
                          const cfg = JSON.parse(e.target.value || "{}");
                          updateAction(i, cfg);
                        } catch (_) { /* JSON invalide, garde valeur locale */ }
                      }}
                      data-testid={`zone-action-${i}-config`}
                      rows={5}
                      className="w-full px-2 py-1 bg-background border border-input outline-none text-xs mono"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border sticky bottom-0 bg-card">
          <button onClick={onCancel}
                  data-testid="zone-editor-cancel"
                  className="px-4 py-2 border border-border text-sm hover:bg-secondary">Annuler</button>
          <button onClick={onSave} disabled={saving}
                  data-testid="zone-editor-save"
                  className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}



function PolygonEditor({ cameraId, polygon, onChange }) {
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [imgSize, setImgSize] = useState({ w: 640, h: 360 });
  const canvasRef = React.useRef(null);
  const imgRef = React.useRef(null);
  const [refreshTick, setRefreshTick] = useState(0);

  // Fetch snapshot une fois par cameraId
  useEffect(() => {
    if (!cameraId) { setSnapshotUrl(null); return; }
    const base = process.env.REACT_APP_BACKEND_URL;
    const token = localStorage.getItem("mg_token") || "";
    setSnapshotUrl(`${base}/api/stream/${cameraId}/frame.jpeg?t=${Date.now()}&token=${encodeURIComponent(token)}`);
  }, [cameraId, refreshTick]);

  // Redessine le polygone
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!polygon || polygon.length === 0) return;
    ctx.strokeStyle = "#00E676";
    ctx.fillStyle = "rgba(0,230,118,0.15)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    polygon.forEach(([rx, ry], i) => {
      const x = rx * canvas.width;
      const y = ry * canvas.height;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (polygon.length >= 3) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
    // Dots
    polygon.forEach(([rx, ry], i) => {
      const x = rx * canvas.width;
      const y = ry * canvas.height;
      ctx.fillStyle = i === 0 ? "#FFB800" : "#00E676";
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
    });
  }, [polygon, imgSize]);

  const handleClick = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const rx = (e.clientX - rect.left) / rect.width;
    const ry = (e.clientY - rect.top) / rect.height;
    onChange([...(polygon || []), [+rx.toFixed(4), +ry.toFixed(4)]]);
  };

  const undo = () => onChange((polygon || []).slice(0, -1));
  const clear = () => onChange([]);

  if (!cameraId) {
    return (
      <div className="text-[11px] text-muted-foreground border border-dashed border-border p-3 text-center">
        Sélectionnez une caméra pour dessiner la zone
      </div>
    );
  }

  return (
    <div>
      <label className="text-xs text-muted-foreground block mb-1 flex items-center justify-between">
        <span>Polygone de la zone ({(polygon || []).length} points)</span>
        <span className="flex gap-2">
          <button type="button" onClick={() => setRefreshTick(t => t + 1)}
                  data-testid="poly-refresh-snapshot"
                  className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 border border-border hover:bg-secondary">
            <RefreshCw size={9} /> Rafraîchir
          </button>
          <button type="button" onClick={undo} disabled={(polygon || []).length === 0}
                  data-testid="poly-undo"
                  className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 border border-border hover:bg-secondary disabled:opacity-40">
            <RotateCcw size={9} /> Annuler
          </button>
          <button type="button" onClick={clear} disabled={(polygon || []).length === 0}
                  data-testid="poly-clear"
                  className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10 disabled:opacity-40">
            <Trash2 size={9} /> Effacer
          </button>
        </span>
      </label>
      <div className="relative border border-border bg-black" style={{ aspectRatio: "16 / 9" }}>
        {snapshotUrl && (
          <img ref={imgRef} src={snapshotUrl} alt="snapshot"
               onLoad={(e) => setImgSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
               onError={() => { /* silencieux */ }}
               data-testid="poly-snapshot"
               className="absolute inset-0 w-full h-full object-contain" />
        )}
        <canvas
          ref={canvasRef}
          width={640}
          height={360}
          onClick={handleClick}
          data-testid="poly-canvas"
          className="absolute inset-0 w-full h-full cursor-crosshair"
        />
      </div>
      <div className="text-[10px] text-muted-foreground mt-1 mono">
        Clique sur l&apos;image pour ajouter des points. Le premier point est jaune. Ferme automatiquement à partir de 3 points.
        {(polygon || []).length === 0 && <span className="ml-1 text-[#FFB800]">— zone vide = couvre tout le frame</span>}
      </div>
    </div>
  );
}
