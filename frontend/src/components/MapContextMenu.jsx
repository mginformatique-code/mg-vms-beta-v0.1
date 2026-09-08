import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronRight } from "lucide-react";

/**
 * v3.55 · Menu contextuel maison pour la page Carte (MapCenter.jsx /
 * LiveMapCanvas.jsx) — clic-droit sur une caméra/un équipement/une
 * connexion/le vide.
 *
 * Pourquoi pas le `ContextMenu` shadcn/Radix déjà dans components/ui/ :
 * Radix attache son déclencheur à un vrai nœud DOM, mais un <Group>
 * react-konva n'a pas de présence DOM individuelle (tout est peint sur un
 * seul <canvas>) — impossible de lui accrocher un ContextMenuTrigger.
 * Ce composant, lui, est purement contrôlé (ouvert via {x, y, items} en
 * state React, positionné en `fixed` par coordonnées viewport) : il
 * fonctionne identiquement que le clic-droit vienne d'un événement DOM
 * natif (Leaflet) ou d'un événement Konva (où l'on lit `evt.clientX/Y`
 * sur l'event natif sous-jacent).
 *
 * `items` : liste de `{ type: "item", label, icon?, onClick, danger? }`
 * | `{ type: "separator" }`
 * | `{ type: "submenu", label, icon?, options: [{ label, icon?, onClick }] }`
 */
export default function MapContextMenu({ x, y, items, onClose }) {
  const rootRef = useRef(null);
  const [openSub, setOpenSub] = useState(null);

  useEffect(() => {
    const onDown = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  // Évite de dépasser le viewport côté droit/bas.
  const style = {
    position: "fixed",
    left: Math.min(x, window.innerWidth - 220),
    top: Math.min(y, window.innerHeight - 24),
    zIndex: 10000,
  };

  const rowClass = "flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary cursor-pointer whitespace-nowrap";

  return createPortal(
    <div ref={rootRef} style={style}
         className="bg-card border border-border shadow-lg py-1 min-w-[180px]" data-testid="map-context-menu">
      {items.map((it, i) => {
        if (it.type === "separator") return <div key={i} className="h-px bg-border my-1" />;
        if (it.type === "submenu") {
          const isOpen = openSub === i;
          return (
            <div key={i} className="relative" onMouseEnter={() => setOpenSub(i)} onMouseLeave={() => setOpenSub(null)}>
              <div className={rowClass} data-testid={`map-ctx-submenu-${i}`}>
                {it.icon && <it.icon size={13} />}
                <span className="flex-1">{it.label}</span>
                <ChevronRight size={12} className="text-muted-foreground" />
              </div>
              {isOpen && (
                <div className="absolute left-full top-0 bg-card border border-border shadow-lg py-1 min-w-[160px]">
                  {it.options.map((op, j) => (
                    <div key={j} className={rowClass} data-testid={`map-ctx-suboption-${i}-${j}`}
                         onClick={() => { onClose(); op.onClick(); }}>
                      {op.icon && <op.icon size={13} style={op.color ? { color: op.color } : undefined} />}
                      <span>{op.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        }
        return (
          <div key={i} className={`${rowClass} ${it.danger ? "text-[#FF3333]" : ""}`}
               data-testid={`map-ctx-item-${i}`}
               onClick={() => { onClose(); it.onClick(); }}>
            {it.icon && <it.icon size={13} />}
            <span>{it.label}</span>
          </div>
        );
      })}
    </div>,
    document.body
  );
}
