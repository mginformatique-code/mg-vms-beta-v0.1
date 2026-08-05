/**
 * CameraControlOverlay — Contrôles terrain en overlay sur le lecteur live.
 *
 * 5 actions rapides :
 *   - Projecteur (relais spotlight)  · POST /api/cameras/{id}/relay/spotlight/{on|off}
 *   - IR (illuminateur infrarouge)    · POST /api/cameras/{id}/relay/ir/{on|off}
 *   - Sirène (alarme sonore)          · POST /api/cameras/{id}/relay/siren/{on|off}
 *   - TTS (parler)                    · POST /api/cameras/{id}/audio/tts { text }
 *   - Reboot                          · POST /api/cameras/{id}/reboot (confirm requis)
 *
 * S'affiche en overlay bottom-left du player, discret par défaut, apparaît au hover.
 */
import React, { useState } from "react";
import { Lightbulb, Moon, Siren, Volume2, RefreshCw, X } from "lucide-react";
import api from "@/lib/api";
import { toast } from "sonner";

const BTN_CLS = "w-8 h-8 bg-black/70 hover:bg-[#00E5FF] hover:text-black flex items-center justify-center text-white transition-colors relative";

function ActionBtn({ children, onClick, testid, title, active }) {
  return (
    <button data-ptz-btn onClick={(e) => { e.stopPropagation(); onClick(e); }}
      className={`${BTN_CLS} ${active ? "!bg-[#00E676] text-black" : ""}`}
      data-testid={testid} title={title}>
      {children}
    </button>
  );
}

export default function CameraControlOverlay({ cam }) {
  const [busy, setBusy] = useState(null);
  const [ttsOpen, setTtsOpen] = useState(false);
  const [ttsText, setTtsText] = useState("");
  // States locaux (optimistic) — on ne persiste pas, chaque toggle relance le POST
  const [relays, setRelays] = useState({ spotlight: false, ir: false, siren: false });

  const camId = cam?.id;
  if (!camId) return null;

  const toggleRelay = async (token) => {
    const next = !relays[token];
    setBusy(token);
    try {
      await api.post(`/cameras/${camId}/relay/${token}/${next ? "on" : "off"}`);
      setRelays((r) => ({ ...r, [token]: next }));
      toast.success(`${token.charAt(0).toUpperCase() + token.slice(1)} ${next ? "activé" : "désactivé"}`);
    } catch (e) {
      toast.error(`Échec ${token} : ${e?.response?.data?.detail || "erreur"}`);
    } finally {
      setBusy(null);
    }
  };

  const sendTts = async () => {
    const text = ttsText.trim();
    if (!text) return;
    setBusy("tts");
    try {
      await api.post(`/cameras/${camId}/audio/tts`, { text });
      toast.success("Message TTS envoyé");
      setTtsOpen(false); setTtsText("");
    } catch (e) {
      toast.error(`TTS : ${e?.response?.data?.detail || "erreur"}`);
    } finally {
      setBusy(null);
    }
  };

  const reboot = async () => {
    if (!window.confirm(`Redémarrer la caméra "${cam.name}" ?\nLe flux sera indisponible 30-60 s.`)) return;
    setBusy("reboot");
    try {
      await api.post(`/cameras/${camId}/reboot`);
      toast.success("Reboot envoyé — flux indisponible ~30-60 s");
    } catch (e) {
      toast.error(`Reboot : ${e?.response?.data?.detail || "erreur"}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="absolute bottom-2 left-2 opacity-70 hover:opacity-100 transition-opacity"
         data-testid={`camera-controls-${camId}`}>
      <div className="flex gap-0.5 bg-black/50 p-0.5 backdrop-blur-sm">
        <ActionBtn onClick={() => toggleRelay("spotlight")} testid="ctrl-spotlight"
          title={`Projecteur ${relays.spotlight ? "ON" : "OFF"}`} active={relays.spotlight}>
          <Lightbulb size={14} />
        </ActionBtn>
        <ActionBtn onClick={() => toggleRelay("ir")} testid="ctrl-ir"
          title={`IR ${relays.ir ? "ON" : "OFF"}`} active={relays.ir}>
          <Moon size={14} />
        </ActionBtn>
        <ActionBtn onClick={() => toggleRelay("siren")} testid="ctrl-siren"
          title={`Sirène ${relays.siren ? "ON" : "OFF"}`} active={relays.siren}>
          <Siren size={14} />
        </ActionBtn>
        <ActionBtn onClick={() => setTtsOpen(true)} testid="ctrl-tts" title="TTS (parler)">
          <Volume2 size={14} />
        </ActionBtn>
        <ActionBtn onClick={reboot} testid="ctrl-reboot" title="Redémarrer la caméra">
          <RefreshCw size={14} className={busy === "reboot" ? "animate-spin" : ""} />
        </ActionBtn>
      </div>

      {/* Modal TTS (compact, inline, ne bloque pas le player) */}
      {ttsOpen && (
        <div className="absolute bottom-9 left-0 bg-black/90 border border-[#00E5FF]/40 p-2 w-64 backdrop-blur-sm"
             onClick={(e) => e.stopPropagation()} data-testid="tts-panel">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] uppercase text-[#00E5FF]">Message vocal</span>
            <button onClick={() => setTtsOpen(false)} className="text-white/50 hover:text-white">
              <X size={12} />
            </button>
          </div>
          <textarea value={ttsText} onChange={(e) => setTtsText(e.target.value)}
            placeholder="Tapez le message à diffuser…"
            className="w-full h-16 text-xs bg-black/50 border border-white/20 p-1.5 text-white resize-none"
            data-testid="tts-input" autoFocus />
          <div className="flex justify-end gap-1 mt-1.5">
            <button onClick={() => setTtsOpen(false)}
              className="text-[10px] px-2 py-1 border border-white/20 text-white/70 hover:bg-white/10">
              Annuler
            </button>
            <button onClick={sendTts} disabled={!ttsText.trim() || busy === "tts"}
              className="text-[10px] px-2 py-1 bg-[#00E5FF] text-black hover:opacity-90 disabled:opacity-40"
              data-testid="tts-send">
              {busy === "tts" ? "Envoi…" : "Diffuser"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
