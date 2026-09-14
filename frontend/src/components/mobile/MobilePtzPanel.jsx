/**
 * MobilePtzPanel — panneau PTZ complet pour la vue live mobile (v3.102).
 *
 * Remplace l'overlay plein écran v3.98 (démonté : "ça se superpose pas à
 * l'écran, rien devant la vue live" — référence app Reolink, dont le menu
 * PTZ s'ouvre DANS le cadre sous la vidéo, jamais par-dessus). Ce composant
 * est rendu INLINE par MobileLive.jsx, dans le panneau sous la vidéo — la
 * vidéo reste visible en permanence, jamais couverte.
 *
 * Ajoute Presets + Patrouille (demande explicite, "PDG" = presets +
 * "mode de patrouille") — mêmes endpoints que CameraCenter.jsx::PTZTab
 * desktop (GET/POST/DELETE .../ptz/presets, POST .../ptz/preset,
 * GET/PUT .../ptz/patrol), pas de nouvelle route backend.
 *
 * Portée volontairement réduite par rapport au desktop pour la patrouille :
 * bascule ON/OFF simple sur la liste de presets déjà enregistrés (vitesse/
 * temporisation par défaut) plutôt qu'un réglage fin — la configuration
 * détaillée reste sur la fiche caméra complète (onglet PTZ desktop,
 * accessible aussi depuis mobile via Centre caméras).
 */
import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import PtzPad from "@/components/mobile/PtzPad";
import { Plus, X as XIcon, RotateCw } from "lucide-react";

const DEFAULT_DWELL_SEC = 8;
const DEFAULT_SPEED = 0.5;

export default function MobilePtzPanel({ cameraId }) {
  const [presets, setPresets] = useState(null);
  const [patrol, setPatrol] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadPresets = () => {
    api.get(`/devices/${cameraId}/ptz/presets`).then((r) => setPresets(r.data.presets || [])).catch(() => setPresets([]));
  };
  const loadPatrol = () => {
    api.get(`/devices/${cameraId}/ptz/patrol`).then((r) => setPatrol({
      enabled: !!r.data.enabled, dwell_seconds: r.data.dwell_seconds || DEFAULT_DWELL_SEC,
      preset_ids: r.data.preset_ids || [], speed: r.data.speed || DEFAULT_SPEED,
    })).catch(() => setPatrol({ enabled: false, dwell_seconds: DEFAULT_DWELL_SEC, preset_ids: [], speed: DEFAULT_SPEED }));
  };
  useEffect(() => { loadPresets(); loadPatrol(); }, [cameraId]);

  const gotoPreset = (id) => {
    api.post(`/devices/${cameraId}/ptz/preset`, { id: String(id), speed: DEFAULT_SPEED })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Preset indisponible"));
  };

  const addPreset = () => {
    const name = window.prompt("Nom du preset (optionnel)", "");
    if (name === null) return;
    setBusy(true);
    api.post(`/devices/${cameraId}/ptz/presets`, { name: name.trim() || undefined })
       .then((r) => { toast.success(`Preset ajouté : ${r.data.name}`); loadPresets(); })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Échec de l'ajout"))
       .finally(() => setBusy(false));
  };

  const deletePreset = (preset) => {
    if (!window.confirm(`Supprimer le preset "${preset.name}" ?`)) return;
    api.delete(`/devices/${cameraId}/ptz/presets/${preset.id}`)
       .then(() => { toast.success("Preset supprimé"); loadPresets(); })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Échec de la suppression"));
  };

  const togglePatrol = () => {
    if (!patrol) return;
    const next = { ...patrol, enabled: !patrol.enabled, preset_ids: patrol.preset_ids.length ? patrol.preset_ids : (presets || []).map((p) => p.id) };
    setBusy(true);
    api.put(`/devices/${cameraId}/ptz/patrol`, {
      enabled: next.enabled, dwell_seconds: next.dwell_seconds, preset_ids: next.preset_ids, speed: next.speed,
    }).then((r) => setPatrol({ ...next, running: !!r.data.running }))
      .catch((e) => toast.error(e.response?.data?.detail?.message || "Échec patrouille"))
      .finally(() => setBusy(false));
  };

  return (
    <div className="p-3 flex flex-col items-center gap-4" data-testid="mobile-ptz-panel">
      <PtzPad cameraId={cameraId} />

      <div className="w-full">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Presets</span>
          <button onClick={addPreset} disabled={busy} data-testid="mobile-ptz-preset-add"
                  className="flex items-center gap-1 text-[10px] uppercase text-[#0044FF]">
            <Plus size={12} /> Ajouter
          </button>
        </div>
        {presets === null ? (
          <div className="text-xs text-muted-foreground">Chargement…</div>
        ) : presets.length === 0 ? (
          <div className="text-xs text-muted-foreground">Aucun preset enregistré</div>
        ) : (
          <div className="flex gap-1.5 overflow-x-auto pb-1" style={{ touchAction: "pan-x" }}>
            {presets.map((p) => (
              <div key={p.id} className="shrink-0 flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1.5">
                <button onClick={() => gotoPreset(p.id)} data-testid="mobile-ptz-preset-goto" className="text-xs">{p.name}</button>
                <button onClick={() => deletePreset(p)} data-testid="mobile-ptz-preset-delete" className="text-muted-foreground">
                  <XIcon size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="w-full flex items-center justify-between border-t border-border pt-3">
        <div className="flex items-center gap-2">
          <RotateCw size={16} className={patrol?.enabled ? "text-[#0044FF]" : "text-muted-foreground"} />
          <div>
            <div className="text-sm">Patrouille automatique</div>
            <div className="text-[10px] text-muted-foreground">Parcourt les presets ci-dessus</div>
          </div>
        </div>
        <button onClick={togglePatrol} disabled={busy || !presets?.length} data-testid="mobile-ptz-patrol-toggle"
                className={`w-11 h-6 rounded-full relative transition-colors disabled:opacity-40 ${patrol?.enabled ? "bg-[#0044FF]" : "bg-secondary"}`}>
          <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${patrol?.enabled ? "translate-x-5" : "translate-x-0.5"}`} />
        </button>
      </div>
    </div>
  );
}
