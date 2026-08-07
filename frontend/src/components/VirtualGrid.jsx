import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Grid } from "react-window";

/**
 * VirtualGrid — grille responsive virtualisée basée sur react-window v2.
 *
 * P0 v0.8-rc3 · Empêche l'explosion DOM sur les listes massives (500k+).
 * Rend uniquement les cellules visibles ± overscan.
 *
 * Props :
 *   items         : Array<T>                 données à afficher
 *   renderItem    : (item, index) => JSX     rendu d'une cellule
 *   itemKey       : (item, index) => string  clé stable (recommandé)
 *   rowHeight     : number                   hauteur d'une ligne (défaut 320)
 *   minColumnWidth: number                   largeur min d'une colonne (défaut 260)
 *   maxColumns    : number                   plafond de colonnes (défaut 4)
 *   height        : number                   hauteur du viewport de la grille (défaut auto)
 *   threshold     : number                   sous ce nombre, rendu classique non virtualisé (défaut 200)
 *   gap           : number                   espace inter-cellules en px (défaut 16)
 *   className     : string                   wrapper classes
 *   testid        : string                   data-testid du root
 *   fallbackClassName : string               grid classes pour rendu non virtualisé
 */
export default function VirtualGrid({
  items,
  renderItem,
  itemKey,
  rowHeight = 320,
  minColumnWidth = 260,
  maxColumns = 4,
  height,
  threshold = 200,
  gap = 16,
  className = "",
  testid = "virtual-grid",
  fallbackClassName = "grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
}) {
  const rootRef = useRef(null);
  const [width, setWidth] = useState(0);

  // Mesure de largeur (responsive)
  useLayoutEffect(() => {
    if (!rootRef.current) return;
    const el = rootRef.current;
    const obs = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width ?? el.clientWidth;
      setWidth(Math.floor(w));
    });
    obs.observe(el);
    setWidth(el.clientWidth || 0);
    return () => obs.disconnect();
  }, []);

  const count = items?.length ?? 0;

  // Sous le seuil : rendu classique (plus riche visuellement, aucune régression UX)
  if (count === 0 || count < threshold) {
    return (
      <div ref={rootRef} className={className} data-testid={testid}>
        <div className={fallbackClassName}>
          {items.map((it, i) => (
            <div key={itemKey ? itemKey(it, i) : i}>{renderItem(it, i)}</div>
          ))}
        </div>
      </div>
    );
  }

  // Calcul colonnes en fonction de la largeur
  const columnCount = Math.max(1, Math.min(maxColumns, Math.floor((width || 320) / minColumnWidth)));
  const rowCount = Math.ceil(count / columnCount);
  const columnWidth = width ? Math.floor(width / columnCount) : minColumnWidth;

  // Hauteur : soit fournie, soit calcul auto (min(rowCount * rowHeight, viewport - 300)).
  const viewportH = typeof window !== "undefined" ? window.innerHeight : 900;
  const autoHeight = Math.min(rowCount * rowHeight, Math.max(400, viewportH - 300));
  const gridHeight = height ?? autoHeight;

  return (
    <div ref={rootRef} className={className} data-testid={testid}>
      <div
        data-testid={`${testid}-virtualized`}
        data-count={count}
        data-columns={columnCount}
        data-rows={rowCount}
      >
        {width > 0 && (
          <Grid
            cellComponent={Cell}
            cellProps={{ items, columnCount, gap, renderItem, itemKey }}
            columnCount={columnCount}
            columnWidth={columnWidth}
            rowCount={rowCount}
            rowHeight={rowHeight}
            defaultHeight={gridHeight}
            defaultWidth={width}
            overscanCount={2}
            style={{ height: gridHeight }}
          />
        )}
      </div>
    </div>
  );
}

function Cell({ ariaAttributes, columnIndex, rowIndex, style, items, columnCount, gap, renderItem, itemKey }) {
  const idx = rowIndex * columnCount + columnIndex;
  const item = items[idx];
  if (!item) return null;
  const inner = {
    ...style,
    padding: gap / 2,
    boxSizing: "border-box",
  };
  return (
    <div style={inner} {...ariaAttributes}>
      {renderItem(item, idx)}
    </div>
  );
}
