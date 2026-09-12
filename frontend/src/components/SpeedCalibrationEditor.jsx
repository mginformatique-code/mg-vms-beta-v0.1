import React, { useState, useEffect } from "react";
import { X, Gauge } from "lucide-react";
import PolygonEditor from "@/components/PolygonEditor";
import LivePlayer from "@/components/video/LivePlayer";
import api from "@/lib/api";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";

/**
 * SpeedCalibrationEditor — v3.37 · Calibration vitesse par homographie.
 *
 * 4 points cliqués sur une image de référence (rectangle au sol, dimensions
 * réelles connues) -> l'utilisateur donne largeur/longueur réelles en
 * mètres -> le backend calcule l'homographie (routers.py::set_speed_calibration).
 * Réutilise PolygonEditor tel quel (maxPoints=4) plutôt qu'un nouveau
 * composant de dessin — même mécanique clic/glisser déjà en prod pour les
 * zones intelligentes et le ROI ANPR.
 *
 * Image de référence : capturée CÔTÉ CLIENT depuis le flux WebRTC déjà
 * fonctionnel (LivePlayer, celui du Mur vidéo), pas via un snapshot
 * backend — testé en direct, les deux routes existantes échouent en
 * pratique : /_helpers/camera-snapshot (go2rtc frame.jpeg renvoie 500 sur
 * un flux H265, confirmé sur rue_vers_centre bien qu'actif) et /ai/debug
 * (_last_debug vit dans la mémoire du process mgvms-pipeline, jamais
 * mgvms-backend qui sert cette route — deux containers séparés, aucune
 * synchro pour ce champ). Le flux WebRTC, lui, fonctionne déjà partout :
 * en capturer une frame est fiable indépendamment du codec source.
 */
export default function SpeedCalibrationEditor({ camera, existing, onClose, onSaved }) {
  const { t } = useApp();
  const [step, setStep] = useState("capture");
  const [points, setPoints] = useState(existing?.image_points || []);
  const [widthM, setWidthM] = useState(existing?.width_m ?? "");
  const [lengthM, setLengthM] = useState(existing?.length_m ?? "");
  const [saving, setSaving] = useState(false);
  const [snapshotUrl, setSnapshotUrl] = useState(null);
  const [captureError, setCaptureError] = useState(false);

  useEffect(() => {
    if (step !== "capture" || !camera?.id) return;
    let attempts = 0;
    const iv = setInterval(() => {
      attempts += 1;
      const video = document.querySelector('[data-testid="speed-cal-capture-video"]');
      if (video && video.readyState >= 2 && video.videoWidth > 0) {
        clearInterval(iv);
        try {
          const canvas = document.createElement("canvas");
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          canvas.getContext("2d").drawImage(video, 0, 0);
          setSnapshotUrl(canvas.toDataURL("image/jpeg", 0.85));
          setStep("points");
        } catch (e) {
          setCaptureError(true);
        }
      } else if (attempts > 40) {
        clearInterval(iv);
        setCaptureError(true);
      }
    }, 500);
    return () => clearInterval(iv);
  }, [step, camera?.id]);

  if (step === "capture") {
    return (
      <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" data-testid="speed-calibration-capture">
        <div className="bg-card border border-border w-full max-w-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="font-head font-semibold text-sm flex items-center gap-2"><Gauge size={14} /> {t("speedcal.capturing_stream")}</div>
            <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="speed-calibration-close"><X size={14} /></button>
          </div>
          <div className="relative aspect-video bg-black overflow-hidden">
            {camera?.id && <LivePlayer camera={camera} hd={false} dataTestId="speed-cal-capture" />}
          </div>
          {captureError ? (
            <p className="text-xs text-[#FF3333]">
              {t("speedcal.stream_unavailable")}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t("speedcal.connecting_stream")}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (step === "points") {
    return (
      <PolygonEditor
        imageSrc={snapshotUrl}
        initialPolygon={points}
        minPoints={4}
        maxPoints={4}
        title={`${t("speedcal.calibrate_title")} — ${camera?.name || ""} ${t("speedcal.calibrate_order")}`}
        onSave={(pts) => { setPoints(pts); setStep("dims"); }}
        onCancel={onClose}
      />
    );
  }

  const save = async () => {
    const w = parseFloat(widthM), l = parseFloat(lengthM);
    if (!(w > 0) || !(l > 0)) { toast.error(t("speedcal.dims_required")); return; }
    setSaving(true);
    try {
      const { data } = await api.put(`/cameras/${camera.id}/speed-calibration`, {
        image_points: points, width_m: w, length_m: l,
      });
      toast.success(t("speedcal.calibration_saved"));
      onSaved?.(data.calibration);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("speedcal.calibration_failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" data-testid="speed-calibration-dims">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="font-head font-semibold text-sm flex items-center gap-2"><Gauge size={14} /> {t("speedcal.real_dims_title")}</div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="speed-calibration-close"><X size={14} /></button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-muted-foreground">
            {t("speedcal.dims_explainer")}
          </p>
          <label className="block text-xs">
            {t("speedcal.width_label")}
            <input type="number" min="0.1" step="0.1" value={widthM} onChange={(e) => setWidthM(e.target.value)}
                   className="w-full mt-1 px-2 py-1.5 bg-secondary border border-border text-sm"
                   data-testid="speed-calibration-width" />
          </label>
          <label className="block text-xs">
            {t("speedcal.length_label")}
            <input type="number" min="0.1" step="0.1" value={lengthM} onChange={(e) => setLengthM(e.target.value)}
                   className="w-full mt-1 px-2 py-1.5 bg-secondary border border-border text-sm"
                   data-testid="speed-calibration-length" />
          </label>
        </div>
        <div className="p-3 border-t border-border flex justify-between gap-2">
          <button onClick={() => setStep("points")} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary">
            ← {t("speedcal.review_points")}
          </button>
          <button onClick={save} disabled={saving}
                  className="text-sm px-3 py-1.5 bg-[#0044FF] text-white hover:bg-[#0033cc] disabled:opacity-50"
                  data-testid="speed-calibration-save">
            {saving ? t("speedcal.calculating") : t("speedcal.calibrate")}
          </button>
        </div>
      </div>
    </div>
  );
}
