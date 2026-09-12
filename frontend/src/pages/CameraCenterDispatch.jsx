/**
 * CameraCenterDispatch — v3.19
 *
 * Route landing pour /camera-center (sans :cameraId dans l'URL).
 *
 * v1.0-rc4 : redirigeait sans rien afficher vers /cameras — "Centre
 * caméras" n'avait donc aucun affichage propre, c'était un lien mort.
 *
 * v3.19 : grille technique simple, volontairement réduite aux champs
 * qui n'existent NULLE PART ailleurs dans l'appli pour ne rien dupliquer —
 *   - IP / mode / résolution / codec / PTZ → déjà dans Appareils (table)
 *   - miniatures vidéo → déjà dans Live
 *   - MTBF / coupures / historique → déjà dans le tableau de bord santé
 *   - compteurs total/en ligne/hors ligne → déjà sur le Dashboard
 * Reste : quels plugins IA tournent réellement sur chaque caméra (ANPR
 * actif ou non, nombre de plugins) — champ jamais affiché ailleurs sous
 * cette forme. Clic sur une carte → /camera-center/:id (le panneau
 * technique complet par caméra, déjà existant : réseau, flux, IA,
 * capacités…) — corrigé le 31/08 (renvoyait vers Appareils par erreur).
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Wifi, WifiOff, ScanLine, Search, Volume2, Mic, Flashlight, Move, CircleDot, MemoryStick } from "lucide-react";
import { useApp } from "@/context/AppContext";

// v3.64 · "Trier par" — même besoin que le tri déjà construit sur la liste
// Appareils, mais la vue ici est une grille de cartes, pas un tableau (pas
// de colonnes à cliquer) : un simple sélecteur de champ + un tri croissant
// implicite couvre le besoin sans réinventer un système de tri par colonne.
const SORT_OPTIONS = [
  { id: "name", labelKey: "camdisp.sort_name" },
  { id: "site_name", labelKey: "camdisp.sort_site" },
  { id: "status", labelKey: "camdisp.sort_status" },
  { id: "plugins", labelKey: "camdisp.sort_plugins" },
];

export default function CameraCenterDispatch() {
  const { t } = useApp();
  const navigate = useNavigate();
  const [cams, setCams] = useState(null);
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("name");

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data || [])).catch(() => setCams([]));
  }, []);

  if (cams === null) return null;

  const filtered = q
    ? cams.filter((c) => (c.name || "").toLowerCase().includes(q.toLowerCase()) || (c.site_name || "").toLowerCase().includes(q.toLowerCase()))
    : cams;

  const sortValue = (c) => {
    if (sortBy === "plugins") return (c.enabled_plugins || []).length;
    if (sortBy === "status") return c.status === "online" ? 0 : 1;
    return (c[sortBy] || "").toString().toLowerCase();
  };
  const sorted = [...filtered].sort((a, b) => {
    const va = sortValue(a), vb = sortValue(b);
    return va < vb ? -1 : va > vb ? 1 : 0;
  });

  return (
    <div className="p-6" data-testid="camera-center-overview">
      <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("camdisp.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("camdisp.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} data-testid="camera-center-sort"
                  className="h-9 px-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]">
            {SORT_OPTIONS.map((o) => (
              <option key={o.id} value={o.id}>{t("camdisp.sort_by")} {t(o.labelKey)}</option>
            ))}
          </select>
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("camdisp.filter_placeholder")} data-testid="camera-center-filter"
                   className="pl-8 pr-3 py-1.5 bg-background border border-input outline-none text-sm w-48 focus:border-[#0044FF]" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {sorted.map((c) => {
          const pluginCount = (c.enabled_plugins || []).length;
          const anprActive = (c.enabled_plugins || []).includes("fast-alpr");
          // v3.61 · Icônes de capacités matérielles (HP/micro/lumière/IR/
          // carte SD/PTZ), ancrées à DROITE de la carte (sens inverse des
          // badges plugins/ANPR ci-dessous, à gauche) — demande explicite.
          // Toutes (sauf PTZ, qui vient de `ptz_enabled`) viennent de
          // `capabilities` — fiable depuis le correctif v3.63 du parsing
          // reolink-aio (voir reolink_driver.py::get_capabilities), qui
          // renvoyait spotlight/siren/audio à False pour TOUTE caméra
          // Reolink quel que soit son vrai matériel. Une caméra sans
          // capacités détectées n'affiche simplement aucune de ces icônes,
          // pas une icône "absente" trompeuse.
          const caps = c.capabilities || {};
          const hasSpeaker = !!(caps.speaker || caps.audio_output || caps.two_way_audio);
          const hasMic = !!(caps.microphone || caps.audio_input);
          const hasLight = !!(caps.spotlight || caps.white_light);
          const hasIr = !!caps.ir_control;
          const hasSdCard = !!caps.sdcard;
          const hasPtz = !!c.ptz_enabled;
          return (
            <button key={c.id} onClick={() => navigate(`/camera-center/${c.id}`)} data-testid="camera-center-card"
                    className="text-left bg-card border border-border p-3 hover:border-[#0044FF] transition-colors">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <span className="font-medium text-sm truncate">{c.name}</span>
                <span className={`flex items-center gap-1 text-[10px] uppercase tracking-wider shrink-0 ${c.status === "online" ? "text-[#00E676]" : "text-[#FF3333]"}`}>
                  {c.status === "online" ? <Wifi size={12} /> : <WifiOff size={12} />}
                  {c.status === "online" ? t("camdisp.online") : t("camdisp.offline")}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mb-2 truncate">{c.site_name || "—"}</div>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">{pluginCount} {pluginCount > 1 ? t("camdisp.plugins_ai_plural") : t("camdisp.plugins_ai_singular")}</span>
                  {anprActive && (
                    <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 border border-[#0044FF]/40 text-[#0044FF]">
                      <ScanLine size={10} /> ANPR
                    </span>
                  )}
                </div>
                {(hasSpeaker || hasMic || hasLight || hasIr || hasSdCard || hasPtz) && (
                  <div className="flex items-center gap-1 text-muted-foreground shrink-0">
                    {hasSpeaker && <Volume2 size={12} title={t("camdisp.cap_speaker")} />}
                    {hasMic && <Mic size={12} title={t("camdisp.cap_mic")} />}
                    {hasLight && <Flashlight size={12} title={t("camdisp.cap_light")} />}
                    {hasIr && <CircleDot size={12} className="text-red-500" title={t("camdisp.cap_ir")} />}
                    {hasSdCard && <MemoryStick size={12} title={t("camdisp.cap_sdcard")} />}
                    {hasPtz && <Move size={12} title="PTZ" />}
                  </div>
                )}
              </div>
            </button>
          );
        })}
        {sorted.length === 0 && (
          <div className="col-span-full text-center text-muted-foreground py-12 text-sm">{t("camdisp.no_camera")}</div>
        )}
      </div>
    </div>
  );
}
