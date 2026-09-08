import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Loader2, ShieldAlert } from "lucide-react";
import Logo from "@/components/Logo";

// v3.53 · Page d'atterrissage publique du SSO « Ouvrir MG-VMS » (MG-VMS
// Center). Le code ?code= vient d'être minté là-bas par un admin déjà
// authentifié ; ce composant l'échange contre une vraie session locale
// via POST /api/mgvms-center/sso/redeem (le backend rappelle LUI-MÊME le
// Center pour vérifier le code — jamais ce navigateur directement).
export default function SsoRedirect() {
  const { setUser } = useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState("");
  const ranOnce = useRef(false);

  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;
    const code = searchParams.get("code");
    if (!code) { setError("Lien SSO invalide : code manquant."); return; }

    const run = async () => {
      try {
        const { data } = await api.post("/mgvms-center/sso/redeem", { code });
        localStorage.setItem("mg_token", data.access_token);
        sessionStorage.setItem("mg_just_logged_in", "1");
        const me = await api.get("/auth/me");
        setUser(me.data);
        navigate("/", { replace: true });
      } catch (err) {
        setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
      }
    };
    run();
  }, [searchParams, navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background text-foreground">
      <div className="flex flex-col items-center gap-4 max-w-sm text-center px-6">
        <Logo className="h-10 w-auto" />
        {error ? (
          <>
            <ShieldAlert className="h-8 w-8 text-destructive" />
            <p className="text-sm text-muted-foreground">{error}</p>
            <a href="/login" className="text-sm text-primary underline underline-offset-4">
              Aller à la page de connexion
            </a>
          </>
        ) : (
          <>
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Connexion via MG-VMS Center…</p>
          </>
        )}
      </div>
    </div>
  );
}
