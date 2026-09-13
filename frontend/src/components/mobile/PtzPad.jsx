/**
 * PtzPad — pavé directionnel PTZ compact, tactile (v3.91).
 *
 * Reprend le pattern "maintenir pour tourner" déjà éprouvé dans
 * CameraCenter.jsx (PTZTab::holdMove) — mouvement continu côté caméra tant
 * que le bouton est pressé, `stop` au relâchement (souris ET tactile).
 * Réimplémenté ici en petit composant autonome plutôt que d'extraire
 * PTZTab (grosse fonction avec presets/patrouille/suivi, aucun besoin ici)
 * pour ne prendre aucun risque de régression sur l'onglet PTZ desktop.
 */
import React from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight } from "lucide-react";

const BTN = "w-11 h-11 flex items-center justify-center bg-black/60 active:bg-[#00E5FF] active:text-black text-white select-none";

export default function PtzPad({ cameraId, speed = 0.5 }) {
  const move = (direction) =>
    api.post(`/devices/${cameraId}/ptz/move`, { direction, speed })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "PTZ indisponible"));

  const holdMove = (direction) => ({
    onMouseDown: (e) => { e.preventDefault(); move(direction); },
    onMouseUp: () => move("stop"),
    onMouseLeave: () => move("stop"),
    onTouchStart: (e) => { e.preventDefault(); move(direction); },
    onTouchEnd: () => move("stop"),
  });

  return (
    <div className="grid grid-cols-3 gap-1 w-fit" data-testid="mobile-ptz-pad">
      <div />
      <button className={BTN} {...holdMove("up")} data-testid="mobile-ptz-up"><ArrowUp size={18} /></button>
      <div />
      <button className={BTN} {...holdMove("left")} data-testid="mobile-ptz-left"><ArrowLeft size={18} /></button>
      <div className="w-11 h-11 bg-black/30" />
      <button className={BTN} {...holdMove("right")} data-testid="mobile-ptz-right"><ArrowRight size={18} /></button>
      <div />
      <button className={BTN} {...holdMove("down")} data-testid="mobile-ptz-down"><ArrowDown size={18} /></button>
      <div />
    </div>
  );
}
