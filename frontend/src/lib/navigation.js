/**
 * navigation.js — pont d'navigation impérative (v3.109).
 *
 * `AppContext.jsx` (WebSocket temps réel, toasts d'alerte) est monté
 * AU-DESSUS de `<BrowserRouter>` dans App.js (`<AppProvider><BrowserRouter>
 * ...</BrowserRouter></AppProvider>`) — `useNavigate()` n'y est donc pas
 * utilisable directement. Pattern standard react-router v6 pour naviguer
 * depuis du code hors composants : un petit composant `NavigationBridge`
 * rendu À L'INTÉRIEUR du Router capture `useNavigate()` une fois et
 * l'expose ici, pour que n'importe quel code (même hors arbre React) puisse
 * déclencher une navigation — demande explicite : "quand une notification
 * apparaît, cliquer dessus... il faudrait que cela amène à l'événement en
 * question".
 */
let _navigate = null;

export function setNavigate(fn) {
  _navigate = fn;
}

export function navigateTo(path, options) {
  if (_navigate) _navigate(path, options);
}
