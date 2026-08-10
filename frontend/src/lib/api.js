import axios from "axios";

// v1.0-rc4.5 · URLs relatives obligatoires en production.
// Le Dockerfile force REACT_APP_BACKEND_URL="" pour la build prod, donc
// baseURL devient "/api" (same-origin, proxifié par Nginx vers backend:8001).
// En dev (`yarn start`), REACT_APP_BACKEND_URL est lu depuis .env local.
const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

const api = axios.create({ baseURL: API });

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
        localStorage.removeItem("mg_token");
        localStorage.removeItem("mg_refresh");
        if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
          window.location.href = "/login";
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
