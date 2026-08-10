/**
 * AppDebugPanel — Volet debug app-level MG-VMS v1.0-rc4.5
 *
 * ACTIVATION : Ctrl+Shift+D (fermeture Escape ou même combo)
 * ACCÈS      : administrateurs uniquement (user.role === "admin")
 *
 * 3 onglets (aucun contenu caméra) :
 *   1. Session      → user, rôles, JWT expiry, refresh token, WS, compteurs erreurs
 *   2. Navigation   → route, params, contexte AppProvider, chunks chargés
 *   3. Build/Deploy → REACT_APP_BACKEND_URL, bundle, HTTPS, hostname, backend health
 *
 * READ-ONLY. Rien de persistant. Aucune action destructive.
 * Panneau STRICTEMENT invisible tant que Ctrl+Shift+D n'est pas pressé.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";

function decodeJwt(token) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload;
  } catch (e) {
    return null;
  }
}

async function timeIt(fn) {
  const t0 = performance.now();
  try {
    const value = await fn();
    return { ok: true, ms: Math.round(performance.now() - t0), value };
  } catch (e) {
    return {
      ok: false, ms: Math.round(performance.now() - t0),
      error: e?.response?.status ? `HTTP ${e.response.status}` : e?.message || String(e),
      body: e?.response?.data,
    };
  }
}

export default function AppDebugPanel() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("session");
  const [results, setResults] = useState({});
  const [running, setRunning] = useState({});
  const [netRefresh, setNetRefresh] = useState(0);
  const { user, lang, theme } = useApp() || {};
  const location = useLocation();
  const params = useParams();

  // ─── Auto-refresh onglet Réseau (500ms tant que ouvert) ──────────
  useEffect(() => {
    if (!open || tab !== "network") return;
    const iv = setInterval(() => setNetRefresh((n) => n + 1), 500);
    return () => clearInterval(iv);
  }, [open, tab]);

  // ─── Raccourci clavier ───────────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      const isToggle = e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d");
      if (isToggle) { e.preventDefault(); setOpen((v) => !v); }
      else if (open && e.key === "Escape") { setOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // ─── Guard admin ─────────────────────────────────────────────────
  const isAdmin = user && typeof user === "object" && user.role === "admin";

  // ─── Info dérivées mémoïsées ─────────────────────────────────────
  const jwt = useMemo(() => {
    const token = localStorage.getItem("mg_token");
    if (!token) return null;
    const payload = decodeJwt(token);
    if (!payload) return { raw_length: token.length, decoded: false };
    const now = Math.floor(Date.now() / 1000);
    return {
      sub: payload.sub, role: payload.role, email: payload.email,
      iat: payload.iat ? new Date(payload.iat * 1000).toISOString() : null,
      exp: payload.exp ? new Date(payload.exp * 1000).toISOString() : null,
      expires_in_s: payload.exp ? payload.exp - now : null,
      expired: payload.exp ? payload.exp < now : null,
    };
  }, [open]); // rafraîchit à chaque ouverture

  const perfCounters = useMemo(() => ({
    unhandled_rejections: window.__mgvms_unhandled_rejections || 0,
    window_errors: window.__mgvms_window_errors || 0,
    react_errors: window.__mgvms_react_errors || 0,
  }), [open]);

  // ─── Test runners app-level ──────────────────────────────────────
  const run = useCallback(async (key, fn) => {
    setRunning((r) => ({ ...r, [key]: true }));
    const res = await timeIt(fn);
    setResults((s) => ({ ...s, [key]: res }));
    setRunning((r) => ({ ...r, [key]: false }));
  }, []);

  const runAuthMe = () => run("auth_me", async () => (await api.get("/auth/me")).data);
  const runSystemHealth = () => run("system_health", async () => (await api.get("/system-health")).data);
  const runPublicStatus = () => run("public_status", async () => (await api.get("/system/public-status")).data);
  const runBackendReachable = () => run("backend_reachable", async () => {
    const r = await fetch(`${process.env.REACT_APP_BACKEND_URL || ""}/api/system/public-status`);
    return { status: r.status, ok: r.ok, headers: Object.fromEntries(r.headers.entries()) };
  });

  const runAll = async () => {
    await runAuthMe();
    await runSystemHealth();
    await runPublicStatus();
    await runBackendReachable();
  };

  // ─── Rapport texte ───────────────────────────────────────────────
  const buildReport = () => {
    const now = new Date().toISOString();
    const env = {
      time: now,
      href: window.location.href, origin: window.location.origin,
      protocol: window.location.protocol, host: window.location.host,
      user_agent: navigator.userAgent,
      react_app_backend_url: process.env.REACT_APP_BACKEND_URL || "(empty — relative /api)",
      node_env: process.env.NODE_ENV,
    };
    const nav = {
      pathname: location.pathname, search: location.search, hash: location.hash,
      params, state: location.state,
    };
    const ctx = { user, lang, theme };
    const parts = [
      "═══════════════════════════════════════════════════════════",
      "  MG-VMS · App Debug Report v1.0-rc4.5",
      "═══════════════════════════════════════════════════════════",
      "",
      "── SESSION ─────────────────────────────────────────",
      JSON.stringify({ jwt, ctx, perf_counters: perfCounters }, null, 2),
      "",
      "── NAVIGATION ──────────────────────────────────────",
      JSON.stringify(nav, null, 2),
      "",
      "── BUILD / ENV ─────────────────────────────────────",
      JSON.stringify(env, null, 2),
      "",
      "── RÉSEAU (derniers 40 appels axios) ────────────────",
      JSON.stringify(((typeof window !== "undefined" && window.__mgvms_axios_history) || []).slice(-40), null, 2),
      "",
      "── ERREURS JS (dernières 20) ────────────────────────",
      JSON.stringify(((typeof window !== "undefined" && window.__mgvms_error_history) || []).slice(-20), null, 2),
      "",
      "── API PROBES ──────────────────────────────────────",
    ];
    for (const [key, res] of Object.entries(results)) {
      parts.push(`▸ ${key} (${res.ms}ms · ${res.ok ? "OK" : "FAIL"})`);
      parts.push(res.ok ? JSON.stringify(res.value, null, 2) : `ERROR: ${res.error}\n${JSON.stringify(res.body, null, 2)}`);
      parts.push("");
    }
    return parts.join("\n");
  };

  const copyReport = async () => {
    try { await navigator.clipboard.writeText(buildReport()); }
    catch (e) { /* silent */ }
  };

  if (!open) return null;

  // ─── UI ──────────────────────────────────────────────────────────
  const panelStyle = {
    position: "fixed", top: 0, right: 0, bottom: 0,
    width: "min(720px, 100vw)", zIndex: 2147483646,
    background: "#0a0a0a", color: "#ddd",
    borderLeft: "2px solid #00E5FF",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "12px",
    display: "flex", flexDirection: "column",
    boxShadow: "-8px 0 32px rgba(0,229,255,0.15)",
  };
  const headerStyle = {
    padding: "10px 14px", borderBottom: "1px solid #00E5FF33",
    display: "flex", alignItems: "center", gap: "12px", background: "#001a1a",
  };
  const tabBtn = (id, label) => (
    <button
      key={id}
      onClick={() => setTab(id)}
      style={{
        padding: "4px 10px",
        border: `1px solid ${tab === id ? "#00E5FF" : "#333"}`,
        background: tab === id ? "#00E5FF15" : "transparent",
        color: tab === id ? "#00E5FF" : "#888",
        fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.1em",
        cursor: "pointer",
      }}
      data-testid={`app-dbg-tab-${id}`}
    >{label}</button>
  );
  const kv = (k, v, testid) => (
    <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", padding: "3px 0", borderBottom: "1px dashed #222", gap: "8px" }}>
      <span style={{ color: "#888", fontSize: "10px", textTransform: "uppercase" }}>{k}</span>
      <span style={{ color: "#ddd", fontSize: "11px", wordBreak: "break-all" }} data-testid={testid}>
        {v == null ? <span style={{ color: "#555" }}>—</span> : typeof v === "object" ? JSON.stringify(v) : String(v)}
      </span>
    </div>
  );
  const btn = (label, onClick, testid, disabled = false) => (
    <button
      onClick={onClick} disabled={disabled}
      style={{
        padding: "5px 12px", border: "1px solid #00E5FF",
        background: "transparent", color: "#00E5FF",
        fontSize: "11px", cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
      }}
      data-testid={testid}
    >{label}</button>
  );
  const resultBlock = (key) => {
    const r = results[key];
    if (running[key]) return <pre style={{ color: "#888" }}>… running …</pre>;
    if (!r) return <pre style={{ color: "#555" }}>(non exécuté)</pre>;
    return (
      <pre style={{
        color: r.ok ? "#8f8" : "#f88", background: "#111", padding: "8px", margin: "4px 0",
        maxHeight: "35vh", overflow: "auto", fontSize: "10px",
        whiteSpace: "pre-wrap", wordBreak: "break-all",
      }}>
        {`[${r.ms}ms · ${r.ok ? "OK" : "FAIL"}]\n`}
        {r.ok ? JSON.stringify(r.value, null, 2) : `${r.error}\n${JSON.stringify(r.body, null, 2)}`}
      </pre>
    );
  };

  // ─── Guard admin ─────────────────────────────────────────────────
  if (!isAdmin) {
    return (
      <div style={panelStyle} data-testid="app-debug-panel">
        <div style={headerStyle}>
          <strong style={{ color: "#00E5FF" }}>🛠 MG-VMS App Debug</strong>
          <div style={{ flex: 1 }} />
          <button onClick={() => setOpen(false)} style={{ border: "1px solid #555", background: "transparent", color: "#aaa", padding: "3px 8px", cursor: "pointer" }} data-testid="app-dbg-close">✕</button>
        </div>
        <div style={{ padding: "40px", textAlign: "center", color: "#ff6666" }} data-testid="app-dbg-forbidden">
          <div style={{ fontSize: "48px", marginBottom: "16px" }}>🔒</div>
          <div style={{ fontSize: "14px", marginBottom: "8px", fontWeight: "bold" }}>Accès administrateur requis</div>
          <div style={{ color: "#888", fontSize: "11px" }}>
            Ce volet n'est disponible que pour les comptes avec le rôle « admin ».<br />
            Votre rôle actuel : <code>{user?.role || "(non authentifié)"}</code>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={panelStyle} data-testid="app-debug-panel" role="dialog" aria-label="App Debug Panel">
      <div style={headerStyle}>
        <strong style={{ color: "#00E5FF" }}>🛠 MG-VMS App Debug</strong>
        <span style={{ color: "#666", fontSize: "10px" }}>v1.0-rc4.5 · admin</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "6px" }}>
          {tabBtn("session", "Session")}
          {tabBtn("network", "Réseau")}
          {tabBtn("navigation", "Navigation")}
          {tabBtn("build", "Build")}
        </div>
        <button onClick={() => setOpen(false)} style={{ border: "1px solid #555", background: "transparent", color: "#aaa", padding: "3px 8px", cursor: "pointer" }} data-testid="app-dbg-close" title="Fermer (Escape)">✕</button>
      </div>

      <div style={{ padding: "10px 14px", borderBottom: "1px solid #222", display: "flex", gap: "8px", flexWrap: "wrap" }}>
        {btn("▶ Sonder tout", runAll, "app-dbg-run-all")}
        {btn("📋 Copier rapport", copyReport, "app-dbg-copy-report")}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "12px 14px" }}>
        {tab === "session" && (
          <div data-testid="app-dbg-panel-session">
            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: "4px" }}>Utilisateur</div>
            {kv("email", user?.email, "session-email")}
            {kv("role", user?.role, "session-role")}
            {kv("permissions", user?.permissions, "session-perms")}
            {kv("mfa_enabled", user?.mfa_enabled, "session-mfa")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>JWT</div>
            {kv("sub", jwt?.sub, "jwt-sub")}
            {kv("role (jwt)", jwt?.role, "jwt-role")}
            {kv("iat", jwt?.iat, "jwt-iat")}
            {kv("exp", jwt?.exp, "jwt-exp")}
            {kv("expires in", jwt?.expires_in_s != null ? `${jwt.expires_in_s} s` : null, "jwt-expires-in")}
            {kv("expired", jwt?.expired, "jwt-expired")}
            {kv("refresh token present", !!localStorage.getItem("mg_refresh"), "refresh-present")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Compteurs erreurs (session)</div>
            {kv("unhandled promise rejections", perfCounters.unhandled_rejections, "err-unhandled")}
            {kv("window.onerror", perfCounters.window_errors, "err-window")}
            {kv("React ErrorBoundary caught", perfCounters.react_errors, "err-react")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Probes</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginBottom: "8px" }}>
              {btn("GET /auth/me", runAuthMe, "run-auth-me", running.auth_me)}
              {btn("GET /system-health", runSystemHealth, "run-system-health", running.system_health)}
            </div>
            {results.auth_me && <><div style={{ fontSize: "10px", color: "#888" }}>auth/me</div>{resultBlock("auth_me")}</>}
            {results.system_health && <><div style={{ fontSize: "10px", color: "#888" }}>system-health</div>{resultBlock("system_health")}</>}
          </div>
        )}

        {tab === "network" && (() => {
          // Ring buffers alimentés par api.js (axios) et index.js (window errors)
          const axiosHistory = (typeof window !== "undefined" && window.__mgvms_axios_history) || [];
          const errorHistory = (typeof window !== "undefined" && window.__mgvms_error_history) || [];
          const last = axiosHistory.slice(-40).reverse();
          const errs = errorHistory.slice(-20).reverse();
          const stats = axiosHistory.reduce((acc, e) => {
            acc.total += 1;
            if (e.kind === "error") acc.errors += 1;
            if (e.status >= 500) acc.status5xx += 1;
            else if (e.status >= 400) acc.status4xx += 1;
            else if (e.status >= 200 && e.status < 300) acc.status2xx += 1;
            if (e.duration_ms != null) { acc.total_ms += e.duration_ms; acc.timed += 1; }
            return acc;
          }, { total: 0, errors: 0, status2xx: 0, status4xx: 0, status5xx: 0, total_ms: 0, timed: 0 });
          const avgMs = stats.timed > 0 ? Math.round(stats.total_ms / stats.timed) : null;
          const statusColor = (s) => {
            if (s == null) return "#f88";
            if (s >= 500) return "#f66";
            if (s >= 400) return "#fa0";
            if (s >= 300) return "#f8f";
            if (s >= 200) return "#8f8";
            return "#888";
          };
          const clearBuffers = () => {
            if (typeof window !== "undefined") {
              window.__mgvms_axios_history = [];
              window.__mgvms_error_history = [];
              window.__mgvms_unhandled_rejections = 0;
              window.__mgvms_window_errors = 0;
              window.__mgvms_react_errors = 0;
              setNetRefresh((n) => n + 1);
            }
          };
          return (
            <div data-testid="app-dbg-panel-network">
              <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: "4px" }}>
                Résumé requêtes (refresh live 500 ms)
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "6px", marginBottom: "10px", fontSize: "10px" }}>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>total</div>
                  <div style={{ fontSize: "14px", color: "#ddd" }} data-testid="net-stat-total">{stats.total}</div>
                </div>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>2xx</div>
                  <div style={{ fontSize: "14px", color: "#8f8" }} data-testid="net-stat-2xx">{stats.status2xx}</div>
                </div>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>4xx</div>
                  <div style={{ fontSize: "14px", color: "#fa0" }} data-testid="net-stat-4xx">{stats.status4xx}</div>
                </div>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>5xx</div>
                  <div style={{ fontSize: "14px", color: "#f66" }} data-testid="net-stat-5xx">{stats.status5xx}</div>
                </div>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>network err.</div>
                  <div style={{ fontSize: "14px", color: "#f66" }} data-testid="net-stat-errors">{stats.errors}</div>
                </div>
                <div style={{ padding: "6px", background: "#111", border: "1px solid #333" }}>
                  <div style={{ color: "#888", fontSize: "9px", textTransform: "uppercase" }}>lat. moy.</div>
                  <div style={{ fontSize: "14px", color: "#ddd" }} data-testid="net-stat-avg">{avgMs != null ? `${avgMs} ms` : "—"}</div>
                </div>
              </div>
              <div style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
                {btn("↻ Rafraîchir", () => setNetRefresh((n) => n + 1), "net-refresh")}
                {btn("🗑 Vider buffers", clearBuffers, "net-clear")}
              </div>

              <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "12px", marginBottom: "4px" }}>
                Derniers appels axios ({last.length}/{axiosHistory.length}) — refresh #{netRefresh}
              </div>
              <div style={{ background: "#111", border: "1px solid #222", maxHeight: "40vh", overflow: "auto" }}>
                {last.length === 0 && (
                  <div style={{ padding: "16px", color: "#555", fontSize: "11px", textAlign: "center" }}>Aucun appel enregistré (naviguez dans l'app pour peupler)</div>
                )}
                {last.map((e, i) => (
                  <div key={i} style={{ padding: "5px 8px", borderBottom: "1px dashed #222", fontSize: "10px", display: "grid", gridTemplateColumns: "70px 55px 40px 60px 1fr", gap: "6px", alignItems: "center" }}>
                    <span style={{ color: "#666" }}>{e.ts.slice(11, 23)}</span>
                    <span style={{ color: e.kind === "error" ? "#f66" : "#aaa", fontWeight: "bold" }}>{e.method}</span>
                    <span style={{ color: statusColor(e.status), fontWeight: "bold" }}>{e.status ?? "—"}</span>
                    <span style={{ color: "#888" }}>{e.duration_ms != null ? `${e.duration_ms}ms` : "—"}</span>
                    <span style={{ color: "#ddd", wordBreak: "break-all" }}>
                      {e.url}
                      {e.code && <span style={{ color: "#f66", marginLeft: "6px" }}>· {e.code}</span>}
                      {e.message && e.kind === "error" && <span style={{ color: "#faa", marginLeft: "6px" }}>· {e.message}</span>}
                    </span>
                  </div>
                ))}
              </div>

              <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>
                Erreurs JS globales ({errs.length}/{errorHistory.length})
              </div>
              <div style={{ background: "#111", border: "1px solid #222", maxHeight: "25vh", overflow: "auto" }}>
                {errs.length === 0 && (
                  <div style={{ padding: "16px", color: "#555", fontSize: "11px", textAlign: "center" }}>Aucune erreur JS ni promise rejection · ✅</div>
                )}
                {errs.map((e, i) => (
                  <div key={i} style={{ padding: "6px 8px", borderBottom: "1px dashed #222", fontSize: "10px" }}>
                    <div style={{ color: "#f88" }}>
                      <span style={{ color: "#666" }}>{e.ts.slice(11, 23)}</span>{" "}
                      <span style={{ color: "#fa0", fontWeight: "bold" }}>{e.kind}</span>{" "}
                      <span style={{ color: "#ddd" }}>{e.name}</span>
                    </div>
                    <div style={{ color: "#f88", marginLeft: "8px" }}>{e.message}</div>
                    {(e.filename || e.lineno) && (
                      <div style={{ color: "#888", marginLeft: "8px", fontSize: "9px" }}>
                        {e.filename}:{e.lineno}:{e.colno}
                      </div>
                    )}
                    {e.stack && (
                      <details style={{ marginLeft: "8px", marginTop: "3px" }}>
                        <summary style={{ cursor: "pointer", color: "#a88", fontSize: "9px" }}>Stack</summary>
                        <pre style={{ color: "#f88", fontSize: "9px", whiteSpace: "pre-wrap" }}>{e.stack}</pre>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

        {tab === "navigation" && (
          <div data-testid="app-dbg-panel-navigation">
            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: "4px" }}>Route courante</div>
            {kv("pathname", location.pathname, "nav-pathname")}
            {kv("search", location.search, "nav-search")}
            {kv("hash", location.hash, "nav-hash")}
            {kv("state", location.state, "nav-state")}
            {kv("params", params, "nav-params")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Contexte AppProvider</div>
            {kv("user (résumé)", user ? { email: user.email, role: user.role } : user, "ctx-user")}
            {kv("lang", lang, "ctx-lang")}
            {kv("theme", theme, "ctx-theme")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Storage local</div>
            {kv("keys", Object.keys(localStorage), "ls-keys")}
            {kv("mg_lang", localStorage.getItem("mg_lang"), "ls-lang")}
            {kv("mg_theme", localStorage.getItem("mg_theme"), "ls-theme")}
          </div>
        )}

        {tab === "build" && (
          <div data-testid="app-dbg-panel-build">
            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: "4px" }}>Environnement navigateur</div>
            {kv("href", window.location.href, "env-href")}
            {kv("origin", window.location.origin, "env-origin")}
            {kv("protocol", window.location.protocol, "env-protocol")}
            {kv("host", window.location.host, "env-host")}
            {kv("hostname", window.location.hostname, "env-hostname")}
            {kv("port", window.location.port || "(défaut)", "env-port")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Build React</div>
            {kv("NODE_ENV", process.env.NODE_ENV, "env-node")}
            {kv("REACT_APP_BACKEND_URL", process.env.REACT_APP_BACKEND_URL || "(empty → /api relatif)", "env-backend")}
            {kv("axios baseURL effective", `${process.env.REACT_APP_BACKEND_URL || ""}/api`, "env-axios")}

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>User Agent</div>
            <div style={{ color: "#ddd", fontSize: "11px", padding: "4px 0", wordBreak: "break-all" }}>{navigator.userAgent}</div>

            <div style={{ color: "#00E5FF", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: "16px", marginBottom: "4px" }}>Probes backend</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginBottom: "8px" }}>
              {btn("GET /system/public-status", runPublicStatus, "run-public-status", running.public_status)}
              {btn("HEAD backend (fetch direct)", runBackendReachable, "run-backend-reachable", running.backend_reachable)}
            </div>
            {results.public_status && <><div style={{ fontSize: "10px", color: "#888" }}>public-status</div>{resultBlock("public_status")}</>}
            {results.backend_reachable && <><div style={{ fontSize: "10px", color: "#888" }}>backend reachable</div>{resultBlock("backend_reachable")}</>}
          </div>
        )}
      </div>

      <div style={{ padding: "6px 14px", borderTop: "1px solid #222", color: "#555", fontSize: "10px", textAlign: "center" }}>
        Ctrl+Shift+D pour basculer · Escape pour fermer · Admin uniquement · Read-only
      </div>
    </div>
  );
}
