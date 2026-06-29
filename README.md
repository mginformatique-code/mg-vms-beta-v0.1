# MG-VMS — Plateforme d'hypervision vidéo (par MG Informatique)

Plateforme web professionnelle de vidéosurveillance / VMS : multi-sites, gestion caméras, mur vidéo, ANPR, recherche véhicule, alertes, notifications (SMTP/Discord/Telegram), audit, RBAC, 2FA.

## Stack (environnement actuel)
- **Backend** : FastAPI + MongoDB (Motor) — auth JWT, RBAC 5 rôles, 2FA TOTP
- **Frontend** : React 19 + Tailwind + shadcn/ui (bilingue FR/EN, thèmes clair/sombre)
- **Exécution** : services gérés par supervisor (backend :8001, frontend :3000), routage `/api` via ingress

> Note : l'architecture micro-services cible (PostgreSQL, FFmpeg, AI Engine GPU, MinIO, monitoring) est fournie comme **artefacts de production** dans `/deploy` (non exécutables dans cet environnement de développement). Voir `AUDIT_MG-VMS.md`.

## Démarrage (dev)
Les services tournent déjà via supervisor. Pour redémarrer :
```
sudo supervisorctl restart backend frontend
```

## Comptes de démonstration
| Email | Mot de passe | Rôle | Périmètre |
|---|---|---|---|
| admin@mg-vms.com | Admin@2026 | admin | Tous les sites |
| tech@mg-vms.com | Tech@2026 | technician | Tous les sites |
| client@mg-vms.com | Client@2026 | client | Mairie Centrale |
| viewer@mg-vms.com | Viewer@2026 | readonly | 2e site |

## Sécurité (Sprint 1)
- JWT access (8h) + refresh (7j) avec rafraîchissement auto côté front
- Anti brute-force (verrouillage 15 min après 5 échecs) + rate-limiting des endpoints d'auth
- Reset password (jeton à usage unique, TTL 1h)
- En-têtes OWASP (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy)
- CORS restreint à l'origine du frontend
- Cloisonnement par site (permissions RBAC + `site_ids`)
- 2FA TOTP, journal d'audit complet

## Documentation
- `AUDIT_MG-VMS.md` — audit d'architecture complet
- `CHANGELOG.md` — historique des versions
- `memory/PRD.md` — exigences produit & roadmap
- `/docs` (API) — Swagger auto-généré sur `/docs`

© MG Informatique
