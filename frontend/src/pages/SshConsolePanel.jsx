import React, { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { Card } from "@/components/ui/card";
import { Loader2, TerminalSquare, LogOut } from "lucide-react";
import HoldToRevealInput from "@/components/ui/hold-to-reveal-input";

/**
 * v3.22 · Console shell hôte (Suivi des performances → Debug), style
 * « cockpit ». Choix tranchés le 01/09 : vrai shell HÔTE (pas le
 * conteneur), authentification déléguée à sshd via les identifiants
 * Linux réels saisis ici — jamais ceux de MG-VMS, jamais stockés côté
 * frontend (juste passés une fois dans le premier message WebSocket).
 */
export default function SshConsolePanel() {
  const [status, setStatus] = useState("form"); // form | connecting | connected | error
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const termRef = useRef(null);
  const containerRef = useRef(null);
  const wsRef = useRef(null);
  const fitRef = useRef(null);

  const cleanup = () => {
    try { wsRef.current?.close(); } catch (e) {}
    wsRef.current = null;
    try { termRef.current?.dispose(); } catch (e) {}
    termRef.current = null;
    fitRef.current = null;
  };

  useEffect(() => () => cleanup(), []);

  const connect = (e) => {
    e.preventDefault();
    if (!username || !password) return;
    setError("");
    setStatus("connecting");

    const envBase = process.env.REACT_APP_BACKEND_URL || "";
    const base = envBase
      ? envBase.replace(/^http/, "ws")
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
    const wsToken = encodeURIComponent(localStorage.getItem("mg_token") || "");
    const ws = new WebSocket(`${base}/api/system/console/ws?token=${wsToken}`);
    wsRef.current = ws;

    ws.onopen = () => {
      const term = new Terminal({
        cursorBlink: true, fontSize: 13, fontFamily: "monospace",
        theme: { background: "#0b0d12" },
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      termRef.current = term;
      fitRef.current = fit;

      ws.send(JSON.stringify({
        type: "login", username, password, cols: 80, rows: 24,
      }));
    };

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      if (msg.type === "connected") {
        setStatus("connected");
        setPassword(""); // effacé du state dès que la session SSH est établie
        setTimeout(() => {
          if (containerRef.current && termRef.current) {
            termRef.current.open(containerRef.current);
            fitRef.current.fit();
            termRef.current.onData((data) => {
              ws.send(JSON.stringify({ type: "input", data }));
            });
            termRef.current.focus();
          }
        }, 0);
      } else if (msg.type === "data") {
        termRef.current?.write(msg.data);
      } else if (msg.type === "error") {
        setError(msg.message || "Échec de connexion");
        setStatus("error");
      }
    };

    ws.onclose = () => {
      if (status === "connected") {
        setError("Session terminée");
        setStatus("error");
      }
    };
    ws.onerror = () => {
      setError("Connexion WebSocket échouée");
      setStatus("error");
    };
  };

  const disconnect = () => {
    cleanup();
    setStatus("form");
    setUsername(""); setPassword(""); setError("");
  };

  useEffect(() => {
    if (status !== "connected") return;
    const onResize = () => {
      if (!fitRef.current || !termRef.current || !wsRef.current) return;
      fitRef.current.fit();
      const { cols, rows } = termRef.current;
      try { wsRef.current.send(JSON.stringify({ type: "resize", cols, rows })); } catch (e) {}
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [status]);

  return (
    <Card className="p-4 space-y-3" data-testid="ssh-console-panel">
      <div className="flex justify-between items-center">
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <TerminalSquare size={15} /> Console hôte (SSH)
        </div>
        {status === "connected" && (
          <button onClick={disconnect} data-testid="ssh-console-disconnect"
                  className="text-[11px] flex items-center gap-1 px-2 py-1 border border-border hover:bg-secondary">
            <LogOut size={12} /> Fermer la session
          </button>
        )}
      </div>

      {status === "form" && (
        <form onSubmit={connect} className="space-y-2 max-w-sm" data-testid="ssh-console-login-form">
          <p className="text-[11px] text-muted-foreground">
            Identifiants Linux réels de la machine — jamais ceux de MG-VMS, jamais stockés.
          </p>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Utilisateur</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)}
                   autoComplete="off" data-testid="ssh-console-username"
                   className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Mot de passe</label>
            <HoldToRevealInput value={password} onChange={(e) => setPassword(e.target.value)}
                   autoComplete="off" data-testid="ssh-console-password"
                   className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]" />
          </div>
          <button type="submit" disabled={!username || !password} data-testid="ssh-console-connect"
                  className="px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
            Se connecter
          </button>
        </form>
      )}

      {status === "connecting" && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={15} className="animate-spin" /> Connexion SSH en cours…
        </div>
      )}

      {status === "error" && (
        <div className="space-y-2">
          <p className="text-[12px] text-[#FF3333]">{error}</p>
          <button onClick={disconnect} data-testid="ssh-console-retry"
                  className="px-3 py-1.5 border border-border hover:bg-secondary text-xs">
            Réessayer
          </button>
        </div>
      )}

      <div
        ref={containerRef}
        data-testid="ssh-console-terminal"
        style={{ display: status === "connected" ? "block" : "none", height: 420 }}
        className="border border-border"
      />
    </Card>
  );
}
