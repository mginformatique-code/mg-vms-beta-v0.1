# v0.7.f · Wave G — YAML Prod Fix + Paramètres HTTPS / TLS · Rapport

**Objectif** : corriger le YAML `docker-compose.prod.yml` (blocker prod TLS)
et livrer un sous-menu complet **HTTPS / TLS** dans le Centre de sécurité
pour gérer domaines local/externe, certificats, génération auto-signée.

---

## 1. YAML Prod Fix — cause racine + correction

**Cause racine** : ligne 55 (et 53-54)

```yaml
MGVMS_DOMAIN: ${MGVMS_DOMAIN:?MGVMS_DOMAIN requis (ex: vms.exemple.com)}
                                                       ^
                                     Ce `:` casse le parsing YAML —
                                     `docker compose config` interprète
                                     jusqu'au premier `:` comme un mapping.
```

**Fix** : quoting explicite + suppression du `:` dans le message d'erreur

```yaml
JWT_SECRET: "${JWT_SECRET:?JWT_SECRET requis (générer via openssl rand -hex 32)}"
ADMIN_PASSWORD: "${ADMIN_PASSWORD:?ADMIN_PASSWORD requis (compte initial)}"
MGVMS_DOMAIN: "${MGVMS_DOMAIN:?MGVMS_DOMAIN requis (ex vms.exemple.com)}"
```

**Validation** : `python3 -c "import yaml; yaml.load(...)" → OK`, tous
les scalars sont uniques (test `TestDockerComposeProdYaml`).

---

## 2. Nouveau sous-menu HTTPS / TLS

### Backend — `backend/routes/tls.py` (340 lignes)

Router `/api/security/tls/*` (permissions `admin`) :

| Endpoint | Rôle |
|----------|------|
| `GET /config` | Domaines + liste certs + cert actif + statut Let's Encrypt |
| `PUT /domains` | Set local/external domain, force_https, HSTS, HSTS max-age |
| `GET /certificates` | Alias `/config` (compat) |
| `GET /certificates/{cid}` | Détail parsé (CN, SAN, dates, empreinte, self-signed) |
| `GET /certificates/{cid}/pem` | Export PEM cert (+ clé si `?include_key=true`, audité) |
| `POST /certificates/upload` | Import cert + clé PEM avec vérification match cert/key |
| `POST /certificates/self-signed` | Génère paire RSA 2048/3072/4096 + certificat X.509 avec CN + SAN (DNS + IPs) |
| `PUT /certificates/{cid}/activate` | Désactive tous les autres, active celui-ci |
| `DELETE /certificates/{cid}` | Refuse la suppression du cert actif (409) |

### Sécurité

- Clé privée **chiffrée AES-GCM 256** avant persistance Mongo — dérivée
  de `JWT_SECRET` via SHA-256
- Nonce aléatoire 96 bits + authentification associée `mgvms-tls-key`
- Jamais stockée en clair
- Round-trip validé par test `TestPrivateKeyEncryption`

### Validation

