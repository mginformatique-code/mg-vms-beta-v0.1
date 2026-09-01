import React, { useState } from "react";
import { Eye } from "lucide-react";

// v3.21 · Champ mot de passe avec bouton "œil" — affiche le texte en clair
// UNIQUEMENT tant qu'il est maintenu enfoncé (mousedown/touchstart), et le
// recache dès qu'on relâche ou qu'on quitte le bouton (mouseup/mouseleave/
// touchend). Jamais un état persistant qu'on pourrait oublier affiché.
export default function HoldToRevealInput({ className = "", ...props }) {
  const [reveal, setReveal] = useState(false);
  const hide = () => setReveal(false);
  return (
    <div className="relative">
      <input {...props} type={reveal ? "text" : "password"} className={`${className} pr-9`} />
      <button type="button" tabIndex={-1}
        onMouseDown={() => setReveal(true)} onMouseUp={hide} onMouseLeave={hide}
        onTouchStart={() => setReveal(true)} onTouchEnd={hide}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        aria-label="Maintenir pour afficher le mot de passe">
        <Eye size={15} />
      </button>
    </div>
  );
}
