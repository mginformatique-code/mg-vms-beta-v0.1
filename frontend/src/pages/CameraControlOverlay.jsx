/**
 * CameraControlOverlay — Contrôles terrain en overlay sur le lecteur live.
 *
 * v3.6 · Réécrit pour utiliser le device layer (`useDeviceCapabilities` +
 * `/api/devices/{id}/light|siren|ir`) au lieu de l'ancienne heuristique de
 * relais ONVIF génériques (`GET /cameras/{id}/relays` puis association
 * positionnelle relais[0]→projecteur / relais[1]→sirène). Cette heuristique
 * était fragile par construction : "ONVIF ne dit pas à quoi sert un relais,
 * juste qu'il existe" (commentaire d'origine) — elle pouvait piloter la
 * mauvaise sortie selon l'ordre de déclaration côté caméra, et n'affichait
 * un bouton QUE si un relais générique existait, jamais en fonction de la
 * capacité réelle (lumière/sirène) de la caméra.
 *
 * Le device layer résout ce problème pour de bon : chaque driver
 * constructeur (Reolink/Hikvision/Dahua/ONVIF générique) sait exactement
 * quelle capacité est réellement câblée sur le modèle (cf.
 * `backend/drivers/*.py`), donc les boutons ci-dessous n'apparaissent que
 * si `caps.spotlight`/`caps.white_light`/`caps.siren`/`caps.ir_control`
 * sont vrais pour CETTE caméra précise — peu importe la marque.
 *
 * 4 actions rapides pilotées par capacité :
 *   - Lumière (spotlight/white light)  · POST /api/devices/{id}/light  {enabled, mode}
 *   - IR (jour/nuit)                    · POST /api/devices/{id}/ir     {mode}
 *   - Sirène                            · POST /api/devices/{id}/siren {enabled}
 *   - TTS (parler, inchangé)            · POST /api/cameras/{id}/audio/tts { text }
 *   - Reboot (inchangé)                 · POST /api/cameras/{id}/reboot (confirm requis)
 *
 * `footer` (bool, def. false) : rendu en barre pleine largeur persistante
 * (usage : CameraCenter LiveTab) au lieu du petit cluster coin bas-gauche
 * qui n'apparaît qu'au survol (usage : mosaïque LiveView, tuiles étroites).
 */
