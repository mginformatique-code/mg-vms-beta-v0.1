import React, { useEffect, useRef, useState } from "react";
import { X, Undo2, Trash2, Save } from "lucide-react";

/**
 * PolygonEditor — Dessine un polygone (ROI, zone parking, etc.) sur un fond image.
 * Coordonnées stockées normalisées 0-1 pour être indépendantes de la résolution d'affichage.
 *
 * Props:
 *  - imageSrc: URL du fond (snapshot caméra)
 *  - initialPolygon: Array<[xn, yn]> — polygone existant
 *  - onSave(polygon): callback appelé sur "Enregistrer"
 *  - onCancel(): callback fermeture sans sauver
 *  - minPoints (default 3)
 */
export default function PolygonEditor({ imageSrc, initialPolygon = [], onSave, onCancel, minPoints = 3, title = "Dessiner la zone" }) {
  const [points, setPoints] = useState(initialPolygon);
  const [size, setSize] = useState({ w: 640, h: 360 });
  const imgRef = useRef(null);
  const canvasRef = useRef(null);
  const [dragIdx, setDragIdx] = useState(-1);

  // Redessine à chaque changement de points
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (points.length === 0) return;
    ctx.strokeStyle = "#00E676"; ctx.lineWidth = 2; ctx.fillStyle = "rgba(0,230,118,0.15)";
    ctx.beginPath();
    points.forEach(([xn, yn], i) => {
      const x = xn * canvas.width, y = yn * canvas.height;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    if (points.length >= 3) ctx.closePath();
    ctx.stroke();
    if (points.length >= 3) ctx.fill();
    // Poignées
    points.forEach(([xn, yn], i) => {
      const x = xn * canvas.width, y = yn * canvas.height;
      ctx.fillStyle = i === dragIdx ? "#FFB800" : "#00E676";
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#000"; ctx.font = "bold 10px sans-serif";
      ctx.fillText(String(i + 1), x - 3, y + 3);
    });
  }, [points, size, dragIdx]);

  const onImgLoad = () => {
    const rect = imgRef.current.getBoundingClientRect();
    setSize({ w: rect.width, h: rect.height });
  };

  const getPt = (e) => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
  };

  const findNearHandle = (xn, yn) => {
    const canvas = canvasRef.current;
    const tolPx = 12;
    const tolX = tolPx / canvas.width, tolY = tolPx / canvas.height;
    return points.findIndex(([px, py]) => Math.abs(px - xn) < tolX && Math.abs(py - yn) < tolY);
  };

  const onCanvasDown = (e) => {
    const [xn, yn] = getPt(e);
    const idx = findNearHandle(xn, yn);
    if (idx >= 0) { setDragIdx(idx); return; }
    setPoints((p) => [...p, [xn, yn]]);
  };

  const onCanvasMove = (e) => {
    if (dragIdx < 0) return;
    const [xn, yn] = getPt(e);
    setPoints((p) => p.map((pt, i) => (i === dragIdx ? [xn, yn] : pt)));
  };

  const onCanvasUp = () => setDragIdx(-1);

  const undo = () => setPoints((p) => p.slice(0, -1));
  const clear = () => setPoints([]);
  const save = () => {
    if (points.length && points.length < minPoints) {
      alert(`Le polygone doit contenir au moins ${minPoints} points (ou être vide pour désactiver la ROI).`);
      return;
    }
    onSave?.(points);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" data-testid="polygon-editor">
      <div className="bg-card border border-border w-full max-w-4xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="font-head font-semibold text-sm">{title}</div>
          <div className="flex items-center gap-2">
            <button onClick={undo} disabled={!points.length} className="flex items-center gap-1 text-xs px-2 py-1 border border-border hover:bg-secondary disabled:opacity-40" data-testid="polygon-undo">
              <Undo2 size={12} /> Annuler dernier
            </button>
            <button onClick={clear} disabled={!points.length} className="flex items-center gap-1 text-xs px-2 py-1 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10 disabled:opacity-40" data-testid="polygon-clear">
              <Trash2 size={12} /> Tout effacer
            </button>
            <button onClick={onCancel} className="p-1 hover:bg-secondary" data-testid="polygon-close"><X size={14} /></button>
          </div>
        </div>
        <div className="p-3 flex-1 overflow-auto">
          <div className="relative inline-block mx-auto" style={{ maxWidth: "100%" }}>
            <img ref={imgRef} src={imageSrc} alt="snapshot" onLoad={onImgLoad}
                 className="block max-w-full max-h-[60vh] bg-black"
                 crossOrigin="anonymous"
                 onError={(e) => { e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'><rect width='100%' height='100%' fill='%23222'/><text x='50%' y='50%' fill='%23666' text-anchor='middle' font-family='sans-serif'>Snapshot indisponible</text></svg>"; }} />
            <canvas ref={canvasRef} width={size.w} height={size.h}
                    onMouseDown={onCanvasDown} onMouseMove={onCanvasMove} onMouseUp={onCanvasUp} onMouseLeave={onCanvasUp}
                    className="absolute inset-0 cursor-crosshair"
                    style={{ width: size.w, height: size.h }}
                    data-testid="polygon-canvas" />
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Cliquez pour ajouter un sommet · Glissez une poignée pour la déplacer · Minimum {minPoints} points · {points.length} point(s) actuellement
          </p>
        </div>
        <div className="p-3 border-t border-border flex justify-end gap-2">
          <button onClick={onCancel} className="text-sm px-3 py-1.5 border border-border hover:bg-secondary" data-testid="polygon-cancel">Annuler</button>
          <button onClick={save} className="flex items-center gap-1.5 text-sm px-3 py-1.5 bg-[#0044FF] text-white hover:bg-[#0033cc]" data-testid="polygon-save">
            <Save size={14} /> Enregistrer ({points.length} points)
          </button>
        </div>
      </div>
    </div>
  );
}
