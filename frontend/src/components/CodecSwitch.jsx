/**
 * CodecSwitch — bascule H.265 / H.264 du flux principal, depuis la liste
 * des appareils (et non depuis les paramètres de la caméra).
 *
 * Le codec affiché vient de la fiche caméra (`camera.codec`, déjà en base) :
 * aucune requête n'est envoyée au chargement de la liste. Interroger chaque
 * caméra au rendu coûterait un aller-retour réseau par ligne — mesuré à
 * plusieurs secondes par appareil, la page deviendrait inutilisable.
 *
 * La capacité réelle n'est donc vérifiée qu'AU CLIC, via
 * `GET /api/devices/{id}/encoding`. C'est volontaire et important : sur les
 * modèles testés (Reolink RLC-81MA), l'API accepte la commande de changement
 * et l'ignore silencieusement — seule la table des valeurs autorisées dit la
 * vérité. Le switch explique donc pourquoi il ne peut pas basculer, au lieu
 * de faire semblant d'avoir fonctionné.
 */
import React, { useState } from "react";
import { Loader2, Lock } from "lucide-react";
import api from "@/lib/api";
import { toast } from "sonner";

const NORM = (c) => String(c || "").toLowerCase().replace("hevc", "h265").replace(".", "");

export default function CodecSwitch({ camera, onChanged }) {
  const [codec, setCodec] = useState(NORM(camera?.codec));
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(null);   // null = pas encore vérifié
  const [reason, setReason] = useState("");

  const isH265 = codec === "h265";
  const target = isH265 ? "h264" : "h265";

  const toggle = async (e) => {
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      const { data: info } = await api.get(`/devices/${camera.id}/encoding`);
      if (!info.changeable) {
        setLocked(true);
        setReason(info.reason || "Codec non modifiable sur ce modèle");
        if (info.current) setCodec(NORM(info.current));
        toast.info(info.reason || "Codec non modifiable sur ce modèle");
        return;
      }
      await api.post(`/devices/${camera.id}/encoding`, { codec: target });
      setCodec(target);
      setLocked(false);
      toast.success(`Flux principal basculé en ${target.toUpperCase()}`);
      onChanged?.(camera.id, target);
    } catch (err) {
      const d = err.response?.data?.detail;
      const msg = d?.message || d || "Changement de codec impossible";
      if (d?.error === "unsupported_capability") {
        setLocked(true);
        setReason(msg);
        toast.info(msg);
      } else {
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  const title = locked
    ? reason
    : `Basculer le flux principal en ${target.toUpperCase()} (actuellement ${codec.toUpperCase() || "?"})`;

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy || locked === true}
      title={title}
      data-testid={`codec-switch-${camera.id}`}
      className={`inline-flex items-center gap-1 border text-[10px] mono uppercase tracking-wider
                  transition-colors disabled:cursor-not-allowed
                  ${locked ? "border-border text-muted-foreground opacity-70"
                           : "border-[#0044FF] hover:bg-[#0044FF]/10"}`}
    >
      <span className={`px-1.5 py-0.5 ${isH265 ? "bg-[#0044FF] text-white" : "text-muted-foreground"}`}>
        H265
      </span>
      <span className={`px-1.5 py-0.5 ${!isH265 ? "bg-[#00E676] text-black" : "text-muted-foreground"}`}>
        H264
      </span>
      {busy && <Loader2 size={11} className="animate-spin mr-1" />}
      {locked && !busy && <Lock size={10} className="mr-1" />}
    </button>
  );
}
