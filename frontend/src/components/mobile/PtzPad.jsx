/**
 * PtzPad — pavé directionnel PTZ compact, tactile (v3.91, corrigé v3.94).
 *
 * Reprend le pattern "maintenir pour tourner" déjà éprouvé dans
 * CameraCenter.jsx (PTZTab::holdMove) — mouvement continu côté caméra tant
 * que le bouton est pressé, `stop` au relâchement (souris ET tactile).
 * Réimplémenté ici en petit composant autonome plutôt que d'extraire
 * PTZTab (grosse fonction avec presets/patrouille/suivi, aucun besoin ici)
 * pour ne prendre aucun risque de régression sur l'onglet PTZ desktop.
 *
 * v3.94 · Corrige "le PTZ bouge sans s'arrêter" (signalé en usage réel) —
 * `onTouchEnd` seul ne suffit pas : dès que le doigt bouge un peu pendant
 * l'appui (tremblement naturel, ou le navigateur qui interprète le geste
 * comme un défilement), le navigateur émet `touchcancel` au lieu de
 * `touchend` — jamais géré ici, donc `move("stop")` n'était jamais envoyé
 * et la caméra continuait de tourner indéfiniment. `touch-action: none`
 * réduit aussi le risque que le navigateur requalifie le geste en scroll.
 * Même bug latent corrigé dans CameraCenter.jsx::PTZTab::holdMove (mêmes
 * boutons désormais aussi utilisés depuis mobile via l'onglet Caméras).
 */
import React from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Minus, Plus } from "lucide-react";

const BTN = "w-11 h-11 flex items-center justify-center bg-black/60 active:bg-[#00E5FF] active:text-black text-white select-none";
const TOUCH_STYLE = { touchAction: "none" };

export default function PtzPad({ cameraId, speed = 0.5 }) {
  const move = (direction) =>
    api.post(`/devices/${cameraId}/ptz/move`, { direction, speed })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "PTZ indisponible"));

  const zoom = (value) =>
    api.post(`/devices/${cameraId}/ptz/zoom`, { value })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Zoom indisponible"));

  const holdMove = (direction) => ({
    onMouseDown: (e) => { e.preventDefault(); move(direction); },
    onMouseUp: () => move("stop"),
    onMouseLeave: () => move("stop"),
    onTouchStart: (e) => { e.preventDefault(); move(direction); },
    onTouchEnd: () => move("stop"),
    onTouchCancel: () => move("stop"),
    style: TOUCH_STYLE,
  });

  return (
    <div className="flex items-center gap-3" data-testid="mobile-ptz-pad">
      <div className="grid grid-cols-3 gap-1 w-fit">
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
      <div className="flex flex-col gap-1">
        <button className={BTN} onClick={() => zoom(0.5)} data-testid="mobile-ptz-zoom-in"><Plus size={18} /></button>
        <button className={BTN} onClick={() => zoom(-0.5)} data-testid="mobile-ptz-zoom-out"><Minus size={18} /></button>
      </div>
    </div>
  );
}
