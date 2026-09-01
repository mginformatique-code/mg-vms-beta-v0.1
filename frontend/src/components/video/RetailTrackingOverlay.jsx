import React, { useEffect, useRef } from "react";

const COLOR_NORMAL = "#00E5FF";
const COLOR_LOITERING = "#FFB800";
const COLOR_CRITICAL = "#FF3333";
const COLOR_REPEATED = "#B47CFF";

// COCO-17 (ordre standard ultralytics YOLO-pose) : indices des points-clés.
const KP = {
  nose: 0, leftEye: 1, rightEye: 2, leftEar: 3, rightEar: 4,
  leftShoulder: 5, rightShoulder: 6, leftElbow: 7, rightElbow: 8,
  leftWrist: 9, rightWrist: 10, leftHip: 11, rightHip: 12,
  leftKnee: 13, rightKnee: 14, leftAnkle: 15, rightAnkle: 16,
};

// Squelette groupé par partie du corps, coloré séparément (approximation
// visuelle de la maille Veesion — pas une vraie segmentation dense par
// pixel, juste un squelette épais coloré par groupe de membre).
const SKELETON_GROUPS = [
  { color: "#FF6FB0", width: 3, edges: [ // tête
    [KP.nose, KP.leftEye], [KP.nose, KP.rightEye],
    [KP.leftEye, KP.leftEar], [KP.rightEye, KP.rightEar],
  ]},
  { color: "#0044FF", width: 5, edges: [ // torse
    [KP.leftShoulder, KP.rightShoulder],
    [KP.leftShoulder, KP.leftHip], [KP.rightShoulder, KP.rightHip],
    [KP.leftHip, KP.rightHip],
  ]},
  { color: "#FF3333", width: 4, edges: [ // bras
    [KP.leftShoulder, KP.leftElbow], [KP.leftElbow, KP.leftWrist],
    [KP.rightShoulder, KP.rightElbow], [KP.rightElbow, KP.rightWrist],
  ]},
  { color: "#00E1FF", width: 4, edges: [ // jambes
    [KP.leftHip, KP.leftKnee], [KP.leftKnee, KP.leftAnkle],
    [KP.rightHip, KP.rightKnee], [KP.rightKnee, KP.rightAnkle],
  ]},
];
const KP_MIN_CONF = 0.3;

function statusFor(tid, retail) {
  const r = retail ? retail[tid] : null;
  if (!r) return { color: COLOR_NORMAL, label: `Personne #${tid}` };
  const activity = r.activity === "walking" ? "Marche" : "Immobile";
  if (r.critical) return { color: COLOR_CRITICAL, label: `⚠ Présence prolongée ${r.dwell_s}s · ${activity}` };
  if (r.repeated_visits) return { color: COLOR_REPEATED, label: `Passages répétés (${r.visits}x) · ${activity}` };
  if (r.loitering) return { color: COLOR_LOITERING, label: `Présence ${r.dwell_s}s · ${activity}` };
  return { color: COLOR_NORMAL, label: `Suivi ${r.dwell_s}s · ${activity}` };
}

function drawSkeleton(ctx, keypointsNorm, w, h) {
  for (const group of SKELETON_GROUPS) {
    ctx.strokeStyle = group.color;
    ctx.lineWidth = group.width;
    ctx.lineCap = "round";
    for (const [ai, bi] of group.edges) {
      const a = keypointsNorm[ai], b = keypointsNorm[bi];
      if (!a || !b || a[2] < KP_MIN_CONF || b[2] < KP_MIN_CONF) continue;
      ctx.beginPath();
      ctx.moveTo(a[0] * w, a[1] * h);
      ctx.lineTo(b[0] * w, b[1] * h);
      ctx.stroke();
    }
  }
}

/**
 * Overlay léger de tracking pour le plugin anti-vol "retail-suspicious-behavior".
 * À afficher uniquement quand la caméra a ce plugin dans `enabled_plugins`
 * (condition côté appelant, pas ici). Dessine, par personne trackée : un
 * squelette coloré par groupe de membre (tête/torse/bras/jambes — approche
 * visuelle inspirée de la maille Veesion, sans vraie segmentation dense) si
 * le cœur a calculé des keypoints ce cycle (`b.keypoints_norm`), sinon un
 * simple rectangle en repli ; et un texte au-dessus avec l'activité
 * (Marche/Immobile, dérivée d'un delta de position — pas un modèle) + le
 * statut du plugin (temps de présence, passages répétés).
 *
 * Aucun pourcentage de confiance IA fabriqué : contrairement à Veesion (qui
 * affiche un score "Normal/Suspect" issu de son dataset propriétaire), on
 * n'affiche que nos vrais signaux — décision actée avec l'utilisateur.
 *
 * Ne couvre que la Phase 1 (dwell-time / passages répétés) — pas encore de
 * dissimulation d'objet ni de vol confirmé (Phase 3+).
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

    ctx.font = "bold 11px ui-monospace, monospace";
    for (const b of persons) {
      const tid = String(b.track_id);
      const { color, label } = statusFor(tid, retail);
      const [x1, y1, x2, y2] = b.bbox_norm;
      const rx = x1 * w, ry = y1 * h, rw = (x2 - x1) * w, rh = (y2 - y1) * h;

      if (b.keypoints_norm && b.keypoints_norm.length >= 17) {
        drawSkeleton(ctx, b.keypoints_norm, w, h);
      } else {
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(rx, ry, rw, rh);
      }

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
