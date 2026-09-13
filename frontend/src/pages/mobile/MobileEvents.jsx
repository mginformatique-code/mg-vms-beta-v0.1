/**
 * MobileEvents — liste d'événements/alertes pour l'interface mobile (v3.91).
 *
 * Cartes verticales compactes (pas la grille 5 colonnes d'`Events.jsx`,
 * illisible sur 375px) — même endpoint `GET /events` (limit/offset), tap →
 * feuille de détail plein écran plutôt que le `EventViewer` desktop
 * (playback vidéo complet, hors périmètre mobile v1 — voir le plan).
 */
import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Camera as CamIcon, Loader2, X } from "lucide-react";

const PAGE_SIZE = 20;

const TYPE_COLOR = {
  motion: "#0044FF", person: "#00E676", vehicle: "#FFB800",
  plate: "#B47CFF", intrusion: "#FF3333", face: "#00E1FF",
};

export default function MobileEvents() {
  const { t } = useApp();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/events", { params: { limit: PAGE_SIZE, offset: 0 } });
      setEvents(r.data || []);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) { /* liste vide affichée */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const r = await api.get("/events", { params: { limit: PAGE_SIZE, offset: events.length } });
      setEvents((prev) => [...prev, ...(r.data || [])]);
      setHasMore((r.data || []).length === PAGE_SIZE);
    } catch (e) {} finally { setLoadingMore(false); }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground" data-testid="mobile-events-loading">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-2" data-testid="mobile-events-list">
      {events.length === 0 ? (
        <div className="text-muted-foreground text-sm py-16 text-center">{t("mobile.events_empty")}</div>
      ) : (
        <div className="flex flex-col gap-2">
          {events.map((e) => (
            <button key={e.id} onClick={() => setDetail(e)} data-testid="mobile-event-card"
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
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: TYPE_COLOR[e.type] || "#888" }} />
                  <span className="text-sm truncate">{e.camera_name}</span>
                </div>
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

      {detail && (
        <div className="fixed inset-0 z-50 bg-black/95 flex flex-col" data-testid="mobile-event-detail">
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
            <span className="text-white text-sm truncate">{detail.camera_name}</span>
            <button onClick={() => setDetail(null)} data-testid="mobile-event-detail-close" className="text-white p-1">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center p-2 min-h-0">
            {(detail.thumbnail || detail.thumbnail_sm) ? (
              <img src={detail.thumbnail || detail.thumbnail_sm} alt={detail.type} className="max-w-full max-h-full object-contain" />
            ) : (
              <CamIcon size={40} className="text-white/30" />
            )}
          </div>
          <div className="px-3 py-3 border-t border-white/10 text-white/80 text-sm space-y-1">
            <div>{new Date(detail.timestamp).toLocaleString("fr-FR")}</div>
            {detail.plate && <div className="mono font-bold">{detail.plate}</div>}
            {detail.confidence != null && <div className="text-xs">{Math.round(detail.confidence * 100)}%</div>}
          </div>
        </div>
      )}
    </div>
  );
}
