/**
 * CameraCenterDispatch — v1.0-rc4
 *
 * Route landing pour /camera-center (sans :cameraId dans l'URL).
 * On redirige simplement vers la page "Appareils" (/cameras) qui gère
 * déjà la liste + le clic "Ouvrir le Centre caméra". Pas de fetch
 * supplémentaire, aucune interférence avec la session auth.
 */
import React from "react";
import { Navigate } from "react-router-dom";

export default function CameraCenterDispatch() {
  return <Navigate to="/cameras" replace />;
}
