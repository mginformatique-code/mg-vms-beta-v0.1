import React from "react";
import { useApp } from "@/context/AppContext";
import mgLogoLight from "@/assets/mg-vms-logo.png";
// Variante dark : si le fichier `mg-vms-logo-dark.png` est fourni, il sera utilisé
// en mode sombre. Sinon on retombe sur la variante light avec un fond blanc léger
// pour préserver la lisibilité (le logo original a un fond blanc + texte sombre).
// TODO : remplacer par le vrai logo dark quand disponible.
import mgLogoDark from "@/assets/mg-vms-logo.png";

/**
 * Composant Logo MG-VMS — sélectionne automatiquement la variante en fonction
 * du thème actif (clair/sombre). Utilisé partout dans l'UI pour rester DRY.
 *
 * Props :
 *   size     : taille en pixels (défaut 36) — s'applique en w+h
 *   className: classes Tailwind supplémentaires
 *   alt      : texte alternatif (défaut "MG-VMS")
 *   forceLight / forceDark : forcer une variante (utile pour Login preview)
 */
export default function Logo({ size = 36, className = "", alt = "MG-VMS",
                                forceLight = false, forceDark = false, ...rest }) {
  const { theme } = useApp();
  const isDark = forceDark || (!forceLight && theme === "dark");
  const src = isDark ? mgLogoDark : mgLogoLight;
  // En mode dark, si on utilise la variante light (fallback tant que la version dark n'est pas
  // fournie), on ajoute un fond blanc arrondi pour garder le logo lisible sur fond sombre.
  const needsWhiteBackdrop = isDark && mgLogoDark === mgLogoLight;
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={`object-contain ${needsWhiteBackdrop ? "bg-white p-0.5 rounded-md" : ""} ${className}`}
      data-testid="mg-logo"
      {...rest}
    />
  );
}
