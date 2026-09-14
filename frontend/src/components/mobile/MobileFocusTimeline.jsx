/**
 * MobileFocusTimeline — timeline d'activité de la vue live mobile (v3.114).
 *
 * Correctif d'une confusion : la v3.103 avait construit une timeline des
 * SEGMENTS D'ENREGISTREMENT (MobileRecordingsTimeline.jsx) sous la vidéo
 * live. Demande explicite en session : "je pensais à la timeline vue
 * live, comme celle qu'on a avec la version desktop de l'app, pas la
 * timeline des enregistrements, ça on l'a dans la page enregistrements"
 * — la VRAIE référence est `FocusTimeline` dans `LiveView.jsx` (bureau) :
 * une frise D'ÉVÉNEMENTS récents (détections IA + plaques), pas de
 * segments vidéo bruts, avec fenêtre glissante (15m/30m/1h/3h/jour) et
 * bande de miniatures cliquables. Remplace `MobileRecordingsTimeline`
 * dans MobileLive.jsx (fichier conservé, non supprimé, au cas où utile
 * ailleurs) — pas dupliqué avec la page Enregistrements, qui garde son
 * propre rôle (segments vidéo, export).
 *
 * Réutilise la taxonomie déjà partagée par le reste du mobile
 * (`eventTypeColor`/`eventTypeLabel` de `Events.jsx`, les VRAIS types
 * backend) plutôt que la classification `_kindFromEvent` parallèle de
 * LiveView.jsx desktop (inférence par sous-chaîne sur un texte anglais
 * deviné) — évite d'introduire une deuxième taxonomie potentiellement
 * incohérente avec le reste de l'app mobile. Aucun overlay sur la
 * vidéo : rendu INLINE dans le panneau sous la vidéo, comme tout le
 * reste de MobileLive (demande explicite passée : "que rien ne soit sur
 * l'emplacement de la vidéo").
 */
import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { eventTypeColor, eventTypeLabel } from "@/pages/Events";
import { Activity, X } from "lucide-react";

const WINDOW_PRESETS = [15, 30, 60, 180]; // minutes
const PLATE_COLOR = "#FFD700";

