/**
 * DebugPanel — Volet de diagnostic caché v1.0-rc4.5
 *
 * ACTIVATION : Ctrl+Shift+D (ou Escape/même combo pour fermer).
 *
 * Panneau SLIDE-IN à droite, invisible par défaut. Ne pollue jamais l'UI
 * normale. Fournit les 5 tests terrain de l'audit v1.0-rc4.5 en 1 clic :
 *   1. Backend health (/api/health, /api/system/public-status)
 *   2. Go2RTC state (/api/streams, /api/config, version)
 *   3. WebRTC SDP test (offer → answer avec candidates réels)
 *   4. Session/env (URL, backend base, token expiry, axios interceptor state)
 *   5. Rapport texte complet · copier/coller pour transmission
 *
 * Aucune UI de production ajoutée. Aucune donnée persistée.
 * À masquer par défaut. Ne s'affiche QUE si Ctrl+Shift+D pressé.
 */
import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";

const SDP_OFFER_TEMPLATE = `v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\nc=IN IP4 0.0.0.0\r\na=rtcp-mux\r\na=setup:actpass\r\na=mid:0\r\na=recvonly\r\na=rtpmap:96 H264/90000\r\na=ice-ufrag:test\r\na=ice-pwd:testtesttesttesttest\r\na=fingerprint:sha-256 00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00\r\n`;

function extractIceCandidates(sdp) {
  if (!sdp || typeof sdp !== "string") return [];
  return sdp.split(/\r?\n/).filter((l) => l.startsWith("a=candidate:"));
}

function decodeJwtExp(token) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.exp ? new Date(payload.exp * 1000).toISOString() : null;
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

