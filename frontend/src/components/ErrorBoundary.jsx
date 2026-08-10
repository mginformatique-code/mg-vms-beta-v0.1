/**
 * ErrorBoundary.jsx — v0.7.g · Axe 10 · Robustesse frontend globale.
 *
 * Attrape TOUTE erreur React qui remonte jusqu'à la racine sans être
 * captée par un Suspense/try local. Affiche un fallback sobre + logue
 * dans window.__mgvms_perf.
 */
import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    this.setState({ info });
    try {
      // Push dans le compteur perf pour visibilité DevTools
      const perf = typeof window !== "undefined" ? window.__mgvms_perf : null;
      if (perf) {
        window.__mgvms_react_errors = (window.__mgvms_react_errors || 0) + 1;
      }
      // eslint-disable-next-line no-console
      console.error("[ErrorBoundary]", error, info?.componentStack);
    } catch (e) { /* ignore logging failures */ }
  }
  reset = () => this.setState({ error: null, info: null });
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-[60vh] flex items-center justify-center p-8" data-testid="error-boundary">
          <div className="max-w-lg border border-[#FF3333]/40 bg-[#FF3333]/5 p-6 space-y-3">
            <div className="text-[10px] uppercase tracking-[0.15em] text-[#FF3333]">Erreur inattendue</div>
            <h2 className="font-head font-black text-xl">Cette section a rencontré un problème.</h2>
            <div className="text-xs text-muted-foreground">
              L&apos;erreur a été isolée : le reste de l&apos;application continue à fonctionner.
              Les autres onglets et la boucle IA ne sont pas impactés.
            </div>
            <details className="text-[10px] mono opacity-70">
              <summary className="cursor-pointer">Détail technique</summary>
              <pre className="whitespace-pre-wrap mt-2 text-[10px]">{String(this.state.error?.message || this.state.error)}</pre>
            </details>
            <div className="flex gap-2 pt-2">
              <button onClick={this.reset} className="border border-border px-3 py-2 text-xs hover:bg-secondary/50" data-testid="error-boundary-retry">
                Réessayer
              </button>
              <button onClick={() => window.location.reload()} className="border border-[#FF3333] text-[#FF3333] px-3 py-2 text-xs hover:bg-[#FF3333]/10" data-testid="error-boundary-reload">
                Recharger la page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
