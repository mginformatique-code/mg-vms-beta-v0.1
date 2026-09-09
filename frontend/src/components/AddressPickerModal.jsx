// v3.58 · Sélection de l'emplacement initial d'une carte live PAR ADRESSE
// (avec suggestions au fil de la frappe) plutôt que par latitude/longitude
// saisies à la main — demande explicite, remplace les deux window.prompt
// précédents dans MapCenter.jsx::createLiveMap. Géocodage via Nominatim
// (OpenStreetMap) : gratuit, sans clé API, même philosophie "sans coût"
// que les fonds de carte OSM/Esri déjà utilisés par cette fonctionnalité.
// Relayé par le backend (GET /api/site-manager/geocode) — Nominatim ne
// renvoie aucun en-tête CORS, un appel direct depuis le navigateur est
// donc bloqué (vérifié en direct).
import React, { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { MapPin, LocateFixed, Search } from "lucide-react";
import api from "@/lib/api";

// Nominatim demande un débit raisonnable (politique d'usage public) — un
// débounce de 450ms évite une requête par frappe clavier, largement
// suffisant pour un usage interactif ponctuel (création d'une carte),
// jamais une recherche en masse.
const DEBOUNCE_MS = 450;

export default function AddressPickerModal({ open, onClose, onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (!open) { setQuery(""); setResults([]); setSearching(false); }
  }, [open]);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (query.trim().length < 3) { setResults([]); return undefined; }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await api.get("/site-manager/geocode", { params: { q: query } });
        setResults(Array.isArray(data) ? data : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const pick = (lat, lng) => {
    onPick(parseFloat(lat), parseFloat(lng));
    onClose();
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (p) => pick(p.coords.latitude, p.coords.longitude),
      () => {},
      { timeout: 5000 }
    );
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent data-testid="address-picker-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><MapPin size={16} /> Emplacement de la carte</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Adresse, ville, lieu-dit…"
              className="w-full bg-secondary/30 border border-border pl-8 pr-3 py-2 text-sm focus:outline-none focus:border-[#0044FF] transition"
              data-testid="address-picker-input"
            />
          </div>

          {searching && <div className="text-xs text-muted-foreground">Recherche…</div>}

          {results.length > 0 && (
            <div className="border border-border divide-y divide-border max-h-56 overflow-y-auto" data-testid="address-picker-results">
              {results.map((r) => (
                <button
                  key={r.place_id}
                  onClick={() => pick(r.lat, r.lon)}
                  className="w-full text-left px-3 py-2 text-xs hover:bg-secondary/50 transition"
                  data-testid="address-picker-result"
                >
                  {r.display_name}
                </button>
              ))}
            </div>
          )}

          <button
            onClick={useMyLocation}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs border border-border hover:bg-secondary/50 transition"
            data-testid="address-picker-geolocate"
          >
            <LocateFixed size={13} /> Utiliser ma position actuelle
          </button>

          <p className="text-[10px] text-muted-foreground">
            Recherche d'adresse via OpenStreetMap (Nominatim) — gratuit, sans clé API.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
