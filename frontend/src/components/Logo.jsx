import React from "react";
import { useApp } from "@/context/AppContext";
import mgLogoLight from "@/assets/mg-vms-logo-light.png";
import mgLogoDark from "@/assets/mg-vms-logo-dark.png";

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
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={`object-contain ${className}`}
      data-testid="mg-logo"
      {...rest}
    />
  );
}
