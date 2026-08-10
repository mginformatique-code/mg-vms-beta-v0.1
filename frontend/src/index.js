import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";
import ErrorBoundary from "@/components/ErrorBoundary";

// v0.7.g · Axe 10 · Robustesse frontend globale + v1.0-rc4.5 · Debug Panel :
// - compteurs discrets (visibles en DevTools et via le volet Ctrl+Shift+D)
// - ring buffer des 100 derniers événements (erreurs/rejections/window errors)
//   consulté par AppDebugPanel onglet "Réseau"
if (typeof window !== "undefined") {
  window.__mgvms_unhandled_rejections = 0;
  window.__mgvms_window_errors = 0;
  window.__mgvms_react_errors = 0;
  window.__mgvms_error_history = window.__mgvms_error_history || [];
  const HISTORY_MAX = 100;
  const _pushErr = (entry) => {
    window.__mgvms_error_history.push({ ts: new Date().toISOString(), ...entry });
    if (window.__mgvms_error_history.length > HISTORY_MAX) {
      window.__mgvms_error_history.splice(0, window.__mgvms_error_history.length - HISTORY_MAX);
    }
  };
  window.addEventListener("unhandledrejection", (e) => {
    window.__mgvms_unhandled_rejections += 1;
    const reason = e.reason;
    _pushErr({
      kind: "unhandledrejection",
      name: reason?.name || "UnhandledPromiseRejection",
      message: String(reason?.message || reason),
      stack: reason?.stack || null,
    });
    console.warn("[unhandledrejection]", e.reason);
  });
  window.addEventListener("error", (e) => {
    window.__mgvms_window_errors += 1;
    _pushErr({
      kind: "window.onerror",
      name: e.error?.name || "Error",
      message: String(e.message || e.error?.message || e),
      filename: e.filename || null,
      lineno: e.lineno || null,
      colno: e.colno || null,
    });
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
root.render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
