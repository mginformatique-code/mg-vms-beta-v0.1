/**
 * MobileEvents — liste d'événements/alertes pour l'interface mobile (v3.91,
 * corrigé/enrichi v3.94).
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
 */
import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { FILTERS, eventTypeColor, eventTypeLabel } from "@/pages/Events";
import { Camera as CamIcon, Loader2, X, CreditCard } from "lucide-react";

const PAGE_SIZE = 20;

function PlatesSection() {
  const { t } = useApp();
  const [plates, setPlates] = useState(null);
  useEffect(() => {
    let alive = true;
    api.get("/plates", { params: { limit: 10 } }).then((r) => { if (alive) setPlates(r.data || []); }).catch(() => { if (alive) setPlates([]); });
    return () => { alive = false; };
  }, []);
  if (plates === null) return null;
  if (plates.length === 0) return null;
  return (
    <div className="mb-3" data-testid="mobile-events-plates-section">
      <div className="flex items-center gap-1.5 px-1 pb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
        <CreditCard size={13} /> {t("mobile.events_plates_title")}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1" style={{ touchAction: "pan-x" }}>
        {plates.map((p) => (
          <div key={p.id} data-testid="mobile-plate-card"
               className="shrink-0 w-32 border border-border bg-card p-2">
            <div className="text-sm font-bold mono truncate">{p.plate}</div>
            <div className="text-[10px] text-muted-foreground truncate">{p.camera_name}</div>
            <div className="text-[10px] mono text-muted-foreground">{new Date(p.timestamp).toLocaleTimeString("fr-FR")}</div>
            {p.list_status && p.list_status !== "none" && (
              <div className={`text-[9px] uppercase font-bold mt-1 ${p.list_status === "black" ? "text-[#FF3333]" : "text-[#FFB800]"}`}>
                {p.list_status === "black" ? t("mobile.events_plate_blacklist") : t("mobile.events_plate_whitelist")}
              </div>
            )}
          </div>
        ))}
      </div>
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
  const isPlaques = filtre === "tous";
  const activeFilter = FILTERS.find((f) => f.id === filtre) || FILTERS[0];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: 0 };
      if (activeFilter.types) params.types = activeFilter.types.join(",");
      const r = await api.get("/events", { params });
      setEvents(r.data || []);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) { setEvents([]); } finally { setLoading(false); }
  }, [activeFilter]);

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
    api.get(`/events/${e.id}`).then((r) => setDetail(r.data)).catch(() => {});
  };
  const closeDetail = () => { setDetailId(null); setDetail(null); };

  return (
    <div className="p-2" data-testid="mobile-events-list">
      <div className="flex gap-1.5 overflow-x-auto pb-2 -mx-2 px-2" style={{ touchAction: "pan-x" }} data-testid="mobile-events-filter-chips">
        {FILTERS.map((f) => {
          const F = f.icon;
          const active = filtre === f.id;
          return (
            <button key={f.id} onClick={() => setFiltre(f.id)} data-testid={`mobile-events-filter-${f.id}`}
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs border ${
                      active ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] font-medium" : "border-border text-muted-foreground"
                    }`}>
              <F size={13} /> {t(f.labelKey)}
            </button>
          );
        })}
      </div>

      {isPlaques && <PlatesSection />}

      {loading ? (
        <div className="flex items-center justify-center text-muted-foreground py-16" data-testid="mobile-events-loading">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : events.length === 0 ? (
        <div className="text-muted-foreground text-sm py-16 text-center">{t("mobile.events_empty")}</div>
      ) : (
        <div className="flex flex-col gap-2">
          {events.map((e) => (
            <button key={e.id} onClick={() => openDetail(e)} data-testid="mobile-event-card"
                    className="flex items-center gap-3 border border-border bg-card p-2 text-left">
              <div className="relative w-20 h-14 shrink-0 bg-black overflow-hidden">
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
                {e.plate && <div className="text-[11px] mono font-bold mt-0.5">{e.plate}</div>}
              </div>
            </button>
          ))}
        </div>
      )}
      {hasMore && (
        <div className="flex justify-center pt-3">
          <button onClick={loadMore} disabled={loadingMore} data-testid="mobile-events-load-more"
                  className="flex items-center gap-2 px-4 py-2 border border-border text-xs uppercase tracking-wider text-muted-foreground disabled:opacity-50">
            {loadingMore && <Loader2 size={13} className="animate-spin" />}
            {t("mobile.events_load_more")}
          </button>
        </div>
      )}

      {detailId && (
        <div className="fixed inset-0 z-50 bg-black/95 flex flex-col" data-testid="mobile-event-detail">
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
            <span className="text-white text-sm truncate">{detail?.camera_name}</span>
            <button onClick={closeDetail} data-testid="mobile-event-detail-close" className="text-white p-1">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center p-2 min-h-0 overflow-hidden">
            {(detail?.thumbnail || detail?.thumbnail_sm) ? (
              <img src={detail.thumbnail || detail.thumbnail_sm} alt={detail.type} className="max-w-full max-h-full object-contain" />
            ) : (
              <CamIcon size={40} className="text-white/30" />
            )}
          </div>
          <div className="px-3 py-3 border-t border-white/10 text-white/90 text-sm space-y-1.5 overflow-y-auto max-h-[40%]">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: eventTypeColor(detail?.type) }} />
              <span className="font-medium">{eventTypeLabel(detail?.type, t)}</span>
            </div>
            <div className="text-white/70 text-xs">{detail && new Date(detail.timestamp).toLocaleString("fr-FR")}</div>
            {detail?.site_name && <div className="text-xs text-white/70">{t("mobile.events_detail_site")}: {detail.site_name}</div>}
            {detail?.plate && <div className="mono font-bold text-base">{detail.plate}</div>}
            {(detail?.vehicle_make || detail?.vehicle_model) && (
              <div className="text-xs text-white/70">{[detail.vehicle_make, detail.vehicle_model, detail.vehicle_color].filter(Boolean).join(" · ")}</div>
            )}
            {detail?.vehicle_type && <div className="text-xs text-white/70">{t("mobile.events_detail_vehicle_type")}: {detail.vehicle_type}</div>}
            {detail?.direction && <div className="text-xs text-white/70">{t("mobile.events_detail_direction")}: {detail.direction}</div>}
            {detail?.confidence != null && <div className="text-xs text-white/70">{t("mobile.events_detail_confidence")}: {Math.round(detail.confidence * 100)}%</div>}
            {detail?.motion_pct != null && <div className="text-xs text-white/70">{t("mobile.events_detail_motion")}: {detail.motion_pct}%</div>}
            {detail?.list_status && detail.list_status !== "none" && (
              <div className={`text-xs font-bold uppercase ${detail.list_status === "black" ? "text-[#FF3333]" : "text-[#FFB800]"}`}>
                {detail.list_status === "black" ? t("mobile.events_plate_blacklist") : t("mobile.events_plate_whitelist")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