function windowStartMs(mode) {
  if (mode === "today") {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  return Date.now() - mode * 60 * 1000;
}

export default function MobileFocusTimeline({ cameraId }) {
  const { t } = useApp();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [windowMode, setWindowMode] = useState(30);
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    if (!cameraId) return;
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const startMs = windowStartMs(windowMode);
        const [ev, pl] = await Promise.all([
          api.get("/events", { params: { camera_id: cameraId, limit: 200 } }),
          api.get("/plates", { params: { camera_id: cameraId, limit: 100 } }),
        ]);
        const evArr = ev.data || [];
        const plArr = pl.data || [];
        const merged = [
          ...evArr.map((e) => ({ ...e, _isPlate: false })),
          ...plArr.map((p) => ({
            id: p.id, type: "plate", timestamp: p.timestamp, _isPlate: true,
            plate: p.plate, thumbnail: p.plate_crop || p.vehicle_crop || p.frame_thumb,
          })),
        ].filter((x) => x.timestamp && new Date(x.timestamp).getTime() >= startMs)
         .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
        if (alive) setItems(merged);
      } catch (e) { if (alive) setItems([]); }
      finally { if (alive) setLoading(false); }
    };
    load();
    const iv = setInterval(load, 8000);
    return () => { alive = false; clearInterval(iv); };
  }, [cameraId, windowMode]);

  const now = Date.now();
  const start = windowStartMs(windowMode);
  const span = Math.max(1, now - start);
  const posPct = (iso) => Math.max(0, Math.min(100, ((new Date(iso).getTime() - start) / span) * 100));
  const colorFor = (item) => (item._isPlate ? PLATE_COLOR : eventTypeColor(item.type));
  const labelFor = (item) => (item._isPlate ? item.plate : eventTypeLabel(item.type, t));

  return (
    <div className="px-3 py-3 border-t border-border" data-testid="mobile-live-focus-timeline">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-1.5">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
          <Activity size={12} /> {t("mobile.live_activity_title")} — {items.length}
          {loading && <span className="text-[#0044FF]">…</span>}
        </div>
        <div className="flex items-center gap-1">
          {WINDOW_PRESETS.map((m) => (
            <button key={m} onClick={() => setWindowMode(m)} data-testid={`mobile-focus-timeline-window-${m}`}
                    className={`text-[9px] mono px-1.5 py-0.5 rounded-md border ${
                      windowMode === m ? "border-[#0044FF] text-[#0044FF]" : "border-border text-muted-foreground"
                    }`}>
              {m < 60 ? `${m}m` : `${m / 60}h`}
            </button>
          ))}
          <button onClick={() => setWindowMode("today")} data-testid="mobile-focus-timeline-window-today"
                  className={`text-[9px] mono px-1.5 py-0.5 rounded-md border ${
                    windowMode === "today" ? "border-[#0044FF] text-[#0044FF]" : "border-border text-muted-foreground"
                  }`}>
            {t("mobile.live_activity_today")}
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="text-xs text-muted-foreground text-center py-3">{t("mobile.live_activity_empty")}</div>
      ) : (
        <>
          <div className="relative h-8 bg-secondary/50 rounded-lg overflow-hidden mb-2" data-testid="mobile-focus-timeline-scrub">
            {items.map((it, i) => (
              <button key={it.id || i} onClick={() => setPreview(it)} data-testid="mobile-focus-timeline-marker"
                      style={{ left: `${posPct(it.timestamp)}%` }}
                      className="absolute top-0 -translate-x-1/2 h-full w-5 flex items-center justify-center"
                      title={`${labelFor(it)} · ${new Date(it.timestamp).toLocaleTimeString("fr-FR")}`}>
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colorFor(it) }} />
              </button>
            ))}
            <div className="absolute top-0 right-0 h-full w-px bg-[#0044FF]" />
          </div>
          <div className="flex gap-1.5 overflow-x-auto pb-1" style={{ touchAction: "pan-x" }} data-testid="mobile-focus-timeline-thumbs">
            {items.filter((it) => it.thumbnail || it.thumbnail_sm).slice(-12).reverse().map((it) => (
              <button key={`th-${it.id}`} onClick={() => setPreview(it)} data-testid="mobile-focus-timeline-thumb"
                      className="relative shrink-0 w-20 rounded-lg overflow-hidden border border-border bg-card text-left">
                <img src={it.thumbnail || it.thumbnail_sm} alt="" className="w-full h-14 object-cover" loading="lazy" />
                <span className="absolute top-1 left-1 w-2.5 h-2.5 rounded-full border border-white/60"
                      style={{ backgroundColor: colorFor(it) }} />
                <div className="px-1 py-0.5 bg-card/95">
                  <div className="text-[9px] mono truncate">{labelFor(it)}</div>
                  <div className="text-[8px] mono text-muted-foreground">
                    {new Date(it.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {preview && (
        <div className="fixed inset-0 z-[60] bg-background flex flex-col" data-testid="mobile-focus-timeline-preview">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
            <span className="text-sm font-medium text-foreground">{labelFor(preview)}</span>
            <button onClick={() => setPreview(null)} data-testid="mobile-focus-timeline-preview-close" className="p-1 text-foreground">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center bg-black">
            {(preview.thumbnail || preview.thumbnail_sm) ? (
              <img src={preview.thumbnail || preview.thumbnail_sm} alt="" className="max-w-full max-h-full object-contain" />
            ) : (
              <Activity size={40} className="text-white/30" />
            )}
          </div>
          <div className="px-3 py-3 border-t border-border text-sm text-foreground">
            {new Date(preview.timestamp).toLocaleString("fr-FR")}
          </div>
        </div>
      )}
    </div>
  );
}
