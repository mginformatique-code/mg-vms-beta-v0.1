import React, { useState } from "react";
import { X, Gauge } from "lucide-react";
import PolygonEditor from "@/components/PolygonEditor";
import api from "@/lib/api";
import { toast } from "sonner";

/**
 * SpeedCalibrationEditor — v3.37 · Calibration vitesse par homographie.
 *
 * 4 points cliqués sur un snapshot (rectangle au sol, dimensions réelles
 * connues) -> l'utilisateur donne largeur/longueur réelles en mètres ->
 * le backend calcule l'homographie (routers.py::set_speed_calibration).
 * Réutilise PolygonEditor tel quel (maxPoints=4) plutôt qu'un nouveau
 * composant de dessin — même mécanique clic/glisser déjà en prod pour les
 * zones intelligentes et le ROI ANPR.
 */
export default function SpeedCalibrationEditor({ camera, existing, onClose, onSaved }) {
  const [step, setStep] = useState("points");
  const [points, setPoints] = useState(existing?.image_points || []);
  const [widthM, setWidthM] = useState(existing?.width_m ?? "");
  const [lengthM, setLengthM] = useState(existing?.length_m ?? "");
  const [saving, setSaving] = useState(false);

  const snapshotUrl = camera?.id
    ? `${process.env.REACT_APP_BACKEND_URL}/api/plugins/_helpers/camera-snapshot/${camera.id}?_=${Date.now()}`
    : null;

  if (step === "points") {
    return (
      <PolygonEditor
        imageSrc={snapshotUrl}
        initialPolygon={points}
        minPoints={4}
        maxPoints={4}
        title={`Calibrer la vitesse — ${camera?.name || ""} (ordre : proche-gauche, proche-droite, loin-droite, loin-gauche)`}
        onSave={(pts) => { setPoints(pts); setStep("dims"); }}
        onCancel={onClose}
      />
    );
  }

  const save = async () => {
    const w = parseFloat(widthM), l = parseFloat(lengthM);
    if (!(w > 0) || !(l > 0)) { toast.error("Largeur et longueur réelles requises (mètres)"); return; }
    setSaving(true);
    try {
      const { data } = await api.put(`/cameras/${camera.id}/speed-calibration`, {
        image_points: points, width_m: w, length_m: l,
      });
      toast.success("Calibration vitesse enregistrée");
      onSaved?.(data.calibration);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec de la calibration");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" data-testid="speed-calibration-dims">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="font-head font-semibold text-sm flex items-center gap-2"><Gauge size={14} /> Dimensions réelles</div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="speed-calibration-close"><X size={14} /></button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-muted-foreground">
            Le rectangle tracé au sol : largeur = distance entre les points 1 et 2 (proche-gauche → proche-droite),
            longueur = distance entre les points 1 et 4 (proche → loin). En mètres.
          </p>
          <label className="block text-xs">
            Largeur (m)
            <input type="number" min="0.1" step="0.1" value={widthM} onChange={(e) => setWidthM(e.target.value)}
                   className="w-full mt-1 px-2 py-1.5 bg-secondary border border-border text-sm"
                   data-testid="speed-calibration-width" />
          </label>
          <label className="block text-xs">
            Longueur (m)
            <input type="number" min="0.1" step="0.1" value={lengthM} onChange={(e) => setLengthM(e.target.value)}
                   className="w-full mt-1 px-2 py-1.5 bg-secondary border border-border text-sm"
                   data-testid="speed-calibration-length" />
          </label>
        </div>
        <div className="p-3 border-t border-border flex justify-between gap-2">
          <button onClick={() => setStep("points")} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">
            ← Revoir les points
          </button>
          <button onClick={save} disabled={saving}
                  className="text-sm px-3 py-1.5 bg-[#0044FF] text-white hover:bg-[#0033cc] disabled:opacity-50"
                  data-testid="speed-calibration-save">
            {saving ? "Calcul…" : "Calibrer"}
          </button>
        </div>
      </div>
    </div>
  );
}
