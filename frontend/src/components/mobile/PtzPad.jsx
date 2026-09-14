/**
 * PtzPad — pavé directionnel PTZ compact, tactile (v3.91, corrigé v3.94/v3.98).
 *
 * Reprend le pattern "maintenir pour tourner" déjà éprouvé dans
 * CameraCenter.jsx (PTZTab::holdMove) — mouvement continu côté caméra tant
 * que le bouton est pressé, `stop` au relâchement (souris ET tactile).
 * Réimplémenté ici en petit composant autonome plutôt que d'extraire
 * PTZTab (grosse fonction avec presets/patrouille/suivi, aucun besoin ici)
 * pour ne prendre aucun risque de régression sur l'onglet PTZ desktop.
 *
 * v3.94 · Corrige "le PTZ bouge sans s'arrêter" — `onTouchCancel` +
 * `touch-action: none` ajoutés (voir CHANGELOG v3.94).
 *
 * v3.98 · Corrige "le zoom ne s'arrête jamais" — root cause réelle,
 * confirmée côté backend (`onvif_driver.py::_ptz_zoom`) : le zoom ONVIF
 * est un `ContinuousMove` comme pan/tilt, mais les boutons zoom (ici ET
 * sur l'onglet PTZ desktop) ne faisaient qu'un `onClick` unique sans
 * jamais envoyer de stop — la caméra zoomait donc jusqu'à sa butée
 * physique à chaque appui. Le backend a été corrigé pour que
 * `ptz/move {direction:"stop"}` arrête explicitement PanTilt ET Zoom sur
 * le même profil ONVIF ; le zoom passe donc au même pattern "maintenir
 * pour zoomer" que les 8 boutons directionnels, réutilisant CET ENDPOINT
 * de stop existant (aucun nouvel endpoint nécessaire).
 * Vitesse réglable ajoutée (demande explicite) — persistée en
 * localStorage par caméra, même convention que `ptzSpeed` desktop
 * (CameraCenter.jsx::PTZTab).
 *
 * v3.112 · Régression réelle signalée en test sur internet (pas seulement
 * LAN) : "tu appuies une fois dessus et ça continue sans s'arrêter". Root
 * cause : `move(direction)` puis `move("stop")` sont deux requêtes HTTP
 * indépendantes, tirées l'une juste après l'autre sans jamais attendre la
 * première — sur une connexion à latence variable (le cas d'usage change
 * depuis les tests via live.mg-vms.com), rien ne garantit que le serveur
 * traite "démarrer" AVANT "arrêter" : si "arrêter" arrive en premier (pas
 * d'effet, rien à arrêter), puis "démarrer" arrive ensuite, la caméra part
 * en mouvement et ne reçoit plus jamais d'ordre d'arrêt. Corrigé en
 * attendant la résolution de la requête de démarrage avant d'envoyer
 * l'arrêt — garantit l'ordre côté serveur même sur une connexion lente.
 */
import React, { useRef, useState } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Minus, Plus } from "lucide-react";

const BTN = "w-11 h-11 rounded-xl flex items-center justify-center bg-black/60 active:bg-[#00E5FF] active:text-black text-white select-none";
const TOUCH_STYLE = { touchAction: "none" };

export default function PtzPad({ cameraId }) {
  const [speed, setSpeed] = useState(() => {
    const saved = Number(localStorage.getItem(`ptz_speed_${cameraId}`));
    return saved >= 0.1 && saved <= 1 ? saved : 0.5;
  });
  const setAndSaveSpeed = (v) => {
    const clamped = Math.max(0.1, Math.min(1, Math.round(v * 10) / 10));
    setSpeed(clamped);
    localStorage.setItem(`ptz_speed_${cameraId}`, String(clamped));
  };

  const move = (direction) =>
    api.post(`/devices/${cameraId}/ptz/move`, { direction, speed })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "PTZ indisponible"));

  const zoom = (value) =>
    api.post(`/devices/${cameraId}/ptz/zoom`, { value })
       .catch((e) => toast.error(e.response?.data?.detail?.message || "Zoom indisponible"));

  // v3.112 · `pending` retient la requête de démarrage en cours — l'arrêt
  // attend sa résolution avant de partir, pour ne jamais risquer que
  // "stop" atteigne le serveur avant "start" sur une connexion lente.
  const pending = useRef(null);
  const holdAction = (start) => {
    const doStop = async () => {
      try { await pending.current; } catch { /* déjà géré par le .catch de start() */ }
      move("stop");
    };
    return {
      onMouseDown: (e) => { e.preventDefault(); pending.current = start(); },
      onMouseUp: doStop,
      onMouseLeave: doStop,
      onTouchStart: (e) => { e.preventDefault(); pending.current = start(); },
      onTouchEnd: doStop,
      onTouchCancel: doStop,
      style: TOUCH_STYLE,
    };
  };
  const holdMove = (direction) => holdAction(() => move(direction));
  const holdZoom = (value) => holdAction(() => zoom(value));

  return (
    <div className="flex flex-col items-center gap-2" data-testid="mobile-ptz-pad">
      <div className="flex items-center gap-3">
        <div className="grid grid-cols-3 gap-1 w-fit">
          <div />
          <button className={BTN} {...holdMove("up")} data-testid="mobile-ptz-up"><ArrowUp size={18} /></button>
          <div />
          <button className={BTN} {...holdMove("left")} data-testid="mobile-ptz-left"><ArrowLeft size={18} /></button>
          <div className="w-11 h-11 rounded-xl bg-black/30" />
          <button className={BTN} {...holdMove("right")} data-testid="mobile-ptz-right"><ArrowRight size={18} /></button>
          <div />
          <button className={BTN} {...holdMove("down")} data-testid="mobile-ptz-down"><ArrowDown size={18} /></button>
          <div />
        </div>
        <div className="flex flex-col gap-1">
          <button className={BTN} {...holdZoom(0.5)} data-testid="mobile-ptz-zoom-in"><Plus size={18} /></button>
          <button className={BTN} {...holdZoom(-0.5)} data-testid="mobile-ptz-zoom-out"><Minus size={18} /></button>
        </div>
      </div>
      <div className="flex items-center gap-2 text-white text-xs" data-testid="mobile-ptz-speed">
        <span className="uppercase tracking-wider text-white/60">Vitesse</span>
        <button className="w-7 h-7 rounded-lg flex items-center justify-center bg-black/60" onClick={() => setAndSaveSpeed(speed - 0.1)} data-testid="mobile-ptz-speed-down">−</button>
        <span className="mono w-9 text-center">{Math.round(speed * 100)}%</span>
        <button className="w-7 h-7 rounded-lg flex items-center justify-center bg-black/60" onClick={() => setAndSaveSpeed(speed + 0.1)} data-testid="mobile-ptz-speed-up">+</button>
      </div>
    </div>
  );
}
