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
// info, plugins, camera detail...) ne doit JAMAIS détruire la session
// globale. Seul `/auth/me` (endpoint vital utilisé par Protected/AppContext
// pour valider la session) déclenche un redirect quand le refresh échoue.
//
// Rationale : si le refresh a échoué mais que le user est en train de
// consulter /camera-center/xxx, on préfère afficher un toast d'erreur
// que d'arracher l'utilisateur de sa page. Il se rebranchera au prochain
// changement de route via Protected.
const CRITICAL_PATHS = ["/auth/me"];

function _isCriticalPath(url) {
  if (!url) return false;
  return CRITICAL_PATHS.some((p) => url === p || url.startsWith(p));
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("mg_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // v1.0-rc4.5 · Ring buffer axios pour AppDebugPanel onglet Réseau
  if (typeof window !== "undefined") {
    config.__mgvms_t0 = performance.now();
  }
  return config;
});

// v1.0-rc4.5 · Ring buffer des 100 derniers appels axios
function _recordAxios(entry) {
  if (typeof window === "undefined") return;
  window.__mgvms_axios_history = window.__mgvms_axios_history || [];
  window.__mgvms_axios_history.push({ ts: new Date().toISOString(), ...entry });
  if (window.__mgvms_axios_history.length > 100) {
    window.__mgvms_axios_history.splice(0, window.__mgvms_axios_history.length - 100);
  }
}

let refreshing = null;

api.interceptors.response.use(
  (res) => {
    _recordAxios({
      kind: "response",
      method: (res.config.method || "get").toUpperCase(),
      url: (res.config.baseURL || "") + (res.config.url || ""),
      status: res.status,
      duration_ms: res.config.__mgvms_t0
        ? Math.round(performance.now() - res.config.__mgvms_t0) : null,
      bytes: Number(res.headers?.["content-length"]) || null,
    });
    return res;
  },
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const url = original?.url || "";
    const isAuthCall = url.includes("/auth/login") || url.includes("/auth/refresh") || url.includes("/auth/logout");

    _recordAxios({
      kind: "error",
      method: (original?.method || "get").toUpperCase(),
      url: (original?.baseURL || "") + (original?.url || ""),
      status: status ?? null,
      duration_ms: original?.__mgvms_t0
        ? Math.round(performance.now() - original.__mgvms_t0) : null,
      code: error.code || null,
      message: error.message || null,
      has_response: !!error.response,
    });

    if (status === 401 && !original._retry && !isAuthCall) {
      const refresh = localStorage.getItem("mg_refresh");
      if (!refresh) {
        localStorage.removeItem("mg_token");
        return Promise.reject(error);
      }
      original._retry = true;
      try {
        if (!refreshing) {
          // v3.1.1 · Le backend fait une rotation à usage unique du refresh
          // token (blackliste l'ancien à chaque appel /auth/refresh). Si on
          // ne persiste pas le nouveau ici, le 2e 401 de la session (n'importe
          // où) réutilise un refresh token déjà consommé → le backend détecte
          // la réutilisation et révoque TOUTES les sessions → déconnexion.
          refreshing = axios.post(`${API}/auth/refresh`, {}, { headers: { Authorization: `Bearer ${refresh}` } })
            .then((r) => {
              if (r.data.refresh_token) localStorage.setItem("mg_refresh", r.data.refresh_token);
              return r.data.access_token;
            })
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
