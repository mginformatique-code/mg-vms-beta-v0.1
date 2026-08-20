/**
 * CameraControlOverlay — Contrôles terrain en overlay sur le lecteur live.
 *
 * 5 actions rapides :
 *   - Projecteur (relais ONVIF réel, token découvert)  · POST /api/cameras/{id}/relay/{token}/{on|off}
 *   - IR (filtre IR jour/nuit, endpoint dédié)          · POST /api/cameras/{id}/ir/{on|off}
 *   - Sirène (relais ONVIF réel, token découvert)       · POST /api/cameras/{id}/relay/{token}/{on|off}
 *   - TTS (parler)                                       · POST /api/cameras/{id}/audio/tts { text }
 *   - Reboot                                             · POST /api/cameras/{id}/reboot (confirm requis)
 *
 * v3.1.4 · Les tokens ONVIF de relais sont des identifiants propres à
 * chaque caméra (ex. "RelayOutputToken_0"), jamais des noms génériques
 * comme "spotlight"/"siren" — l'appel échouait systématiquement en
 * envoyant ces libellés comme token. On découvre maintenant les VRAIS
 * relais via GET /cameras/{id}/relays et on associe les 2 premiers
 * trouvés aux boutons projecteur/sirène (heuristique : ONVIF ne dit pas
 * à quoi sert un relais, juste qu'il existe). Boutons désactivés si la
 * caméra n'expose aucun relais. L'IR bascule maintenant le vrai endpoint
 * dédié (filtre IR-cut) au lieu d'un relais fictif.
 *
 * S'affiche en overlay bottom-left du player, discret par défaut, apparaît au hover.
 */
import React, { useState, useEffect } from "react";
import { Lightbulb, Moon, Siren, Volume2, RefreshCw, X } from "lucide-react";
import api from "@/lib/api";
import { toast } from "sonner";

const BTN_CLS = "w-8 h-8 bg-black/70 hover:bg-[#00E5FF] hover:text-black flex items-center justify-center text-white transition-colors relative disabled:opacity-30 disabled:hover:bg-black/70 disabled:hover:text-white disabled:cursor-not-allowed";

function ActionBtn({ children, onClick, testid, title, active, disabled }) {
  return (
    <button data-ptz-btn disabled={disabled} onClick={(e) => { e.stopPropagation(); onClick(e); }}
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
  const [irOn, setIrOn] = useState(false);
  // Relais réellement présents sur la caméra (tokens ONVIF opaques) — [] tant
  // qu'on n'a pas encore interrogé/si la caméra n'en expose aucun.
  const [availableRelays, setAvailableRelays] = useState(null); // null = pas encore chargé
  const [relayState, setRelayState] = useState({}); // token -> bool (optimistic)

  const camId = cam?.id;

  useEffect(() => {
    if (!camId) return;
    let alive = true;
    api.get(`/cameras/${camId}/relays`)
      .then((r) => { if (alive) setAvailableRelays(r.data?.relays || []); })
      .catch(() => { if (alive) setAvailableRelays([]); });
    return () => { alive = false; };
  }, [camId]);

  if (!camId) return null;

  const spotlightToken = availableRelays?.[0]?.token;
  const sirenToken = availableRelays?.[1]?.token;

  const toggleRelay = async (token, label) => {
    if (!token) return;
    const next = !relayState[token];
    setBusy(token);
    try {
      await api.post(`/cameras/${camId}/relay/${encodeURIComponent(token)}/${next ? "on" : "off"}`);
      setRelayState((r) => ({ ...r, [token]: next }));
      toast.success(`${label} ${next ? "activé" : "désactivé"}`);
    } catch (e) {
      toast.error(`Échec ${label} : ${e?.response?.data?.detail || "erreur"}`);
    } finally {
      setBusy(null);
    }
  };

  const toggleIr = async () => {
    const next = !irOn;
    setBusy("ir");
    try {
      await api.post(`/cameras/${camId}/ir/${next ? "on" : "off"}`);
      setIrOn(next);
      toast.success(`IR ${next ? "activé" : "désactivé"}`);
    } catch (e) {
      toast.error(`Échec IR : ${e?.response?.data?.detail || "erreur"}`);
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
        <ActionBtn onClick={() => toggleRelay(spotlightToken, "Projecteur")} testid="ctrl-spotlight"
          disabled={!spotlightToken}
          title={spotlightToken ? `Projecteur (relais ${spotlightToken}) ${relayState[spotlightToken] ? "ON" : "OFF"}` : "Aucun relais détecté sur cette caméra"}
          active={relayState[spotlightToken]}>
          <Lightbulb size={14} />
        </ActionBtn>
        <ActionBtn onClick={toggleIr} testid="ctrl-ir"
          title={`IR (filtre jour/nuit) ${irOn ? "ON" : "OFF"}`} active={irOn}>
          <Moon size={14} />
        </ActionBtn>
        <ActionBtn onClick={() => toggleRelay(sirenToken, "Sirène")} testid="ctrl-siren"
          disabled={!sirenToken}
          title={sirenToken ? `Sirène (relais ${sirenToken}) ${relayState[sirenToken] ? "ON" : "OFF"}` : "Un seul relais détecté sur cette caméra (déjà utilisé pour le projecteur)"}
          active={relayState[sirenToken]}>
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
