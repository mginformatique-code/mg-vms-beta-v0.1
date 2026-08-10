/**
 * useDeviceCapabilities — hook pour récupérer les capacités d'une caméra
 * via /api/devices/{camera_id}/capabilities (v0.4.6 device layer).
 *
 * Retourne { caps, info, loading, error, refresh, discover, errorLabel }.
 * caps est un objet plat : { ptz, zoom, spotlight, siren, ... }.
 * Toute UI conditionnelle DOIT lire depuis ce hook — jamais deviner par
 * le modèle de caméra.
 *
 * v1.0-rc4.5 · error.code (`authentication_failed`, `device_locked`,
 * `device_unreachable`, `command_timeout`, ...) est mappé vers un
 * `error.label` français ciblé (plus jamais "Unknown error").
 */
import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";

// v1.0-rc4.5 · Messages utilisateur par code d'erreur device layer.
// Chaque code retourné par les drivers doit avoir son entrée ici.
const ERROR_LABELS = {
  authentication_failed:
    "Authentification ONVIF refusée (HTTP 401). Vérifiez l'identifiant et le mot de passe de la caméra.",
  device_locked:
    "Caméra temporairement verrouillée après plusieurs tentatives d'authentification (protection anti-brute-force de la caméra). Attendez quelques minutes avant de réessayer.",
  device_unreachable:
    "Service ONVIF inaccessible sur cette adresse/port. Vérifiez le réseau, l'IP et le port ONVIF.",
  command_timeout:
    "Délai d'attente dépassé — la caméra ne répond pas à temps. Vérifiez la connectivité réseau.",
  camera_missing_ip:
    "Adresse IP absente pour cette caméra — impossible de contacter le service ONVIF.",
  camera_not_found:
    "Caméra introuvable dans la base MG-VMS.",
  unsupported_capability:
    "Cette fonction n'est pas supportée par le driver actuel de la caméra.",
  no_driver_available:
    "Aucun driver disponible pour cette caméra.",
  device_error:
    "La caméra a répondu par une erreur générique. Consultez les logs backend.",
  driver_error:
    "Erreur interne du driver — voir les logs backend.",
  load_failed:
    "Impossible de charger les capacités de la caméra.",
  discover_failed:
    "Échec de la découverte automatique.",
};

function labelForCode(code, fallback) {
  if (code && ERROR_LABELS[code]) return ERROR_LABELS[code];
  return fallback || "Erreur inconnue lors du dialogue avec la caméra.";
}

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
      const code = e.response?.data?.detail?.error || "load_failed";
      const rawMessage = e.response?.data?.detail?.message || e.message;
      setError({
        status,
        code,
        message: rawMessage,
        label: labelForCode(code, rawMessage),
      });
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
      const code = e.response?.data?.detail?.error || "discover_failed";
      const rawMessage = e.response?.data?.detail?.message || e.message;
      setError({
        status: e.response?.status,
        code,
        message: rawMessage,
        label: labelForCode(code, rawMessage),
      });
      throw e;
    } finally {
      setLoading(false);
    }
  }, [cameraId]);

  return { caps, info, loading, error, refresh: load, discover };
}
