/**
 * CameraCenterDispatch — v1.0-rc4
 *
 * Route landing pour /camera-center (sans :cameraId dans l'URL).
 * - Récupère la liste des caméras
 * - Si ≥ 1 caméra → redirige vers /camera-center/<première>
 * - Si 0 caméra → empty state avec CTA "Ajouter une caméra"
 *
 * Évite de dupliquer la logique de CameraCenter.jsx (qui exige un ID)
 * et garde le menu "Centre caméras" fonctionnel dans la sidebar.
 */
import React, { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Loader2, Cctv, Plus } from "lucide-react";

export default function CameraCenterDispatch() {
  const [state, setState] = useState({ loading: true, cameras: [] });
  const navigate = useNavigate();

  useEffect(() => {
    api.get("/cameras")
      .then((r) => setState({ loading: false, cameras: Array.isArray(r.data) ? r.data : [] }))
      .catch(() => setState({ loading: false, cameras: [] }));
  }, []);

  if (state.loading) {
    return (
      <div className="flex items-center gap-2 py-10 text-muted-foreground" data-testid="camera-center-dispatch-loading">
        <Loader2 size={16} className="animate-spin" /> Chargement du Centre caméras…
      </div>
    );
  }
  if (state.cameras.length > 0) {
    const first = state.cameras[0];
    return <Navigate to={`/camera-center/${first.id}`} replace />;
  }
  return (
    <div className="max-w-2xl mx-auto py-16 text-center space-y-4" data-testid="camera-center-dispatch-empty">
      <Cctv size={48} className="mx-auto text-muted-foreground" strokeWidth={1.2} />
      <h1 className="font-head text-2xl">Centre caméras</h1>
      <p className="text-sm text-muted-foreground">
        Aucune caméra n&apos;est configurée. Ajoutez-en une pour accéder au hub caméra
        (aperçu, PTZ, ONVIF, capacités, plugins, journal, snapshots, WSDL…).
      </p>
      <button
        onClick={() => navigate("/cameras")}
        data-testid="camera-center-dispatch-add-btn"
        className="inline-flex items-center gap-2 px-4 py-2 border border-border bg-secondary hover:bg-secondary/80 text-sm"
      >
        <Plus size={14} /> Ajouter une caméra
      </button>
    </div>
  );
}
