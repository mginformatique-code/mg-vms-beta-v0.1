import axios from "axios";

// v1.0-rc4.5 · URLs relatives obligatoires en production.
// Le Dockerfile force REACT_APP_BACKEND_URL="" pour la build prod, donc
// baseURL devient "/api" (same-origin, proxifié par Nginx vers backend:8001).
// En dev (`yarn start`), REACT_APP_BACKEND_URL est lu depuis .env local.
const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

const api = axios.create({ baseURL: API });

// v1.0-rc4.5 · Audit UI · Redirect /login intelligent
// -----------------------------------------------------------------------------
// Une 401 sur un endpoint SECONDAIRE (capabilities, diagnostics, streams
// info, plugins) ne doit JAMAIS détruire la session globale et vider le
// Camera Center. Seuls les endpoints CRITIQUES (auth core, listes racines)
// déclenchent le redirect quand le refresh échoue.
//
// Sur un endpoint secondaire, on rejette simplement la promesse ; l'UI locale
// gère l'erreur avec un fallback (badge "—", "non disponible", etc.) sans
// arracher l'utilisateur de son écran.
const CRITICAL_PATHS = [
  "/auth/me",
  "/auth/refresh",
  "/cameras",       // liste racine (nav)
  "/sites",
  "/system/",
];

function _isCriticalPath(url) {
  if (!url) return false;
  return CRITICAL_PATHS.some((p) => url === p || url.startsWith(p));
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("mg_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const url = original?.url || "";
    const isAuthCall = url.includes("/auth/login") || url.includes("/auth/refresh") || url.includes("/auth/logout");

    if (status === 401 && !original._retry && !isAuthCall) {
      const refresh = localStorage.getItem("mg_refresh");
      if (!refresh) {
        localStorage.removeItem("mg_token");
        return Promise.reject(error);
      }
      original._retry = true;
      try {
        if (!refreshing) {
          refreshing = axios.post(`${API}/auth/refresh`, {}, { headers: { Authorization: `Bearer ${refresh}` } })
            .then((r) => r.data.access_token)
            .finally(() => { refreshing = null; });
        }
        const newToken = await refreshing;
        localStorage.setItem("mg_token", newToken);
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch (e) {
        // Le refresh a échoué. Le comportement dépend de l'importance de la
        // requête d'origine :
        //   - endpoint CRITIQUE (/auth/me, /cameras, /sites, /system/) →
        //     vider le token et rediriger vers /login (session vraiment perdue)
        //   - endpoint SECONDAIRE (/devices/xxx/capabilities, /diagnostics/*,
        //     /plugins, etc.) → rejeter simplement l'erreur ; l'UI locale
        //     affichera "non disponible" sans arracher l'utilisateur.
        if (_isCriticalPath(url)) {
          localStorage.removeItem("mg_token");
          localStorage.removeItem("mg_refresh");
          if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
            window.location.href = "/login";
          }
        }
        return Promise.reject(e);
      }
    }
    return Promise.reject(error);
  }
);

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Une erreur est survenue.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export default api;