- Hostname RFC 1123 (regex stricte, labels ≤ 63 chars)
- Match cert/key vérifié à l'upload (`priv.public_key().public_numbers()
  == cert.public_key().public_numbers()`)
- Clé RSA restreinte à 2048/3072/4096 bits
- Validité 1 - 3650 jours
- Toutes les mutations tracées dans `audit_logs`

### Frontend — `frontend/src/pages/TlsSettings.jsx` (477 lignes)

Route `/security-center/tls` — page complète et intuitive :

**4 tuiles résumé** en tête :
- Domaine externe / Domaine local (chip mono)
- Force HTTPS (Activé / Désactivé)
- Let's Encrypt (Détecté / Non configuré)

**Panneau Domaines & routing** :
- Domaine LAN (mdns / DNS interne)
- Domaine externe (Internet public)
- Toggle Force HTTPS
- Toggle HSTS + max-age configurable (borné 0 - 2 ans)

**Panneau Certificats stockés** :
- Ligne par cert avec badges statut (Actif, Auto-signé, Importé, Généré,
  jours restants, expiré, expire bientôt)
- Boutons Activer / Exporter / Supprimer
- Détails visibles : CN, SAN (tronqué avec tooltip), SHA-256 empreinte,
  Validité du … au …

**Panneau Générer auto-signé** (colonne gauche) :
- Nom convivial + CN + SAN (multi-ligne, wildcards + IPs)
- Organisation + Pays + Validité (jours) + Taille clé RSA (select)
- Toggle "Activer immédiatement"
- Warning explicite : LAN / intranet uniquement, warning navigateur

**Panneau Importer certificat existant** (colonne droite) :
- Nom + textareas cert.pem + key.pem + input file drag-and-drop
- Toggle "Activer immédiatement"

**Aide en bas de page** : 3 conseils actionnables selon le cas d'usage
(LAN, Prod Internet, HSTS).

**Accessibilité / tests** : **80 `data-testid`** exposés, dont 30+
préfixés `tls-`.

### Intégration Centre de sécurité

Nouvelle action rapide **HTTPS / TLS · Domaines & certificats** en tête
de la grille "Actions rapides" du Centre de sécurité (icône Lock bleue).

---

## 3. Tests

Nouveau `tests/test_v07f_tls_settings.py` — **8 tests verts** :

- `TestTlsRouterRegistered` (1) — les 8 routes TLS sont enregistrées
- `TestSelfSignedGeneration` (1) — cert X.509 valide, CN/SAN/dates cohérents
- `TestPrivateKeyEncryption` (2) — AES-GCM round-trip + garbage rejeté
- `TestDomainsValidation` (2) — RFC 1123 accepte/refuse correctement
- `TestDockerComposeProdYaml` (2) — YAML parse OK + guard anti-régression
  contre le pattern dangereux `${VAR:?message: hint}` non-quoté

**Suite totale v0.7 : 120/120 verts** (Wave A→G + régression).

### Live validation (Playwright)

- Login → `/security-center` : action rapide "HTTPS / TLS" visible et cliquable
- `/security-center/tls` : page rend complètement, 80 data-testids
- Cert auto-signé créé via API : CN=mgvms.local, SANs=[mgvms.local,
  *.mgvms.local, 192.168.1.10], days_left=364, self_signed=true, activé
- Domaines persistés : external=vms.example.com, force_https=true, HSTS=true

---

## 4. Fichiers

| Fichier | +/- | Nature |
|---------|:-:|--------|
| `deploy-app/docker-compose.prod.yml` | +5 / -3 | Quoting env vars |
| `backend/routes/tls.py` (nouveau) | +340 | Router complet |
| `backend/server.py` | +2 | Registration |
| `frontend/src/pages/TlsSettings.jsx` (nouveau) | +477 | Page complète |
| `frontend/src/pages/SecurityCenter.jsx` | +6 / -1 | Action rapide |
| `frontend/src/App.js` | +2 / 0 | Route |
| `backend/tests/test_v07f_tls_settings.py` (nouveau) | +150 | 8 tests |
| **TOTAL** | **~985 lignes** | |

---

## 5. API publique — zéro cassure

**Nouveaux endpoints uniquement** (préfixe `/api/security/tls/*`) — aucun
endpoint existant modifié. Aucun schéma Mongo altéré (nouvelle collection
`tls_certificates`, séparée).

**Contrat sécurité** : la clé privée n'est jamais renvoyée sauf
`GET /certificates/{cid}/pem?include_key=true` par un admin authentifié —
et cette action est **auditée** (`tls_private_key_exported`).

---

## 6. Prochaines pistes

- **Nginx auto-reload** : quand un cert est activé via UI, générer le
  contenu de `nginx.conf` + `certs/{cid}.crt` sur volume partagé et
  déclencher `nginx -s reload` via un side-car
- **Let's Encrypt intégré** : bouton "Obtenir un certificat Let's Encrypt"
  qui déclenche `certbot certonly --webroot` en background
- **CSR export** : pour les CA privées d'entreprise, permettre de générer
  un CSR signable en externe puis ré-uploader la chaîne
- **Notification pré-expiration** : alerte 30 j / 7 j avant expiration
