/**
 * useDeviceCapabilities — hook pour récupérer les capacités d'une caméra
 * via /api/devices/{camera_id}/capabilities (v0.4.6 device layer).
 *
 * Retourne { caps, loading, error, refresh }.
 * caps est un objet plat : { ptz, zoom, spotlight, siren, ... }.
 * Toute UI conditionnelle DOIT lire depuis ce hook — jamais deviner par
 * le modèle de caméra.
 */
import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";

export default function useDeviceCapabilities(cameraId) {
  const [caps, setCaps] = useState(null);
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!cameraId) return;
    setLoading(true);
    setError(null);
    try {
      const [capsRes, infoRes] = await Promise.all([
        api.get(`/devices/${cameraId}/capabilities`).catch((e) => ({ error: e })),
        api.get(`/devices/${cameraId}/info`).catch((e) => ({ error: e })),
      ]);
      if (capsRes.error) throw capsRes.error;
      setCaps(capsRes.data || null);
      if (!infoRes.error) setInfo(infoRes.data || null);
    } catch (e) {
      // 404 caméra pas encore probée → caps null (l'UI affiche "Détecter capacités")
      const status = e.response?.status;
      setError({ status, code: e.response?.data?.detail?.error || "load_failed",
                 message: e.response?.data?.detail?.message || e.message });
    } finally {
      setLoading(false);
    }
  }, [cameraId]);

  useEffect(() => { load(); }, [load]);

  const discover = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.post(`/devices/${cameraId}/discover`);
      setCaps(res.data.capabilities || null);
      setInfo(res.data.info || null);
      setError(null);
      return res.data;
    } catch (e) {
      setError({ status: e.response?.status,
                 code: e.response?.data?.detail?.error || "discover_failed",
                 message: e.response?.data?.detail?.message || e.message });
      throw e;
    } finally {
      setLoading(false);
    }
  }, [cameraId]);

  return { caps, info, loading, error, refresh: load, discover };
}
