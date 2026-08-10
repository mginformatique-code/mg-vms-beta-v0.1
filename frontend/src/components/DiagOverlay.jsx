/**
 * DiagOverlay.jsx — DIAG-ONLY (v1.0-rc4.5 P0)
 *
 * Bandeau plein écran, non-supprimable via ErrorBoundary. Écoute :
 *   - window.__mgvms_diag_events (poussé par ErrorBoundary, api.js, index.js)
 *   - Se rafraîchit toutes les 500ms.
 * Affiche TOUTES les exceptions/rejections/axios errors capturées, avec
 * stack, componentStack, réponse Axios brute.
 *
 * À supprimer une fois le bug identifié.
 */
import React, { useEffect, useState } from "react";

export default function DiagOverlay() {
  const [events, setEvents] = useState([]);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.__mgvms_diag_events = window.__mgvms_diag_events || [];
    const iv = setInterval(() => {
      const arr = window.__mgvms_diag_events || [];
      setEvents(arr.slice(-30));
    }, 500);
    return () => clearInterval(iv);
  }, []);

  const copy = () => {
    try {
      const payload = JSON.stringify(
        (window.__mgvms_diag_events || []).slice(-30),
        null,
        2
      );
      navigator.clipboard?.writeText(payload);
    } catch (e) {
      /* ignore */
    }
  };

  const clear = () => {
    window.__mgvms_diag_events = [];
    setEvents([]);
  };

  if (events.length === 0) return null;

  const style = {
    position: "fixed",
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 2147483647,
    background: "#0a0a0a",
    color: "#ff6b6b",
    borderTop: "2px solid #ff3333",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "11px",
    maxHeight: collapsed ? "40px" : "45vh",
    overflow: "hidden",
    boxShadow: "0 -4px 24px rgba(255,51,51,0.4)",
  };

  const headerStyle = {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "6px 10px",
    background: "#1a0a0a",
    borderBottom: "1px solid #ff3333",
    color: "#ffcccc",
  };

  const btnStyle = {
    background: "#ff3333",
    color: "#000",
    border: "none",
    padding: "3px 8px",
    fontWeight: "bold",
    fontSize: "10px",
    cursor: "pointer",
  };

  const bodyStyle = {
    padding: "8px 10px",
    overflow: "auto",
    maxHeight: "calc(45vh - 40px)",
  };

  return (
    <div style={style} data-testid="mgvms-diag-overlay">
      <div style={headerStyle}>
        <strong style={{ color: "#ff3333" }}>
          🚨 MG-VMS DIAG ({events.length} event{events.length > 1 ? "s" : ""})
        </strong>
        <button style={btnStyle} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? "▲ Ouvrir" : "▼ Réduire"}
        </button>
        <button style={btnStyle} onClick={copy}>
          📋 Copier JSON
        </button>
        <button style={btnStyle} onClick={clear}>
          ✕ Vider
        </button>
        <span style={{ marginLeft: "auto", color: "#888", fontSize: "10px" }}>
          Root cause · v1.0-rc4.5 · à retirer après diagnostic
        </span>
      </div>
      {!collapsed && (
        <div style={bodyStyle}>
          {events
            .slice()
            .reverse()
            .map((ev, i) => (
              <div
                key={i}
                style={{
                  borderBottom: "1px dashed #442222",
                  padding: "6px 0",
                  marginBottom: "4px",
                }}
              >
                <div style={{ color: "#ffaa00", fontWeight: "bold" }}>
                  [{ev.ts}] {ev.kind} — {ev.name || ""} : {ev.message}
                </div>
                {ev.filename && (
                  <div style={{ color: "#8ff" }}>
                    file: {ev.filename}:{ev.lineno}:{ev.colno}
                  </div>
                )}
                {ev.axios && (
                  <details style={{ marginTop: "4px" }}>
                    <summary style={{ cursor: "pointer", color: "#ffcc00" }}>
                      Axios detail ({ev.axios.method?.toUpperCase()}{" "}
                      {ev.axios.url} → {ev.axios.status ?? "no-response"})
                    </summary>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        color: "#ccc",
                        margin: "4px 0 0",
                      }}
                    >
                      {JSON.stringify(ev.axios, null, 2)}
                    </pre>
                  </details>
                )}
                {ev.stack && (
                  <details style={{ marginTop: "4px" }}>
                    <summary style={{ cursor: "pointer", color: "#ff8888" }}>
                      Stack trace
                    </summary>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        color: "#ff8888",
                        margin: "4px 0 0",
                      }}
                    >
                      {ev.stack}
                    </pre>
                  </details>
                )}
                {ev.componentStack && (
                  <details style={{ marginTop: "4px" }}>
                    <summary style={{ cursor: "pointer", color: "#88ccff" }}>
                      React component stack
                    </summary>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        color: "#88ccff",
                        margin: "4px 0 0",
                      }}
                    >
                      {ev.componentStack}
                    </pre>
                  </details>
                )}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

/**
 * Helper global pour pousser un event dans l'overlay.
 * Utilisable depuis n'importe quel fichier (importer diagPush).
 */
export function diagPush(ev) {
  if (typeof window === "undefined") return;
  window.__mgvms_diag_events = window.__mgvms_diag_events || [];
  const entry = {
    ts: new Date().toISOString().slice(11, 23),
    ...ev,
  };
  window.__mgvms_diag_events.push(entry);
  console.error("[MG-VMS DIAG]", entry);
}
