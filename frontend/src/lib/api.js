import axios from "axios";
import { diagPush } from "@/components/DiagOverlay";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const api = axios.create({ baseURL: API });

// ─── DIAG-MODE v1.0-rc4.5 P0 ─────────────────────────────────────────
// Log boot-time de la config API pour vérifier que le bundle n'a pas
// été buildé avec une URL absolue HTTP polluée.
if (typeof window !== "undefined") {
  diagPush({
    kind: "boot",
    name: "api.js",
    message: `axios baseURL = "${API}"`,
    axios: {
      baseURL: API,
      REACT_APP_BACKEND_URL: process.env.REACT_APP_BACKEND_URL || "(empty)",
      window_origin: window.location.origin,
      window_protocol: window.location.protocol,
      window_host: window.location.host,
    },
  });
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

    // ─── DIAG-MODE : capture COMPLÈTE de l'erreur axios ───
    try {
      const axiosDetail = {
        code: error.code || null,
        message: error.message || null,
        method: original?.method || null,
        url: (original?.baseURL || "") + (original?.url || ""),
        request_headers: original?.headers ? JSON.parse(JSON.stringify(original.headers)) : null,
        request_data: original?.data || null,
        status: status ?? null,
        statusText: error.response?.statusText || null,
        response_headers: error.response?.headers || null,
        response_data: error.response?.data ?? null,
        has_response: !!error.response,
        has_request: !!error.request,
      };
      // Attach detail to the error object so unhandledrejection listener
      // can pick it up too (via reason.__mgvms_axios).
      try { error.__mgvms_axios = axiosDetail; } catch (e) { /* ignore */ }
      diagPush({
        kind: "axios-error",
        name: error.name || "AxiosError",
        message: error.message || "(no message)",
        stack: error.stack || null,
        axios: axiosDetail,
      });
    } catch (e) { /* never break the interceptor */ }

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
