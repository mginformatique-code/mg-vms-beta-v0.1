import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";
import ErrorBoundary from "@/components/ErrorBoundary";

// v0.7.g · Axe 10 · Robustesse frontend globale — handler pour toutes les
// promesses rejetées non captées (fetch/API errors, race conditions dans
// des useEffect qui n'ont pas de try/catch). Un tracker discret + log console
// évite qu'une petite erreur async plante la page silencieusement.
if (typeof window !== "undefined") {
  // Initialisation compteurs (visibles dès l'ouverture en DevTools/tests)
  window.__mgvms_unhandled_rejections = 0;
  window.__mgvms_window_errors = 0;
  window.__mgvms_react_errors = 0;
  window.addEventListener("unhandledrejection", (e) => {
    window.__mgvms_unhandled_rejections += 1;
    // eslint-disable-next-line no-console
    console.warn("[unhandledrejection]", e.reason);
  });
  window.addEventListener("error", () => {
    window.__mgvms_window_errors += 1;
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
