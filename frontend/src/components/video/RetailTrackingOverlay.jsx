import React, { useEffect, useRef } from "react";

const COLOR_NORMAL = "#00E5FF";
const COLOR_LOITERING = "#FFB800";
const COLOR_CRITICAL = "#FF3333";
const COLOR_REPEATED = "#B47CFF";

function styleFor(tid, retail) {
  const r = retail ? retail[tid] : null;
  if (!r) return { color: COLOR_NORMAL, label: `Personne #${tid}` };
  if (r.critical) return { color: COLOR_CRITICAL, label: `⚠ Présence prolongée ${r.dwell_s}s` };
  if (r.repeated_visits) return { color: COLOR_REPEATED, label: `Passages répétés (${r.visits}x)` };
  if (r.loitering) return { color: COLOR_LOITERING, label: `Présence ${r.dwell_s}s` };
  return { color: COLOR_NORMAL, label: `Suivi ${r.dwell_s}s` };
}

/**
 * Overlay léger de tracking pour le plugin anti-vol "retail-suspicious-behavior".
 * À afficher uniquement quand la caméra a ce plugin dans `enabled_plugins`
 * (condition côté appelant, pas ici). Dessine un rectangle par personne
 * trackée + un texte au-dessus indiquant son état courant (temps de présence,
 * passages répétés). Volontairement limité aux personnes/au scope de ce
 * plugin — pas un overlay YOLO générique (voir OverlayCanvas dans
 * LiveView.jsx pour ça).
 *
 * `retail` ne couvre aujourd'hui que la Phase 1 (dwell-time / passages
 * répétés) — pas encore de dissimulation d'objet ni de vol confirmé, qui
 * viendront avec les phases suivantes du plan anti-vol.
 */
export default function RetailTrackingOverlay({ boxes, retail }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    const w = parent.clientWidth, h = parent.clientHeight;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);

    const persons = (boxes || []).filter((b) => b.label === "Personne" && b.track_id != null);
    if (!persons.length) return;

    ctx.lineWidth = 2;
    ctx.font = "bold 11px ui-monospace, monospace";
    for (const b of persons) {
      const tid = String(b.track_id);
      const { color, label } = styleFor(tid, retail);
      const [x1, y1, x2, y2] = b.bbox_norm;
      const rx = x1 * w, ry = y1 * h, rw = (x2 - x1) * w, rh = (y2 - y1) * h;

      ctx.strokeStyle = color;
      ctx.strokeRect(rx, ry, rw, rh);

      const metrics = ctx.measureText(label);
      const th = 15;
      ctx.fillStyle = color;
      ctx.fillRect(rx, Math.max(0, ry - th), metrics.width + 8, th);
      ctx.fillStyle = "#000";
      ctx.fillText(label, rx + 4, Math.max(11, ry - 3));
    }
  }, [boxes, retail]);

  return (
    <canvas
      ref={ref}
      className="absolute inset-0 w-full h-full pointer-events-none"
      data-testid="retail-tracking-overlay"
    />
  );
}
