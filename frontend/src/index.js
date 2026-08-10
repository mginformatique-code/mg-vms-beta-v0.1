import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";
import ErrorBoundary from "@/components/ErrorBoundary";
import DiagOverlay, { diagPush } from "@/components/DiagOverlay";

// ─── DIAG-MODE v1.0-rc4.5 P0 ────────────────────────────────────────
// Handlers globaux : captent TOUTE exception / rejection non gérée AVANT
// même que React n'ait fini de monter. Poussés dans window.__mgvms_diag_events
// et affichés en overlay rouge permanent + console.
if (typeof window !== "undefined") {
  window.__mgvms_unhandled_rejections = 0;
  window.__mgvms_window_errors = 0;
  window.__mgvms_react_errors = 0;
  window.__mgvms_diag_events = window.__mgvms_diag_events || [];

  window.addEventListener("unhandledrejection", (e) => {
    window.__mgvms_unhandled_rejections += 1;
    const reason = e.reason;
    diagPush({
      kind: "unhandledrejection",
      name: reason?.name || "UnhandledPromiseRejection",
      message: String(reason?.message || reason),
      stack: reason?.stack || null,
      axios: reason?.__mgvms_axios || null,
    });
  });

  window.addEventListener("error", (e) => {
    window.__mgvms_window_errors += 1;
    diagPush({
      kind: "window.onerror",
      name: e.error?.name || "Error",
      message: String(e.message || e.error?.message || e),
      filename: e.filename || null,
      lineno: e.lineno || null,
      colno: e.colno || null,
      stack: e.error?.stack || null,
    });
  });

  // Log boot markers (utile pour savoir si React monte du tout)
  diagPush({
    kind: "boot",
    name: "index.js",
    message: `React root render start · UA=${navigator.userAgent.slice(0, 80)} · href=${window.location.href}`,
  });
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));

// v1.0-rc4.5 P0 · DiagOverlay est monté HORS ErrorBoundary et HORS
// providers pour survivre à tout crash React. Il ne dépend d'aucun
// contexte.
root.render(
  <React.StrictMode>
    <>
      <DiagOverlay />
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ErrorBoundary>
    </>
  </React.StrictMode>,
);

// Ping post-render (si on arrive ici sans avoir déclenché d'exception synchrone)
if (typeof window !== "undefined") {
  setTimeout(() => {
    diagPush({
      kind: "boot",
      name: "post-render",
      message: "React root render completed (T+0ms). Aucun crash synchrone.",
    });
  }, 0);
}