import React, { useState } from "react";
import { Lightbulb, Moon, Siren, Volume2, RefreshCw, X, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { toast } from "sonner";
import useDeviceCapabilities from "@/hooks/useDeviceCapabilities";

const BTN_CLS = "w-8 h-8 bg-black/70 hover:bg-[#00E5FF] hover:text-black flex items-center justify-center text-white transition-colors relative disabled:opacity-30 disabled:hover:bg-black/70 disabled:hover:text-white disabled:cursor-not-allowed";

function ActionBtn({ children, onClick, testid, title, active, busy }) {
  return (
    <button data-ptz-btn disabled={busy} onClick={(e) => { e.stopPropagation(); onClick(e); }}
      className={`${BTN_CLS} ${active ? "!bg-[#00E676] text-black" : ""}`}
      data-testid={testid} title={title}>
      {busy ? <Loader2 size={13} className="animate-spin" /> : children}
    </button>
  );
}

export default function CameraControlOverlay({ cam, footer = false, visible = true }) {
  const camId = cam?.id;
  const { caps } = useDeviceCapabilities(camId);
  const [busy, setBusy] = useState(null);
  const [ttsOpen, setTtsOpen] = useState(false);
  const [ttsText, setTtsText] = useState("");
  // État "dernière commande envoyée" — le device layer ne remonte pas
  // (encore) l'état matériel courant lumière/sirène en lecture, juste des
  // commandes ; ces booléens reflètent donc ce qu'on a demandé, pas un
  // poll live de la caméra (cf. AlarmTab/LightingTab dans CameraCenter,
  // même limite documentée).
  const [lightOn, setLightOn] = useState(false);
  const [sirenOn, setSirenOn] = useState(false);
  const [irOn, setIrOn] = useState(false);

  if (!camId) return null;

  const hasLight = !!(caps?.spotlight || caps?.white_light);
  const hasSiren = !!caps?.siren;
  const hasIr = !!caps?.ir_control;
  const hasAnyDeviceControl = hasLight || hasSiren || hasIr;

  const toggleLight = async () => {
    const next = !lightOn;
    setBusy("light");
    try {
      await api.post(`/devices/${camId}/light`, { enabled: next, mode: "on" });
      setLightOn(next);
      toast.success(`Lumière ${next ? "activée" : "désactivée"}`);
    } catch (e) {
      toast.error(`Échec lumière : ${e?.response?.data?.detail?.message || e?.response?.data?.detail || "erreur"}`);
    } finally { setBusy(null); }
  };

  const toggleIr = async () => {
    const next = !irOn;
    setBusy("ir");
    try {
      await api.post(`/devices/${camId}/ir`, { mode: next ? "on" : "off" });
      setIrOn(next);
      toast.success(`IR ${next ? "activé" : "désactivé"}`);
    } catch (e) {
      toast.error(`Échec IR : ${e?.response?.data?.detail?.message || e?.response?.data?.detail || "erreur"}`);
    } finally { setBusy(null); }
  };

  const toggleSiren = async () => {
    const next = !sirenOn;
    setBusy("siren");
    try {
      await api.post(`/devices/${camId}/siren`, { enabled: next });
      setSirenOn(next);
      toast.success(`Sirène ${next ? "activée" : "désactivée"}`);
    } catch (e) {
      toast.error(`Échec sirène : ${e?.response?.data?.detail?.message || e?.response?.data?.detail || "erreur"}`);
    } finally { setBusy(null); }
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

  const buttons = (
    <>
      {hasLight && (
        <ActionBtn onClick={toggleLight} testid="ctrl-light" busy={busy === "light"}
          title={`Lumière ${lightOn ? "ON" : "OFF"}`} active={lightOn}>
          <Lightbulb size={14} />
        </ActionBtn>
      )}
      {hasIr && (
        <ActionBtn onClick={toggleIr} testid="ctrl-ir" busy={busy === "ir"}
          title={`IR (filtre jour/nuit) ${irOn ? "ON" : "OFF"}`} active={irOn}>
          <Moon size={14} />
        </ActionBtn>
      )}
      {hasSiren && (
        <ActionBtn onClick={toggleSiren} testid="ctrl-siren" busy={busy === "siren"}
          title={`Sirène / alarme ${sirenOn ? "ON" : "OFF"}`} active={sirenOn}>
          <Siren size={14} />
        </ActionBtn>
      )}
      <ActionBtn onClick={() => setTtsOpen(true)} testid="ctrl-tts" title="TTS (parler)">
        <Volume2 size={14} />
      </ActionBtn>
      <ActionBtn onClick={reboot} testid="ctrl-reboot" title="Redémarrer la caméra" busy={busy === "reboot"}>
        <RefreshCw size={14} />
      </ActionBtn>
    </>
  );

  if (footer) {
    // Barre pleine largeur, persistante — pied de la visualisation
    // (usage : CameraCenter LiveTab, plus de place qu'une tuile de mosaïque).
    return (
      <div className="absolute bottom-0 inset-x-0 flex items-center justify-between gap-2 px-2 py-1.5 bg-black/75 backdrop-blur-sm"
           data-testid={`camera-controls-footer-${camId}`}>
        <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-white/50">
          {!hasAnyDeviceControl && !caps && "Chargement des capacités…"}
          {!hasAnyDeviceControl && caps && "Aucune fonction relais/lumière/sirène sur cette caméra"}
        </div>
        <div className="flex gap-0.5">{buttons}</div>
        {ttsOpen && (
          <div className="absolute bottom-11 right-2 bg-black/90 border border-[#00E5FF]/40 p-2 w-64 backdrop-blur-sm"
               onClick={(e) => e.stopPropagation()} data-testid="tts-panel">
            <TtsPanel ttsText={ttsText} setTtsText={setTtsText} onClose={() => setTtsOpen(false)} onSend={sendTts} busy={busy === "tts"} />
          </div>
        )}
      </div>
    );
  }

  // v3.19 · `visible` pilote l'OPACITÉ, pas le montage — le composant reste
  // monté en continu. Avant, LiveView démontait/remontait ce composant à
  // chaque hover in/out, ce qui réinitialisait lightOn/irOn/sirenOn à leur
  // valeur par défaut (false) — un simple mouvement de souris hors de la
  // tuile suffisait à faire "oublier" que la lumière était allumée, donc le
  // bouton renvoyait toujours enabled:true au clic suivant (impossible
  // d'éteindre). Signalé par l'utilisateur : "le bouton lumière ça
  // fonctionne, mais pas possible de l'éteindre".
  return (
    // v3.36 · Remonté de bottom-2 à bottom-6 (demande explicite, "remonte
    // légèrement les boutons d'actions caméras") — chevauchait le bandeau
    // de pied de tuile (site + caméra, LiveView.jsx absolute bottom-0).
    // Reste bien sous la timeline de la vue focus (FocusTimeline, bottom-14
    // — voir son propre commentaire sur cette même zone), non touchée.
    <div className={`absolute bottom-6 left-2 transition-opacity ${visible ? "opacity-70 hover:opacity-100" : "opacity-0 pointer-events-none"}`}
         data-testid={`camera-controls-${camId}`}>
      <div className="flex gap-0.5 bg-black/50 p-0.5 backdrop-blur-sm">{buttons}</div>
      {ttsOpen && (
        <div className="absolute bottom-9 left-0 bg-black/90 border border-[#00E5FF]/40 p-2 w-64 backdrop-blur-sm"
             onClick={(e) => e.stopPropagation()} data-testid="tts-panel">
          <TtsPanel ttsText={ttsText} setTtsText={setTtsText} onClose={() => setTtsOpen(false)} onSend={sendTts} busy={busy === "tts"} />
        </div>
      )}
    </div>
  );
}

function TtsPanel({ ttsText, setTtsText, onClose, onSend, busy }) {
  return (
    <>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase text-[#00E5FF]">Message vocal</span>
        <button onClick={onClose} className="text-white/50 hover:text-white">
          <X size={12} />
        </button>
      </div>
      <textarea value={ttsText} onChange={(e) => setTtsText(e.target.value)}
        placeholder="Tapez le message à diffuser…"
        className="w-full h-16 text-xs bg-black/50 border border-white/20 p-1.5 text-white resize-none"
        data-testid="tts-input" autoFocus />
      <div className="flex justify-end gap-1 mt-1.5">
        <button onClick={onClose}
          className="text-[10px] px-2 py-1 border border-white/20 text-white/70 hover:bg-white/10">
          Annuler
        </button>
        <button onClick={onSend} disabled={!ttsText.trim() || busy}
          className="text-[10px] px-2 py-1 bg-[#00E5FF] text-black hover:opacity-90 disabled:opacity-40"
          data-testid="tts-send">
          {busy ? "Envoi…" : "Diffuser"}
        </button>
      </div>
    </>
  );
}
