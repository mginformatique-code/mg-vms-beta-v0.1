# MG-VMS v0.5.1.b · Rapport Sécurité + Production

**Date** : Février 2026 · **Cible** : Release Candidate v1.0

## Résumé exécutif

MG-VMS peut désormais être déployé en production chez un client dans un
socle sécurisé minimal : reverse-proxy TLS Nginx, certificats Let's Encrypt
auto-renouvelés, headers OWASP complets, rate limiting brute-force, secrets
obligatoires par variable d'environnement, backend/go2rtc/frontend non
exposés directement à Internet.

**Score sécurité (auto-évalué)** : **8/10** (voir §Points ouverts).

## Livrables

| Artefact | Rôle |
|---|---|
| `deploy-app/nginx.conf` | Terminaison TLS + rate limit + headers OWASP + reverse-proxy |
| `deploy-app/nginx-proxy_backend.conf` | Snippet include (headers X-Forwarded-*) |
| `deploy-app/docker-compose.prod.yml` | Nginx + Certbot + override ports + secrets obligatoires |
| `backend/server.py` (modif) | `TrustedHostMiddleware` conditionné à `MGVMS_TRUSTED_HOSTS` |
| `frontend/tests/security-production.test.js` | 29 tests structurels sécurité |
| `memory/ROADMAP.md` | Roadmap versionnée jusqu'à RC v1.0 |

## Headers HTTP appliqués

| Header | Valeur | Rôle |
|---|---|---|
| Strict-Transport-Security | `max-age=31536000; includeSubDomains; preload` | Force HTTPS 1 an sur tout sous-domaine |
| X-Frame-Options | `DENY` | Anti-clickjacking absolu |
| X-Content-Type-Options | `nosniff` | Anti MIME-sniffing |
| Referrer-Policy | `strict-origin-when-cross-origin` | Referer minimum |
| Permissions-Policy | `geolocation=() microphone=() payment=() usb=() interest-cohort=()` | Bloque APIs sensibles |
| Content-Security-Policy | `frame-ancestors 'none'; form-action 'self'; object-src 'none'; ...` | Anti-XSS multi-couches |

## Rate limiting

- **Login** : 5 requêtes/minute/IP (burst 3, HTTP 429) sur `/api/auth/login`
- **API générale** : 100 req/s/IP (burst 200) sur `/api/*`
- **Backend** : rate-limit brute-force en mémoire déjà présent (`security.py`, tracking `login_attempts`)

## TLS

- Protocoles : **TLS 1.2 + TLS 1.3** uniquement (SSLv3/TLS 1.0/1.1 refusés)
- Ciphers : suites ECDHE (Forward Secrecy) uniquement
- OCSP stapling activé
- Session tickets désactivés (protection anti-replay)
- Certificats Let's Encrypt renouvelés automatiquement toutes les 12 h (idempotent)

## Isolation réseau

En production (`docker-compose.prod.yml`) :

| Service | Exposition Internet | Accès |
|---|---|---|
| nginx | 80, 443 | ✅ public |
| backend | ❌ aucun | via nginx uniquement |
| frontend | ❌ aucun | via nginx uniquement |
| go2rtc | 8554 (RTSP LAN optionnel) + 8555 (WebRTC ICE UDP) | flux vidéo directs |
| mongo | ❌ aucun | réseau docker interne |

## Secrets

Toutes les valeurs critiques sont **obligatoires par `.env`** (fail-fast au démarrage) :
- `JWT_SECRET` — `openssl rand -hex 32`
- `ADMIN_PASSWORD` — compte initial
- `MGVMS_DOMAIN` — utilisé pour CORS + TrustedHost + REACT_APP_BACKEND_URL

**Preuve** : `docker-compose.prod.yml` utilise la syntaxe `${VAR:?message requis}` qui fait crasher le déploiement si absent.

## Uploads

- `client_max_body_size 50m` (nginx)
- `client_body_timeout 60s` (protection Slowloris)
- Endpoints upload identifiés : `/api/analyze_plate`, `/api/faces/{id}/photo`, `/api/anpr/watchlist/import`, `/api/plugins/*/config/upload` — tous derrière `require_role` / `require_permission`

## Points ouverts (à traiter avant score 10/10)

1. **CSP inclut `'unsafe-inline'` sur script/style** — requis par Tailwind runtime + React 19 hot-reload. Migration vers CSP strict nonce nécessite refonte du build (roadmap v0.5.2).
2. **Le pod cloud ne permet pas de tester le trafic HTTPS réel** — validation certbot + Nginx à faire sur machine cliente.
3. **Audit dépendances CVE** — `pip-audit` / `npm audit` à intégrer en CI.
4. **Refresh token / rotation JWT** — actuellement single JWT longue durée. Roadmap v0.5.2.
5. **Session cookies vs JWT localStorage** — trade-off connu (XSS vs CSRF). Actuellement JWT en localStorage — acceptable avec CSP stricte, mais session cookies HttpOnly + Secure = meilleur défaut.
6. **Logs sensibles** : vérifier que les logs backend ne loguent jamais password/token clair.
7. **Backup MongoDB** : script de dump chiffré + rotation à ajouter (roadmap v0.5.3).

## Réponse à la question "RC v1.0 prête ?"

**Non, pas encore** — score maturité global **68 %**.

Ce qui manque pour prétendre à RC :
- v0.5.1.a Welcome Center
- v0.5.1.f Monitoring temps réel
- Drivers Axis/Hanwha/Uniview (v0.5.2)
- Workflow Center complet (v0.5.3)
- Documentation complète (v0.5.4)
- Tests stress 30/50 caméras sur RTX A2000 (v0.5.5)

**Ce qui est prêt (>80 %)** :
- Pipeline IA · Camera Device Layer · Latence · Sécurité minimale · Docker
- **MG-VMS peut être installé chez un client pilote en conditions sécurisées**
- **MG-VMS ne peut pas encore être vendu comme produit fini**

## Instructions de déploiement client (résumé)

```bash
# Sur le serveur cible (Ubuntu 24.04 + NVIDIA Driver 550+ + nvidia-container-toolkit)
cd /opt && git clone <repo> mg-vms && cd mg-vms/deploy-app

# 1. Configurer les secrets
cp .env.example .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
sed -i "s/^MGVMS_DOMAIN=.*/MGVMS_DOMAIN=vms.exemple.com/" .env
# Éditer aussi ADMIN_PASSWORD

# 2. Créer les points de montage
sudo mkdir -p /mnt/mongodb /mnt/video-datastore/recordings
sudo chown -R 999:999 /mnt/mongodb        # uid Mongo
sudo chown -R 1000:1000 /mnt/video-datastore/recordings

# 3. Premier démarrage (sans HTTPS pour créer les certs)
docker compose -f docker-compose.yml up -d
# Vérifier que le domaine résout bien vers l'IP publique

# 4. Émission initiale du certificat Let's Encrypt
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot \
    certonly --webroot -w /var/www/certbot -d $MGVMS_DOMAIN \
    --email admin@$MGVMS_DOMAIN --agree-tos --no-eff-email

# 5. Lancement production complet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 6. Vérifications post-déploiement
curl -I https://$MGVMS_DOMAIN                # HSTS + headers OK
curl https://$MGVMS_DOMAIN/api/health        # backend OK
```
