/**
 * MobileEvents — liste d'événements/alertes pour l'interface mobile (v3.91,
 * corrigé/enrichi v3.94/v3.99).
 *
 * v3.94 ·
 *  - Couleurs/libellés de type CORRIGÉS : réutilisent désormais la vraie
 *    taxonomie exportée depuis `Events.jsx` (`eventTypeColor`/`eventTypeLabel`/
 *    `FILTERS`) — la v3.91 devinait des clés ("motion"/"plate") qui ne
 *    correspondaient à AUCUN vrai type émis par le backend (les vrais types
 *    sont en français : "Personne", "Voiture"...), donc le point de couleur
 *    tombait toujours sur le gris par défaut.
 *  - Chips de filtre (mêmes `FILTERS` que desktop) — le chip par défaut
 *    "tous" ("Informations véhicules" sur desktop) affiche maintenant AUSSI
 *    une section Plaques native (liste compacte, `GET /plates`) au-dessus
 *    du flux d'événements — demande explicite "englober la partie ANPR".
 *    Pas d'embarquement de `VehiclesSection` (2000+ lignes, UI desktop
 *    riche jamais vérifiée à 375px) : liste mobile dédiée à la place,
 *    cohérente avec le reste de ce chantier.
 *  - Détail enrichi : charge la fiche complète (`GET /events/{id}`) à
 *    l'ouverture (comme le fait `EventViewer` desktop) au lieu de se
 *    limiter aux 3-4 champs déjà connus de la liste — "les événements tels
 *    quels n'apportent aucun détail" (retour utilisateur direct).
 *
 * v3.99 · "la fiche véhicule complète, comme la version desktop" — les
 * plaques récentes ouvrent maintenant une VRAIE fiche véhicule
 * consolidée (`GET /vehicles/{plate}`, même endpoint que le tiroir
 * desktop `VehicleDrawer`/`TabOverview`) : passages/première-dernière vue/
 * caméras/confiance moyenne/durée de visite, PAS juste le dernier
 * enregistrement ANPR isolé — plus les actions liste noire/blanche déjà
 * présentes côté desktop. Les onglets Timeline/Heatmap desktop (analytique
 * visuelle, peu adaptée à 375px) restent hors périmètre v1.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { toast } from "sonner";
import { FILTERS, eventTypeColor, eventTypeLabel } from "@/pages/Events";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Camera as CamIcon, Loader2, X, CreditCard, Ban, ShieldCheck, Undo2, ChevronLeft, ChevronRight, PlayCircle } from "lucide-react";

const SWIPE_THRESHOLD_PX = 50;

const PAGE_SIZE = 20;

function passageThumbUrl(passageId) {
  if (!passageId) return null;
  const token = localStorage.getItem("mg_token") || "";
  const base = process.env.REACT_APP_BACKEND_URL || "";
  return `${base}/api/vehicles/passage/${passageId}/thumb?kind=frame&token=${encodeURIComponent(token)}`;
}

// v3.107 · Remplace `PlatesSection` (bandeau "Plaques récentes" glissable
// horizontalement, embarqué en tête de "Informations véhicules") par un
// vrai onglet dédié — demande explicite : "on change de système... un
// onglet plaques stp, et tu me supprimeras les plaques récentes en haut
// de page" (mobile uniquement, la version bureau garde ses `FILTERS`
// intacts). Liste complète paginée (`GET /plates`, même pattern
// charger-plus que le flux d'événements) plutôt que 10 mini-cartes.
function PlatesTab({ onSelectVehicle }) {
  const { t } = useApp();
  const [plates, setPlates] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(() => {
    setPlates(null);
    api.get("/plates", { params: { limit: PAGE_SIZE } })
       .then((r) => { setPlates(r.data || []); setHasMore((r.data || []).length === PAGE_SIZE); })
       .catch(() => setPlates([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const r = await api.get("/plates", { params: { limit: PAGE_SIZE, offset: plates.length } });
      setPlates((prev) => [...prev, ...(r.data || [])]);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) {} finally { setLoadingMore(false); }
  };

  if (plates === null) {
    return (
      <div className="flex items-center justify-center text-muted-foreground py-16" data-testid="mobile-plates-tab-loading">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }
  if (plates.length === 0) {
    return <div className="text-muted-foreground text-sm py-16 text-center">{t("mobile.events_plates_empty")}</div>;
  }

  return (
    <div data-testid="mobile-plates-tab">
      <div className="flex flex-col gap-2">
        {plates.map((p, i) => (
          <button key={p.id} onClick={() => onSelectVehicle(plates.map((pp) => pp.plate), i)} data-testid="mobile-plates-tab-row"
                  className="flex items-center gap-3 rounded-xl border border-border bg-card p-2 text-left">
            <img src={passageThumbUrl(p.id)} alt={p.plate} loading="lazy"
                 className="w-16 h-12 rounded-lg object-cover bg-secondary shrink-0"
                 onError={(e) => { e.currentTarget.style.display = "none"; }} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold mono truncate">{p.plate}</div>
              <div className="text-[11px] text-muted-foreground truncate">{p.camera_name}</div>
              <div className="text-[11px] mono text-muted-foreground">{new Date(p.timestamp).toLocaleString("fr-FR")}</div>
            </div>
            {p.list_status && p.list_status !== "none" && (
              <span className={`text-[9px] uppercase font-bold shrink-0 ${p.list_status === "black" ? "text-[#FF3333]" : "text-[#FFB800]"}`}>
                {p.list_status === "black" ? t("mobile.events_plate_blacklist") : t("mobile.events_plate_whitelist")}
              </span>
            )}
          </button>
        ))}
      </div>
      {hasMore && (
        <div className="flex justify-center pt-3">
          <button onClick={loadMore} disabled={loadingMore} data-testid="mobile-plates-tab-load-more"
                  className="flex items-center gap-2 px-4 py-2 rounded-full border border-border text-xs uppercase tracking-wider text-muted-foreground disabled:opacity-50">
            {loadingMore && <Loader2 size={13} className="animate-spin" />}
            {t("mobile.events_load_more")}
          </button>
        </div>
      )}
    </div>
  );
}

// v3.99 · Fiche véhicule consolidée, réutilise GET /vehicles/{plate} —
// mêmes champs que `TabOverview` desktop (VehicleDrawer).
// v3.103 · Ajout des onglets Timeline/Heatmap desktop (demande explicite,
// screenshot desktop à l'appui) + fond/texte reconstruits sur les tokens
// de thème (`bg-background`/`text-foreground`/`border-border`) au lieu de
// `bg-black/95`+`text-white` codés en dur ("j'aimerais que ça respecte le
// thème noir ou blanc") + navigation tactile gauche/droite entre fiches
// (glissement, seuil identique à MobileLive) pilotée par le parent via
// `onPrev`/`onNext`/`hasPrev`/`hasNext` (liste de plaques du contexte
// d'ouverture — plaques récentes ou plaques des événements affichés).
// v3.105 · Équivalent tactile du survol souris `CameraHoverStat` desktop
// (demande explicite : "la même chose qu'au survol de la souris... mais
// quand j'appuie à l'écran") — même source (`GET /vehicles/{plate}/cameras`,
// mêmes champs `count`/`last_seen`/`first_seen`), mais déclenché par un tap
// (mémorise le point de tap plutôt que la position du curseur) au lieu du
// survol qui n'existe pas au toucher ; se ferme au tap suivant n'importe où.
function VehicleTimelineTab({ plate }) {
  const { t } = useApp();
  const [items, setItems] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [activeStat, setActiveStat] = useState(null); // { camId, x, y } | null

  useEffect(() => {
    setItems(null);
    setActiveStat(null);
    api.get(`/vehicles/${encodeURIComponent(plate)}/passages`, { params: { limit: 100 } })
       .then((r) => setItems(r.data.items || [])).catch(() => setItems([]));
    api.get(`/vehicles/${encodeURIComponent(plate)}/cameras`)
       .then((r) => setCameras(r.data.items || [])).catch(() => setCameras([]));
  }, [plate]);

  const statsByCamera = useMemo(() => new Map(cameras.map((c) => [c.camera_id, c])), [cameras]);
  const activeCamStat = activeStat ? statsByCamera.get(activeStat.camId) : null;

  if (items === null) return <div className="flex justify-center py-8"><Loader2 size={18} className="animate-spin text-muted-foreground" /></div>;
  if (items.length === 0) return <div className="text-xs text-muted-foreground text-center py-8">{t("mobile.vehicle_no_passages")}</div>;

  const groups = new Map();
  for (const p of items) {
    const key = new Date(p.timestamp).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }

  return (
    <div className="space-y-4 relative" data-testid="mobile-vehicle-timeline">
      {activeStat && <div className="fixed inset-0 z-[59]" onClick={() => setActiveStat(null)} />}
      {Array.from(groups.entries()).map(([day, rows]) => (
        <div key={day}>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">{day}</div>
          <div className="border-l-2 border-[#0044FF]/40 pl-3 space-y-2">
            {rows.map((p) => (
              <div key={p.id} className="flex items-center gap-2.5 text-xs" data-testid={`mobile-vehicle-timeline-item-${p.id}`}>
                <span className="mono text-[#0044FF] w-11 shrink-0">{new Date(p.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>
                <img src={passageThumbUrl(p.id)} alt={p.camera_name} className="w-14 h-10 rounded-md object-cover bg-secondary shrink-0" loading="lazy" />
                <button onClick={(e) => { e.stopPropagation(); setActiveStat((cur) => cur?.camId === p.camera_id ? null : { camId: p.camera_id, x: e.clientX, y: e.clientY }); }}
                        data-testid="mobile-vehicle-timeline-camera"
                        className="min-w-0 flex-1 truncate text-left text-foreground underline decoration-dotted decoration-muted-foreground">
                  {p.camera_name}
                </button>
                <span className="mono shrink-0" style={{ color: (p.confidence || 0) > 0.9 ? "#00E676" : "#FFB800" }}>{Math.round((p.confidence || 0) * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      {activeStat && activeCamStat && (
        <div className="fixed z-[60] rounded-lg border border-border bg-card shadow-xl p-2.5 text-[10px] mono space-y-0.5"
             style={{
               left: Math.min(activeStat.x, window.innerWidth - 200),
               top: Math.min(activeStat.y + 14, window.innerHeight - 110),
             }}
             data-testid="mobile-vehicle-timeline-camera-stat">
          <div className="flex items-center gap-1 text-foreground font-medium"><CamIcon size={11} className="text-[#0044FF]" /> {activeCamStat.camera_name}</div>
          <div>{activeCamStat.count} {t("veh.passage_singular")}{activeCamStat.count > 1 ? "s" : ""}</div>
          <div className="text-muted-foreground">{t("veh.last_label")}{activeCamStat.last_seen ? new Date(activeCamStat.last_seen).toLocaleString("fr-FR") : "—"}</div>
          <div className="text-muted-foreground">{t("veh.first_label")}{activeCamStat.first_seen ? new Date(activeCamStat.first_seen).toLocaleString("fr-FR") : "—"}</div>
        </div>
      )}
    </div>
  );
}

function VehicleHeatmapTab({ plate }) {
  const { t } = useApp();
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    api.get(`/vehicles/${encodeURIComponent(plate)}/heatmap`).then((r) => setD(r.data)).catch(() => setD({ by_hour: [], by_dow: [], dow_labels: [] }));
  }, [plate]);
  if (!d) return <div className="flex justify-center py-8"><Loader2 size={18} className="animate-spin text-muted-foreground" /></div>;
  const maxH = Math.max(1, ...(d.by_hour?.length ? d.by_hour : [0]));
  const maxD = Math.max(1, ...(d.by_dow?.length ? d.by_dow : [0]));
  return (
    <div className="space-y-5" data-testid="mobile-vehicle-heatmap">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("mobile.vehicle_heatmap_hour")}</div>
        <div className="space-y-1">
          {(d.by_hour || []).map((count, h) => (
            <div key={h} className="flex items-center gap-2 text-[10px] mono" data-testid={`mobile-heatmap-hour-${h}`}>
              <span className="w-6 text-muted-foreground">{String(h).padStart(2, "0")}</span>
              <div className="h-2 flex-1 bg-secondary/40 relative overflow-hidden">
                <div className="h-full bg-[#0044FF]" style={{ width: `${(count / maxH) * 100}%` }} />
              </div>
              <span className="w-6 text-right text-muted-foreground">{count}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("mobile.vehicle_heatmap_dow")}</div>
        <div className="space-y-1">
          {(d.by_dow || []).map((count, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px] mono" data-testid={`mobile-heatmap-dow-${i}`}>
              <span className="w-14 text-muted-foreground truncate">{d.dow_labels?.[i] ?? i}</span>
              <div className="h-2 flex-1 bg-secondary/40 relative overflow-hidden">
                <div className="h-full bg-[#00E676]" style={{ width: `${(count / maxD) * 100}%` }} />
              </div>
              <span className="w-6 text-right text-muted-foreground">{count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// v3.105 · Équivalent tactile de `MagnifierImage` desktop (demande
// explicite : "pareil pour la loupe, mais légèrement décalé sur le côté
// pour pas que le doigt gêne") — même mécanique de lentille zoomée que la
// version souris (Vehicles.jsx), mais pilotée par le doigt
// (onTouchStart/onTouchMove) et la lentille est décalée horizontalement
// du côté opposé au point touché (jamais centrée dessus comme au survol
// souris, où le curseur fin ne masque rien) — bornée aux limites de
// l'image pour ne jamais déborder. `stopPropagation` sur les événements
// tactiles : évite que le glissement d'exploration de la loupe déclenche
// aussi la navigation gauche/droite entre fiches véhicule (swipe posé sur
// le conteneur parent, voir plus bas).
function MobileMagnifier({ src, alt, className, zoom = 2.5, size = 160 }) {
  const containerRef = useRef(null);
  const [lens, setLens] = useState(null);

  const update = (touch) => {
    const rect = containerRef.current.getBoundingClientRect();
    const x = touch.clientX - rect.left;
    const y = touch.clientY - rect.top;
    if (x < 0 || y < 0 || x > rect.width || y > rect.height) { setLens(null); return; }
    const sideOffset = size / 2 + 24;
    const lensX = x < rect.width / 2
      ? Math.min(x + sideOffset, rect.width - size / 2)
      : Math.max(x - sideOffset, size / 2);
    const lensY = Math.min(Math.max(y, size / 2), rect.height - size / 2);
    setLens({
      lensX, lensY,
      bgW: rect.width * zoom, bgH: rect.height * zoom,
      bgX: -(x * zoom - size / 2), bgY: -(y * zoom - size / 2),
    });
  };
  const onTouchStart = (e) => { e.preventDefault(); e.stopPropagation(); update(e.touches[0]); };
  const onTouchMove = (e) => { e.preventDefault(); e.stopPropagation(); update(e.touches[0]); };
  const onTouchEnd = (e) => { e.stopPropagation(); setLens(null); };

  return (
    <div ref={containerRef} className="relative inline-block" style={{ touchAction: "none" }}
         onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}>
      <img src={src} alt={alt} className={className}
           onError={(e) => { e.target.style.display = "none"; }} data-testid="mobile-magnifier-source-img" />
      {lens && (
        <div className="absolute pointer-events-none rounded-full border-2 border-[#0044FF] shadow-xl"
             style={{
               left: lens.lensX - size / 2, top: lens.lensY - size / 2,
               width: size, height: size,
               backgroundImage: `url(${src})`,
               backgroundRepeat: "no-repeat",
               backgroundSize: `${lens.bgW}px ${lens.bgH}px`,
               backgroundPosition: `${lens.bgX}px ${lens.bgY}px`,
             }}
             data-testid="mobile-magnifier-lens" />
      )}
    </div>
  );
}

function VehicleDetail({ plate, onClose, onPrev, onNext, hasPrev, hasNext }) {
  const { t } = useApp();
  const [d, setD] = useState(null);
  const [saving, setSaving] = useState(false);
  const touchStartX = useRef(null);

  const load = useCallback(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}`).then((r) => setD(r.data)).catch(() => {});
  }, [plate]);
  useEffect(() => { setD(null); load(); }, [load]);

  const setWatch = async (listType) => {
    setSaving(true);
    try {
      const { data: list } = await api.get("/watchlist");
      const existing = (list || []).find((w) => (w.plate || "").toUpperCase() === plate.toUpperCase());
      if (existing) await api.delete(`/watchlist/${existing.id}`);
      if (listType) await api.post("/watchlist", { plate, list_type: listType, reason: "" });
      toast.success(t("mobile.vehicle_watch_updated"));
      setD((prev) => prev ? { ...prev, list_status: listType || "none" } : prev);
    } catch (e) {
      toast.error(t("mobile.vehicle_watch_failed"));
    } finally { setSaving(false); }
  };

  const onTouchStart = (e) => { touchStartX.current = e.touches[0].clientX; };
  const onTouchEnd = (e) => {
    if (touchStartX.current == null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (dx > SWIPE_THRESHOLD_PX && hasPrev) onPrev();
    else if (dx < -SWIPE_THRESHOLD_PX && hasNext) onNext();
    touchStartX.current = null;
  };

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col" data-testid="mobile-vehicle-detail"
         onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <span className="text-foreground text-lg font-bold mono truncate">{d?.plate || plate}</span>
        <button onClick={onClose} data-testid="mobile-vehicle-detail-close" className="text-foreground p-1">
          <X size={20} />
        </button>
      </div>
      {!d ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <div className="relative">
            {d.best_thumb_id && (
              <img src={passageThumbUrl(d.best_thumb_id)} alt={d.plate}
                   className="w-full max-h-56 object-cover" data-testid="mobile-vehicle-thumb" />
            )}
            {hasPrev && (
              <button onClick={onPrev} data-testid="mobile-vehicle-prev"
                      className="absolute left-1 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full flex items-center justify-center bg-black/50 text-white">
                <ChevronLeft size={20} />
              </button>
            )}
            {hasNext && (
              <button onClick={onNext} data-testid="mobile-vehicle-next"
                      className="absolute right-1 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full flex items-center justify-center bg-black/50 text-white">
                <ChevronRight size={20} />
              </button>
            )}
          </div>
          <div className="p-3">
            {(d.vehicle_make || d.vehicle_model || d.vehicle_color) && (
              <div className="text-base font-medium text-foreground mb-3">
                {[d.vehicle_make, d.vehicle_model, d.vehicle_color].filter(Boolean).join(" · ")}
              </div>
            )}

            <Tabs defaultValue="overview" key={plate}>
              <TabsList className="grid grid-cols-3 rounded-xl bg-secondary/40 border border-border h-auto p-1 gap-1" data-testid="mobile-vehicle-tabs">
                <TabsTrigger value="overview" className="rounded-lg text-xs py-2">{t("veh.tab_overview")}</TabsTrigger>
                <TabsTrigger value="timeline" className="rounded-lg text-xs py-2">Timeline</TabsTrigger>
                <TabsTrigger value="heatmap" className="rounded-lg text-xs py-2">Heatmap</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-3">
                <div className="grid grid-cols-2 gap-2 text-xs text-foreground">
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_type")}</span><br />{d.vehicle_type || "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_country")}</span><br />{d.country || "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_passages")}</span><br />{d.passages_count ?? "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_cameras")}</span><br />{d.cameras_count ?? "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_first_seen")}</span><br />{d.first_seen ? new Date(d.first_seen).toLocaleString("fr-FR") : "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_last_seen")}</span><br />{d.last_seen ? new Date(d.last_seen).toLocaleString("fr-FR") : "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_avg_confidence")}</span><br />{d.avg_confidence != null ? `${Math.round(d.avg_confidence * 100)}%` : "—"}</div>
                  <div><span className="text-muted-foreground">{t("mobile.vehicle_avg_visit")}</span><br />{d.avg_visit_duration_min != null ? `${d.avg_visit_duration_min} min` : "—"}</div>
                </div>
                {d.engines?.length > 0 && (
                  <div className="text-[11px] text-muted-foreground mt-2">{t("mobile.vehicle_engines")}: {d.engines.join(", ")}</div>
                )}

                <div className="pt-3 mt-3 border-t border-border">
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">{t("mobile.vehicle_watchlist")}</div>
                  {d.list_status && d.list_status !== "none" && (
                    <div className={`text-xs font-bold uppercase mb-2 ${d.list_status === "black" ? "text-[#FF3333]" : "text-[#FFB800]"}`}>
                      {d.list_status === "black" ? t("mobile.events_plate_blacklist") : t("mobile.events_plate_whitelist")}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button onClick={() => setWatch("black")} disabled={saving} data-testid="mobile-vehicle-blacklist"
                            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg border border-[#FF3333]/50 text-[#FF3333] text-xs uppercase disabled:opacity-40">
                      <Ban size={13} /> {t("mobile.events_plate_blacklist")}
                    </button>
                    <button onClick={() => setWatch("white")} disabled={saving} data-testid="mobile-vehicle-whitelist"
                            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg border border-[#FFB800]/50 text-[#FFB800] text-xs uppercase disabled:opacity-40">
                      <ShieldCheck size={13} /> {t("mobile.events_plate_whitelist")}
                    </button>
                    {d.list_status && d.list_status !== "none" && (
                      <button onClick={() => setWatch(null)} disabled={saving} data-testid="mobile-vehicle-unwatch"
                              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg border border-border text-muted-foreground text-xs uppercase disabled:opacity-40">
                        <Undo2 size={13} /> {t("mobile.vehicle_remove_watch")}
                      </button>
                    )}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="timeline" className="mt-3">
                <VehicleTimelineTab plate={plate} />
              </TabsContent>
              <TabsContent value="heatmap" className="mt-3">
                <VehicleHeatmapTab plate={plate} />
              </TabsContent>
            </Tabs>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MobileEvents() {
  const { t } = useApp();
  const [filtre, setFiltre] = useState("tous");
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [detailId, setDetailId] = useState(null);
  const [detail, setDetail] = useState(null);
  // v3.105 · Lecture vidéo de l'événement (demande explicite) — même
  // mécanique que `EventViewer.jsx::playAround` desktop : `GET
  // /events/{id}/recording` retrouve l'enregistrement qui couvre cet
  // instant + l'offset en secondes, `t=` en query force un seek côté
  // serveur (indispensable si le flux source est HEVC transcodé à la
  // volée, sans support Range) tandis que `onLoadedMetadata` cale aussi
  // `currentTime` pour le cas H264 natif.
  const [recInfo, setRecInfo] = useState(null);
  const [recLoading, setRecLoading] = useState(false);
  const [showVideo, setShowVideo] = useState(false);
  // v3.103 · Remplace `vehiclePlate` seul par une liste + index navigable
  // (demande explicite : "que ce puisse être déplaçable de droite à
  // gauche... pour passer d'une fiche véhicule à une autre") — la liste
  // dépend du contexte d'ouverture (plaques récentes, ou plaques des
  // événements actuellement chargés), jamais un simple plate isolé.
  const [vehicleNav, setVehicleNav] = useState(null); // { list: [plate...], index } | null
  const vehiclePlate = vehicleNav ? vehicleNav.list[vehicleNav.index] : null;
  const openVehicle = (list, index) => setVehicleNav({ list, index });
  const closeVehicle = () => setVehicleNav(null);
  const prevVehicle = () => setVehicleNav((v) => v && ({ ...v, index: (v.index - 1 + v.list.length) % v.list.length }));
  const nextVehicle = () => setVehicleNav((v) => v && ({ ...v, index: (v.index + 1) % v.list.length }));
  // Plaques dédupliquées des événements actuellement chargés, dans l'ordre
  // d'affichage — utilisé quand on ouvre une fiche depuis une carte
  // événement plutôt que depuis la section "Plaques récentes".
  const openVehicleFromEvents = (plate) => {
    const list = [];
    for (const e of events) if (e.plate && !list.includes(e.plate)) list.push(e.plate);
    const index = Math.max(0, list.indexOf(plate));
    openVehicle(list.length ? list : [plate], index);
  };
  // v3.107 · "Plaques" est un onglet mobile SUPPLÉMENTAIRE (pas un des
  // `FILTERS` partagés avec le bureau, qui restent inchangés) — son
  // contenu vient de `/plates` (PlatesTab), pas de `/events`, donc le
  // chargement d'événements ci-dessous est explicitement sauté quand il
  // est actif (pas d'appel /events inutile en arrière-plan).
  const isPlatesTab = filtre === "plaques";
  const activeFilter = FILTERS.find((f) => f.id === filtre) || FILTERS[0];

  const load = useCallback(async () => {
    if (isPlatesTab) { setLoading(false); return; }
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: 0 };
      if (activeFilter.types) params.types = activeFilter.types.join(",");
      const r = await api.get("/events", { params });
      setEvents(r.data || []);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) { setEvents([]); } finally { setLoading(false); }
  }, [activeFilter, isPlatesTab]);

  useEffect(() => { load(); }, [load]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const params = { limit: PAGE_SIZE, offset: events.length };
      if (activeFilter.types) params.types = activeFilter.types.join(",");
      const r = await api.get("/events", { params });
      setEvents((prev) => [...prev, ...(r.data || [])]);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) {} finally { setLoadingMore(false); }
  };

  const openDetail = (e) => {
    setDetailId(e.id);
    setDetail(e);
    setRecInfo(null);
    setShowVideo(false);
    api.get(`/events/${e.id}`).then((r) => setDetail(r.data)).catch(() => {});
  };
  const closeDetail = () => { setDetailId(null); setDetail(null); setRecInfo(null); setShowVideo(false); };

  const playEventVideo = async () => {
    if (!detailId) return;
    setRecLoading(true);
    try {
      const { data } = await api.get(`/events/${detailId}/recording`);
      const token = localStorage.getItem("mg_token") || "";
      const offset = Math.max(0, data.offset_sec || 0);
      const url = `${process.env.REACT_APP_BACKEND_URL}/api${data.stream_url}?token=${encodeURIComponent(token)}&t=${offset}`;
      setRecInfo({ ...data, url });
      setShowVideo(true);
    } catch (e) {
      toast.error(e.response?.status === 404 ? t("mobile.events_video_unavailable") : t("mobile.events_video_failed"));
    } finally { setRecLoading(false); }
  };

  return (
    <div className="p-2" data-testid="mobile-events-list">
      <div className="flex gap-1.5 overflow-x-auto pb-2 -mx-2 px-2" style={{ touchAction: "pan-x" }} data-testid="mobile-events-filter-chips">
        {FILTERS.map((f) => {
          const F = f.icon;
          const active = filtre === f.id;
          return (
            <button key={f.id} onClick={() => setFiltre(f.id)} data-testid={`mobile-events-filter-${f.id}`}
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs border ${
                      active ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] font-medium" : "border-border text-muted-foreground"
                    }`}>
              <F size={13} /> {t(f.labelKey)}
            </button>
          );
        })}
        {/* v3.107 · Onglet mobile-only, demande explicite — n'existe pas
            dans `FILTERS` (partagé avec le bureau), ajouté séparément ici. */}
        <button onClick={() => setFiltre("plaques")} data-testid="mobile-events-filter-plaques"
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs border ${
                  isPlatesTab ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] font-medium" : "border-border text-muted-foreground"
                }`}>
          <CreditCard size={13} /> {t("mobile.events_filter_plates")}
        </button>
      </div>

      {isPlatesTab ? (
        <PlatesTab onSelectVehicle={openVehicle} />
      ) : loading ? (
        <div className="flex items-center justify-center text-muted-foreground py-16" data-testid="mobile-events-loading">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : events.length === 0 ? (
        <div className="text-muted-foreground text-sm py-16 text-center">{t("mobile.events_empty")}</div>
      ) : (
        <div className="flex flex-col gap-2">
          {events.map((e) => (
            <button key={e.id} onClick={() => openDetail(e)} data-testid="mobile-event-card"
                    className="flex items-center gap-3 rounded-xl border border-border bg-card p-2 text-left">
              <div className="relative w-20 h-14 shrink-0 bg-black rounded-lg overflow-hidden">
                {(e.thumbnail_sm || e.thumbnail) ? (
                  <img src={e.thumbnail_sm || e.thumbnail} alt={e.type} className="w-full h-full object-cover" loading="lazy" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center"><CamIcon size={16} className="text-white/30" /></div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: eventTypeColor(e.type) }} />
                  <span className="text-sm truncate">{eventTypeLabel(e.type, t)}</span>
                </div>
                <div className="text-[11px] text-muted-foreground truncate">{e.camera_name}</div>
                <div className="text-[11px] mono text-muted-foreground">{new Date(e.timestamp).toLocaleString("fr-FR")}</div>
                {e.plate && (
                  <button onClick={(ev) => { ev.stopPropagation(); openVehicleFromEvents(e.plate); }}
                          data-testid="mobile-event-plate-link"
                          className="text-[11px] mono font-bold mt-0.5 underline decoration-dotted">
                    {e.plate}
                  </button>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
      {!isPlatesTab && hasMore && (
        <div className="flex justify-center pt-3">
          <button onClick={loadMore} disabled={loadingMore} data-testid="mobile-events-load-more"
                  className="flex items-center gap-2 px-4 py-2 rounded-full border border-border text-xs uppercase tracking-wider text-muted-foreground disabled:opacity-50">
            {loadingMore && <Loader2 size={13} className="animate-spin" />}
            {t("mobile.events_load_more")}
          </button>
        </div>
      )}

      {detailId && (
        // v3.103 · Fond/texte reconstruits sur les tokens de thème (même
        // correctif que VehicleDetail ci-dessus — bug identique, même
        // fichier) au lieu de `bg-black/95`+`text-white` codés en dur.
        <div className="fixed inset-0 z-50 bg-background flex flex-col" data-testid="mobile-event-detail">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-foreground text-sm truncate">{detail?.camera_name}</span>
            <button onClick={closeDetail} data-testid="mobile-event-detail-close" className="text-foreground p-1">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center p-2 min-h-0 overflow-hidden bg-black">
            {showVideo && recInfo ? (
              <video src={recInfo.url} controls autoPlay className="w-full h-full object-contain bg-black"
                     onLoadedMetadata={(e) => { e.currentTarget.currentTime = Math.max(0, recInfo.offset_sec || 0); }}
                     data-testid="mobile-event-video" />
            ) : (detail?.thumbnail || detail?.thumbnail_sm) ? (
              <MobileMagnifier src={detail.thumbnail || detail.thumbnail_sm} alt={detail.type} className="max-w-full max-h-full object-contain" />
            ) : (
              <CamIcon size={40} className="text-white/30" />
            )}
          </div>
          <div className="px-3 py-3 border-t border-border text-foreground text-sm space-y-1.5 overflow-y-auto max-h-[40%]">
            {!showVideo && (
              <button onClick={playEventVideo} disabled={recLoading} data-testid="mobile-event-play-video-btn"
                      className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-[#0044FF] disabled:opacity-50">
                {recLoading ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />}
                {t("mobile.events_play_video")}
              </button>
            )}
            {detail?.type && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: eventTypeColor(detail.type) }} />
                <span className="font-medium">{eventTypeLabel(detail.type, t)}</span>
              </div>
            )}
            <div className="text-muted-foreground text-xs">{detail && new Date(detail.timestamp).toLocaleString("fr-FR")}</div>
            {detail?.site_name && <div className="text-xs text-muted-foreground">{t("mobile.events_detail_site")}: {detail.site_name}</div>}
            {detail?.plate && (
              <button onClick={() => openVehicleFromEvents(detail.plate)} data-testid="mobile-event-detail-plate-link"
                      className="mono font-bold text-base underline decoration-dotted">
                {detail.plate}
              </button>
            )}
            {(detail?.vehicle_make || detail?.vehicle_model) && (
              <div className="text-xs text-muted-foreground">{[detail.vehicle_make, detail.vehicle_model, detail.vehicle_color].filter(Boolean).join(" · ")}</div>
            )}
            {detail?.vehicle_type && <div className="text-xs text-muted-foreground">{t("mobile.events_detail_vehicle_type")}: {detail.vehicle_type}</div>}
            {detail?.direction && <div className="text-xs text-muted-foreground">{t("mobile.events_detail_direction")}: {detail.direction}</div>}
            {detail?.confidence != null && <div className="text-xs text-muted-foreground">{t("mobile.events_detail_confidence")}: {Math.round(detail.confidence * 100)}%</div>}
            {detail?.motion_pct != null && <div className="text-xs text-muted-foreground">{t("mobile.events_detail_motion")}: {detail.motion_pct}%</div>}
          </div>
        </div>
      )}

      {vehiclePlate && (
        <VehicleDetail plate={vehiclePlate} onClose={closeVehicle} onPrev={prevVehicle} onNext={nextVehicle}
                       hasPrev={vehicleNav.list.length > 1} hasNext={vehicleNav.list.length > 1} />
      )}
    </div>
  );
}
