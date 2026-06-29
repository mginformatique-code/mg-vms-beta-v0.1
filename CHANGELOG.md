# CHANGELOG — MG-VMS

Format inspiré de Keep a Changelog. Dates au format AAAA-MM.

## [1.3.0] — 2026-06 — Sprint 2 : Temps réel (P1)
### Ajouté
- **WebSocket** `/api/ws` (authentifié par token, cloisonné par site) : push live des **métriques système** (toutes les 5s) et des **alertes** (à la création). Reconnexion auto côté front.
- **Métriques système réelles** via **psutil** dans `/api/dashboard/stats` (CPU/RAM/stockage/température/bande passante/uptime) — remplacent les valeurs aléatoires.
- **Pagination serveur** non-cassante sur `/plates`, `/events`, `/alerts`, `/audit` : params `limit`/`offset` + header `X-Total-Count` (le corps reste un tableau JSON). UI « Charger plus » sur ANPR et Audit.
- **Front** : indicateur « LIVE » (topbar), toasts d'alerte temps réel, badge d'alertes live, rechargement auto du dashboard/alertes sur nouvelle alerte.
- `POST /api/alerts` : `broadcast_alert` ; `site_id` désormais honoré (alerte rattachable à un site sans caméra) ; `test_camera` diffuse le changement de statut.
### Tests
- 12/12 Sprint 2 + 30/30 régression = **42/42 backend**, frontend 100% (itération 6).

## [1.2.0] — 2026-06 — Sprint 1 : Sécurité (P1)
### Ajouté
- **Anti brute-force** : verrouillage du compte 15 min après 5 échecs (clé IP:email, collection `login_attempts`), HTTP 423.
- **Rate-limiting** des endpoints sensibles (`/auth/login` 10/min, `/auth/forgot-password` 5/5min, `/auth/reset-password` 10/5min), HTTP 429 + `Retry-After`.
- **Reset password** : `POST /auth/forgot-password` (réponse générique anti-énumération) + `POST /auth/reset-password` (jeton `secrets`, TTL 1h, usage unique), envoi best-effort par SMTP si configuré.
- **En-têtes de sécurité OWASP** sur toutes les réponses (X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy, X-XSS-Protection) via `SecurityMiddleware`.
- **Cloisonnement par site** : helpers `allowed_sites()` / `site_scope()` appliqués à sites, caméras, événements, plaques, alertes et dashboard. `site_ids` assignables par l'admin (UI Users + `PUT /users/{id}`).
- **Refresh token câblé** côté frontend : intercepteur axios qui rafraîchit l'access token sur 401 et rejoue la requête ; stockage `mg_refresh`.
- **Frontend** : flux « Mot de passe oublié », page `/reset-password`, dialog d'affectation des sites par utilisateur.
### Modifié
- **CORS** restreint à l'origine explicite du frontend (au lieu de `*`).
- Cookie `access_token` passé en `secure=True`.
- Seed : `client` rattaché au 1er site, `viewer` au 2e (démo du cloisonnement).
### Sécurité
- Tests : 17/17 backend + parcours frontend validés (itération 5).

## [1.1.0] — 2026-06 — Notifications & Intégrations
### Ajouté
- Canaux SMTP / Discord / Telegram configurables dans l'UI (admin), secrets chiffrés (Fernet) et masqués en lecture, test d'envoi par canal, activation/désactivation.
- Envoi automatique sur alerte critique (`POST /alerts` + BackgroundTasks).
- Tests : 20/20 backend + 14/14 frontend.

## [1.0.0] — 2026-06 — MVP initial
### Ajouté
- Auth JWT + RBAC (admin/technicien/client/lecture seule/invité) + 2FA TOTP.
- Multi-sites, gestion caméras (RTSP/ONVIF config, test, snapshot, PTZ — simulés).
- Mur vidéo (1→64), dashboard (KPI + graphiques), ANPR (recherche, watchlist, export CSV, analyse IA d'image), recherche véhicule, alertes, carte OSM, audit, gestion utilisateurs, paramètres.
- Bilingue FR/EN, thèmes clair/sombre.
- Tests : 30/30 backend + parcours frontend.