export default function DebugPanel() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("summary");
  const [results, setResults] = useState({});
  const [running, setRunning] = useState({});
  const [camId, setCamId] = useState("");
  const [cams, setCams] = useState([]);

  // Raccourci clavier global : Ctrl+Shift+D
  useEffect(() => {
    const onKey = (e) => {
      const isToggle = e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d");
      if (isToggle) { e.preventDefault(); setOpen((v) => !v); }
      else if (open && e.key === "Escape") { setOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Charger la liste des caméras à l'ouverture (une fois)
  useEffect(() => {
    if (!open || cams.length) return;
    api.get("/cameras").then((r) => {
      const list = (r.data || []).map((c) => ({ id: c.id, name: c.name, mode: c.stream_mode }));
      setCams(list);
      if (list.length && !camId) setCamId(list[0].id);
    }).catch(() => {});
  }, [open, cams.length, camId]);

  const run = useCallback(async (key, fn) => {
    setRunning((r) => ({ ...r, [key]: true }));
    const res = await timeIt(fn);
    setResults((s) => ({ ...s, [key]: res }));
    setRunning((r) => ({ ...r, [key]: false }));
  }, []);

  // ─── Test runners ────────────────────────────────────────────────
  const runHealth = () => run("health", async () => (await api.get("/health")).data);
  const runPublicStatus = () => run("public_status", async () => (await api.get("/system/public-status")).data);
  const runStreams = () => run("streams", async () => {
    // Va chercher /api/streams via le backend (proxy → go2rtc). Fallback : direct si dispo.
    try { return (await api.get("/diagnostics/go2rtc/streams")).data; }
    catch { return { note: "endpoint proxy indisponible — nécessite curl direct côté serveur" }; }
  });
  const runGo2rtcDiag = () => {
    if (!camId) return;
    return run("go2rtc_diag", async () => (await api.get(`/cameras/${camId}/go2rtc-diagnostic`)).data);
  };
  const runPipelineDiag = () => {
    if (!camId) return;
    return run("pipeline_diag", async () => (await api.get(`/cameras/${camId}/pipeline-diagnostic`)).data);
  };
  const runWebrtcSdp = () => {
    if (!camId) return;
    return run("webrtc_sdp", async () => {
      const { data } = await api.post(`/pipeline/webrtc/${camId}`, { type: "offer", sdp: SDP_OFFER_TEMPLATE });
      return {
        type: data.type,
        candidates: extractIceCandidates(data.sdp),
        answer_sdp_length: (data.sdp || "").length,
      };
    });
  };
  const runAll = async () => {
    await runHealth();
    await runPublicStatus();
    await runStreams();
    if (camId) { await runGo2rtcDiag(); await runPipelineDiag(); await runWebrtcSdp(); }
  };

  // ─── Rapport texte complet ───────────────────────────────────────
  const buildReport = () => {
    const now = new Date().toISOString();
    const env = {
      href: window.location.href,
      origin: window.location.origin,
      protocol: window.location.protocol,
      host: window.location.host,
      user_agent: navigator.userAgent,
      api_base_url: process.env.REACT_APP_BACKEND_URL || "(empty — relative /api)",
      time: now,
    };
    const token = localStorage.getItem("mg_token");
    env.token_expiry = token ? decodeJwtExp(token) : null;
    env.selected_camera_id = camId || null;
    const parts = [
      "═══════════════════════════════════════════════════════════",
      "  MG-VMS · Debug Report v1.0-rc4.5",
      "═══════════════════════════════════════════════════════════",
      "",
      "── Environnement ─────────────────────────────────────────",
      JSON.stringify(env, null, 2),
      "",
    ];
    for (const [key, res] of Object.entries(results)) {
      parts.push(`── ${key} (${res.ms}ms · ${res.ok ? "OK" : "FAIL"}) ─────────────`);
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
      data-testid={`dbg-tab-${id}`}
    >{label}</button>
  );
  const btn = (label, onClick, testid, disabled = false) => (
    <button
      onClick={onClick}
      disabled={disabled}
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
        color: r.ok ? "#8f8" : "#f88",
        background: "#111", padding: "8px", margin: "4px 0",
        maxHeight: "40vh", overflow: "auto", fontSize: "10px",
        whiteSpace: "pre-wrap", wordBreak: "break-all",
      }}>
        {`[${r.ms}ms · ${r.ok ? "OK" : "FAIL"}]\n`}
        {r.ok ? JSON.stringify(r.value, null, 2) : `${r.error}\n${JSON.stringify(r.body, null, 2)}`}
      </pre>
    );
  };

  return (
    <div style={panelStyle} data-testid="debug-panel" role="dialog" aria-label="Debug Panel">
      <div style={headerStyle}>
        <strong style={{ color: "#00E5FF" }}>🛠 MG-VMS Debug · Ctrl+Shift+D</strong>
        <span style={{ color: "#666", fontSize: "10px" }}>v1.0-rc4.5</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "6px" }}>
          {tabBtn("summary", "Résumé")}
          {tabBtn("network", "Réseau")}
          {tabBtn("go2rtc", "Go2RTC")}
          {tabBtn("webrtc", "WebRTC")}
          {tabBtn("env", "Env")}
        </div>
        <button
          onClick={() => setOpen(false)}
          style={{ border: "1px solid #555", background: "transparent", color: "#aaa", padding: "3px 8px", cursor: "pointer" }}
          data-testid="dbg-close"
          title="Fermer (Escape)"
        >✕</button>
      </div>

      {/* Sélecteur caméra + bouton Run All (persistent header) */}
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #222", display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ color: "#888", fontSize: "10px", textTransform: "uppercase" }}>Caméra cible</span>
        <select
          value={camId}
          onChange={(e) => setCamId(e.target.value)}
          style={{ background: "#111", color: "#ddd", border: "1px solid #333", padding: "3px 6px", fontSize: "11px" }}
          data-testid="dbg-cam-select"
        >
          {cams.length === 0 && <option value="">(aucune caméra chargée)</option>}
          {cams.map((c) => (
            <option key={c.id} value={c.id}>{c.name} · {c.mode || "auto"} · {c.id.slice(0, 8)}</option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        {btn("▶ Tout lancer", runAll, "dbg-run-all")}
        {btn("📋 Copier rapport", copyReport, "dbg-copy-report")}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "12px 14px" }}>
        {tab === "summary" && (
          <div>
            <div style={{ color: "#888", marginBottom: "8px" }}>
              Volet de diagnostic MG-VMS. Aucune modification apportée à l'app.
              Utilise les endpoints backend existants uniquement.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "12px" }}>
              {btn("Backend /health", runHealth, "dbg-run-health", running.health)}
              {btn("System public-status", runPublicStatus, "dbg-run-public", running.public_status)}
              {btn("Go2RTC diagnostic caméra", runGo2rtcDiag, "dbg-run-go2rtc-diag", running.go2rtc_diag || !camId)}
              {btn("Pipeline diagnostic caméra", runPipelineDiag, "dbg-run-pipeline-diag", running.pipeline_diag || !camId)}
              {btn("WebRTC SDP test", runWebrtcSdp, "dbg-run-webrtc", running.webrtc_sdp || !camId)}
              {btn("Streams (proxy go2rtc)", runStreams, "dbg-run-streams", running.streams)}
            </div>
            <div style={{ marginTop: "16px", color: "#888", fontSize: "10px" }}>
              Résultats affichés dans les onglets Réseau / Go2RTC / WebRTC. Cliquez « Copier rapport » pour envoyer un rapport complet à l'équipe support.
            </div>
          </div>
        )}

        {tab === "network" && (
          <div>
            <div style={{ color: "#888", fontSize: "10px", marginBottom: "8px" }}>
              Latence et disponibilité des endpoints backend.
            </div>
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>GET /api/health</h4>
            {resultBlock("health")}
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>GET /api/system/public-status</h4>
            {resultBlock("public_status")}
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>Streams Go2RTC (via backend)</h4>
            {resultBlock("streams")}
          </div>
        )}

        {tab === "go2rtc" && (
          <div>
            <div style={{ color: "#888", fontSize: "10px", marginBottom: "8px" }}>
              Diagnostic Go2RTC détaillé pour la caméra sélectionnée. Endpoint
              <code style={{ color: "#00E5FF" }}> GET /api/cameras/{"{id}"}/go2rtc-diagnostic</code>
              — sondage READ-ONLY (codec, transport, bitrate, résolution, transcoding).
            </div>
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>Go2RTC diagnostic</h4>
            {resultBlock("go2rtc_diag")}
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>Pipeline diagnostic (multi-étapes)</h4>
            {resultBlock("pipeline_diag")}
          </div>
        )}

        {tab === "webrtc" && (
          <div>
            <div style={{ color: "#888", fontSize: "10px", marginBottom: "8px" }}>
              Envoie une offer SDP minimale au backend qui la relaie à Go2RTC.
              Retourne les <b>candidates ICE réels</b> retournés par Go2RTC
              (host UDP/TCP, srflx via STUN, etc.). Permet de trancher entre
              cause "candidates absents/mauvais" vs "candidates OK mais réseau bloqué".
            </div>
            <h4 style={{ color: "#00E5FF", fontSize: "11px", marginTop: "12px" }}>WebRTC SDP test</h4>
            {resultBlock("webrtc_sdp")}
            {results.webrtc_sdp?.ok && (
              <div style={{ marginTop: "8px", padding: "8px", border: "1px solid #ffaa0033", background: "#ffaa0011" }}>
                <div style={{ color: "#ffaa00", fontSize: "10px", textTransform: "uppercase" }}>Interprétation candidates</div>
                <div style={{ color: "#ddd", fontSize: "11px", marginTop: "4px" }}>
                  Si vous voyez <code>typ host</code> avec l'IP LAN du serveur ➜ ICE devrait marcher sur LAN direct.<br />
                  Si vous voyez UNIQUEMENT <code>172.x.x.x</code> ou IP docker ➜ candidates non joignables ➜ pas de flux.<br />
                  Si vous voyez <code>typ srflx</code> avec IP publique ➜ STUN a fait son job.
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "env" && (
          <div>
            <div style={{ color: "#888", fontSize: "10px", marginBottom: "8px" }}>
              Informations d'environnement client (navigateur, session, config axios).
            </div>
            <pre style={{ background: "#111", padding: "8px", fontSize: "10px", whiteSpace: "pre-wrap" }}>
              {JSON.stringify({
                url: window.location.href,
                origin: window.location.origin,
                protocol: window.location.protocol,
                host: window.location.host,
                api_base: process.env.REACT_APP_BACKEND_URL || "(empty — relative /api)",
                token_present: !!localStorage.getItem("mg_token"),
                token_expiry: localStorage.getItem("mg_token") ? decodeJwtExp(localStorage.getItem("mg_token")) : null,
                refresh_present: !!localStorage.getItem("mg_refresh"),
                user_agent: navigator.userAgent,
                cameras_loaded: cams.length,
              }, null, 2)}
            </pre>
          </div>
        )}
      </div>

      <div style={{ padding: "6px 14px", borderTop: "1px solid #222", color: "#555", fontSize: "10px", textAlign: "center" }}>
        Ctrl+Shift+D pour basculer · Escape pour fermer · Rapport partageable via « Copier rapport »
      </div>
    </div>
  );
}
