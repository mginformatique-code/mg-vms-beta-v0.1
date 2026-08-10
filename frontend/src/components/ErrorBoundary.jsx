/**
 * ErrorBoundary.jsx — DIAG-MODE v1.0-rc4.5 P0
 *
 * ⚠️ Instrumentation temporaire : affiche TOUTE l'exception React brute
 * (message, name, stack, componentStack) au lieu du message générique.
 * À restaurer à la version sobre une fois la cause racine identifiée.
 */
import React from "react";
import { diagPush } from "./DiagOverlay";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    this.setState({ info });
    try {
      const perf = typeof window !== "undefined" ? window.__mgvms_perf : null;
      if (perf) {
        window.__mgvms_react_errors = (window.__mgvms_react_errors || 0) + 1;
      }
      diagPush({
        kind: "react-error-boundary",
        name: error?.name || "Error",
        message: String(error?.message || error),
        stack: error?.stack || null,
        componentStack: info?.componentStack || null,
      });
      console.error("[ErrorBoundary]", error, info?.componentStack);
    } catch (e) {
      /* ignore logging failures */
    }
  }
  reset = () => this.setState({ error: null, info: null });
  render() {
    if (this.state.error) {
      const err = this.state.error;
      const info = this.state.info;
      const payload = {
        name: err?.name,
        message: err?.message,
        stack: err?.stack,
        componentStack: info?.componentStack,
        toString: String(err),
      };
      return (
        <div
          style={{
            minHeight: "60vh",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            padding: "24px",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          }}
          data-testid="error-boundary"
        >
          <div
            style={{
              maxWidth: "1100px",
              width: "100%",
              border: "2px solid #ff3333",
              background: "#1a0a0a",
              color: "#ffcccc",
              padding: "20px",
              fontSize: "12px",
            }}
          >
            <div
              style={{
                fontSize: "10px",
                textTransform: "uppercase",
                letterSpacing: "0.15em",
                color: "#ff3333",
                marginBottom: "6px",
              }}
            >
              🚨 React ErrorBoundary — DIAG MODE
            </div>
            <h2 style={{ fontSize: "18px", fontWeight: "bold", margin: "0 0 12px" }}>
              {err?.name || "Error"} : {String(err?.message || err)}
            </h2>
            <div style={{ marginBottom: "10px", color: "#ffff88" }}>
              Voir aussi le bandeau rouge en bas (MG-VMS DIAG) + console DevTools.
            </div>
            <details open>
              <summary style={{ cursor: "pointer", color: "#ff8888" }}>
                Stack trace (JS)
              </summary>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  color: "#ff8888",
                  background: "#000",
                  padding: "10px",
                  marginTop: "6px",
                  fontSize: "11px",
                  overflow: "auto",
                }}
              >
                {payload.stack || "(aucune stack)"}
              </pre>
            </details>
            <details open style={{ marginTop: "10px" }}>
              <summary style={{ cursor: "pointer", color: "#88ccff" }}>
                React component stack (composant fautif)
              </summary>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  color: "#88ccff",
                  background: "#000",
                  padding: "10px",
                  marginTop: "6px",
                  fontSize: "11px",
                  overflow: "auto",
                }}
              >
                {payload.componentStack || "(aucun componentStack)"}
              </pre>
            </details>
            <details style={{ marginTop: "10px" }}>
              <summary style={{ cursor: "pointer", color: "#cccccc" }}>
                Payload JSON complet (copier/coller pour l&apos;agent)
              </summary>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  color: "#ccc",
                  background: "#000",
                  padding: "10px",
                  marginTop: "6px",
                  fontSize: "10px",
                  overflow: "auto",
                }}
              >
                {JSON.stringify(payload, null, 2)}
              </pre>
            </details>
            <div style={{ display: "flex", gap: "8px", paddingTop: "12px" }}>
              <button
                onClick={this.reset}
                style={{
                  border: "1px solid #666",
                  background: "transparent",
                  color: "#ccc",
                  padding: "8px 14px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
                data-testid="error-boundary-retry"
              >
                Réessayer
              </button>
              <button
                onClick={() => window.location.reload()}
                style={{
                  border: "1px solid #ff3333",
                  background: "transparent",
                  color: "#ff3333",
                  padding: "8px 14px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
                data-testid="error-boundary-reload"
              >
                Recharger la page
              </button>
              <button
                onClick={() => {
                  try {
                    navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
                  } catch (e) { /* ignore */ }
                }}
                style={{
                  border: "1px solid #ffcc00",
                  background: "transparent",
                  color: "#ffcc00",
                  padding: "8px 14px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
              >
                📋 Copier le rapport
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
