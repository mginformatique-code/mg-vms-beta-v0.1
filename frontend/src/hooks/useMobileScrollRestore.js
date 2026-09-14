/**
 * useMobileScrollRestore — restaure la position de défilement d'une page
 * mobile en revenant dessus (v3.103, demande explicite : "si je fais un
 * retour sur une page... que ca ne me ramène pas en début de page, mais
 * là où j'ai cliqué avant").
 *
 * `MobileLayout` enveloppe CHAQUE route mobile individuellement (un
 * `<main>` distinct est démonté/remonté à chaque navigation, pas un
 * shell persistant avec `<Outlet/>`) — le scroll natif du navigateur ne
 * peut donc rien restaurer tout seul. La position est gardée dans une Map
 * en mémoire de module (survit au démontage/remontage du composant, tant
 * que l'app ne recharge pas la page), indexée par chemin d'URL complet
 * (`pathname + search`, pour distinguer par ex. deux caméras différentes
 * sur la même route paramétrée).
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const scrollPositions = new Map();

export default function useMobileScrollRestore(containerRef) {
  const location = useLocation();
  const key = location.pathname + location.search;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const saved = scrollPositions.get(key);
    if (saved != null) el.scrollTop = saved;

    const onScroll = () => scrollPositions.set(key, el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      scrollPositions.set(key, el.scrollTop);
      el.removeEventListener("scroll", onScroll);
    };
  }, [key, containerRef]);
}
