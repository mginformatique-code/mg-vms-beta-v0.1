# Chapitre 22 — Administration & RBAC

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `02-philosophie-principes` (R05, R09) · `05-contrats-interfaces` · `11-plateforme-plugins`

Ce chapitre définit l'administration du système : gestion des utilisateurs, rôles, permissions granulaires par site, authentification (JWT locale + plugins LDAP/OIDC), 2FA, audit, sauvegardes.

---

## 22.1 Principes

**Modèle RBAC hiérarchique** : Utilisateur → Rôle → Permissions → Ressources (sites, caméras, plugins). Un utilisateur n'a jamais accès à une ressource sans permission explicite.

**Deny by default** : toute action non explicitement autorisée est refusée.

**Audit intégral** : toute action admin (création user, modif config, resync, etc.) est enregistrée dans `db.audit_logs` (R09) avec rétention minimum 1 an.

**Auth pluggable** : la source d'authentification (JWT local, LDAP, OIDC) est un **plugin** (interface `AuthProvider`, chapitre 11 §11.3.7).

---

## 22.2 Modèle de données

### 22.2.1 Utilisateur

```json
{
  "id": "uuid",
  "email": "sophie.martin@example.com",
  "name": "Sophie Martin",
  "password_hash": "bcrypt$12$...",  // null si auth externe
  "auth_provider": "local|ldap|oidc-google|oidc-keycloak",
  "external_id": "...",              // si auth externe
  "roles": ["operator"],
  "sites_access": ["site_a_id", "site_b_id"],  // ou ["*"] pour tous
  "permissions_override": {},        // exceptions au rôle
  "2fa_enabled": true,
  "2fa_secret_encrypted": "...",
  "active": true,
  "created_at": "...",
  "created_by": "admin_user_id",
  "last_login": "...",
  "failed_login_attempts": 0,
  "locked_until": null
}
```

### 22.2.2 Rôle

```json
{
  "id": "role_operator",
  "name": "Opérateur",
  "description": "Consultation live + alertes + exports",
  "permissions": [
    "view_live",
    "view_recordings",
    "view_events",
    "view_alerts",
    "acknowledge_alerts",
    "export_recording"
  ],
  "built_in": true  // rôles système, non-modifiables
}
```

### 22.2.3 Permissions atomiques

Liste exhaustive des permissions du core v3.0 :

| Permission | Description |
|---|---|
| `view_live` | Voir les flux live |
| `view_recordings` | Voir les enregistrements |
| `view_events` | Voir les événements IA |
| `view_alerts` | Voir les alertes |
| `acknowledge_alerts` | Acquitter les alertes |
| `export_recording` | Télécharger un extrait vidéo |
| `read_plates` | Voir l'historique ANPR |
| `read_faces` | Voir la reconnaissance faciale |
| `manage_ptz` | Contrôler les caméras PTZ |
| `technician` | Diagnostics + config caméras (pas admin) |
| `manage_cameras` | CRUD caméras |
| `manage_ai_config` | Config IA / scénarios |
| `manage_storage` | Config pools de stockage |
| `manage_plugins` | Installer / désinstaller plugins |
| `manage_users` | CRUD users et rôles |
| `manage_sites` | CRUD sites |
| `read_audit` | Consulter le journal d'audit |
| `manage_settings` | Config globale |
| `admin` | Super-admin (implicite : toutes permissions) |

**Extensibilité plugin** : chaque plugin peut définir ses propres permissions dans son manifest (`spec.permissions_declared[]`). Elles apparaissent dans l'UI de rôles avec préfixe `plugin.{name}.{permission}`.

### 22.2.4 Rôles système bundle v3.0

| Rôle | Permissions clés |
|---|---|
| `viewer` | view_live, view_recordings, view_events |
| `operator` | viewer + view_alerts, acknowledge_alerts, export_recording, read_plates |
| `technician` | operator + technician, manage_cameras, manage_ai_config |
| `admin` | technician + manage_users, manage_plugins, manage_storage, manage_sites, read_audit, manage_settings |
| `super_admin` | admin implicite (utilisateur avec flag `super_admin: true`) |

L'admin peut créer des **rôles custom** en cochant des permissions (UI dédiée).

---

## 22.3 Authentification

### 22.3.1 Local (défaut)

- Mot de passe bcrypt (cost 12), stocké en `password_hash`.
- JWT access token 15 min + refresh token 7 j (single-use rotation).
- Rate limit login : 5 tentatives par IP en 60 s (chapitre 5 §5.1.5).
- Après 5 échecs consécutifs sur un même compte : lock 15 min, notif admin.

### 22.3.2 2FA (TOTP)

- Optionnel par utilisateur, forcé pour rôles `admin` (config globale par admin).
- Standard TOTP RFC 6238, compatible Google Authenticator, Authy, Aegis, 1Password.
- Backup codes générés à l'activation (10 codes single-use).
- Reset 2FA : par un autre admin uniquement (log audit).

### 22.3.3 LDAP / Active Directory (plugin `auth-ldap`)

Plugin optionnel. Config admin :
- URL serveur LDAP.
- Base DN, bind DN, bind password (chiffré Fernet).
- Filtre utilisateur (`(&(objectClass=user)(sAMAccountName={username}))`).
- Mapping groupes LDAP → rôles MG-VMS.

Flow : login → check DB local → si absent → check LDAP → si OK → création user local avec mapping rôle.

### 22.3.4 OIDC (plugin `auth-oidc-*`)

Plugins par provider : `auth-oidc-google`, `auth-oidc-microsoft`, `auth-oidc-keycloak`.

Config : issuer URL, client_id, client_secret, scopes, mapping claims → rôles.

Flow standard OIDC Authorization Code Flow avec PKCE.

Bouton « Se connecter avec Google » sur la page de login (si plugin activé).

### 22.3.5 Priorité des sources

Ordre de tentative : local → LDAP (si activé) → OIDC (si activé). L'utilisateur choisit via l'UI de login (radio buttons ou boutons providers).

Un même email peut exister via plusieurs sources, mais l'`auth_provider` du premier login gagne. Les logins ultérieurs doivent utiliser le même provider (message clair sinon).

---

## 22.4 Multi-site & isolation

### 22.4.1 Modèle site

```json
{
  "id": "uuid",
  "name": "Usine Bordeaux",
  "address": "...",
  "timezone": "Europe/Paris",
  "geo": {"lat": ..., "lng": ...},
  "logo_url": "...",
  "created_at": "..."
}
```

Chaque caméra, chaque événement, chaque alerte est rattaché à un site.

### 22.4.2 Accès par site

Un utilisateur a `sites_access: ["site_a", "site_b"]` ou `["*"]` (tous). Les listes filtrées par API l'excluent des autres sites automatiquement.

**Exemple** : `GET /api/v1/cameras` retourne uniquement les caméras des sites autorisés à l'utilisateur.

### 22.4.3 Fédération (v3.5+)

Une instance MG-VMS peut être un « master » qui pilote plusieurs instances secondaires (une par site géographique distant, chacune avec ses caméras locales). La fédération partage :
- Utilisateurs + rôles (source de vérité = master).
- Dashboards consolidés (vue cross-site).
- Alertes remontées vers le master.

Le trafic vidéo reste local (aucun flux caméra ne traverse WAN sauf explicite).

---

## 22.5 Interface administration

Page `/administration` avec 6 onglets :

### 22.5.1 Utilisateurs

Liste + CRUD. Colonnes : email, nom, rôles, sites, 2FA, dernière connexion, statut.

Actions rapides : désactiver, forcer reset password, forcer reset 2FA, voir audit user.

### 22.5.2 Rôles & permissions

Liste des rôles + éditeur de rôle custom (checkboxes de permissions).

Rôles système en lecture seule (`built_in: true`) avec bouton **[Dupliquer et modifier]**.

### 22.5.3 Sites

CRUD sites + gestion des accès utilisateurs par site.

### 22.5.4 Authentification

Config des providers auth :
- Local : toggle « activer », politique password (min length, force).
- LDAP : formulaire (visible si plugin `auth-ldap` installé).
- OIDC : liste des providers configurés.
- 2FA : politique (optionnel / forcé pour admin / forcé pour tous).

### 22.5.5 Journal d'audit

Table paginée + filtrable (`db.audit_logs`).

Colonnes : timestamp, user, action, cible, IP, résultat, détails.

Export CSV / PDF.

Rétention 12 mois par défaut (configurable, minimum 3 mois).

### 22.5.6 Sauvegardes

Config des backups auto :
- Fréquence (quotidien 03:00 par défaut).
- Destination (pool storage local ou plugin S3/SFTP).
- Rétention (30 jours).
- Chiffrement AES-256 avec passphrase.

Actions : [Sauvegarder maintenant] [Restaurer une sauvegarde] [Télécharger].

---

## 22.6 Audit log

### 22.6.1 Format standard

```json
{
  "id": "uuid",
  "timestamp": "...",
  "user_id": "uuid",
  "user_email": "admin@example.com",
  "action": "camera.create|user.delete|plugin.install|...",
  "target_type": "camera|user|plugin|...",
  "target_id": "uuid",
  "target_name": "Parking Nord",
  "ip_address": "192.168.1.100",
  "user_agent": "Mozilla/5.0...",
  "result": "success|failure",
  "details": {"before": {...}, "after": {...}, "error": "..."},
  "correlation_id": "..."
}
```

### 22.6.2 Actions systématiquement auditées

- Authentification : login (success/fail), logout, 2FA setup/reset.
- User management : create, update, delete, role change, permission override.
- Caméra : create, update, delete, PTZ command, snapshot download.
- Plugin : install, enable, disable, uninstall, config change.
- Config globale : any settings change.
- Recording : consultation, export, download.
- Alertes : acknowledge, purge.
- Diagnostics : streams-sync repair, plugin restart forcé.

### 22.6.3 Rétention & purge

- 12 mois par défaut, purge auto par job cron quotidien.
- Purge auditée elle-même (« audit purged 3452 entries older than 12 months »).
- Export périodique possible vers stockage externe (plugin `s3-storage`) pour conformité longue durée.

---

## 22.7 Sauvegardes & migration

### 22.7.1 Contenu d'une sauvegarde

- Dump MongoDB complet (`mongodump`) — état applicatif.
- Config des plugins (`/data/plugins/*/config/`).
- Secrets chiffrés (jamais les clés de chiffrement — l'admin doit les gérer séparément).
- Metadata (version MG-VMS, liste plugins, checksum).

**Non-inclus** :
- Segments vidéo enregistrés (volumes trop massifs, gestion séparée par Storage Manager).
- Logs applicatifs.
- Modèles IA (téléchargeables depuis Marketplace).

### 22.7.2 Restauration

Assistant restauration en 4 étapes :
1. Upload / sélection de la sauvegarde.
2. Vérification signature + compatibilité version (min v3.0 → v3.0, migration auto vers v3.x supérieur).
3. Confirmation impact (« vous allez remplacer 42 caméras existantes »).
4. Restauration + restart supervisé.

### 22.7.3 Migration d'instance

Cas : passer d'un serveur physique à un autre.

1. Sauvegarde depuis instance A.
2. Installation propre MG-VMS sur instance B (Docker Compose).
3. Import sauvegarde via UI ou CLI (`mgvms-cli backup restore <file>`).
4. Réinstallation auto des plugins listés dans la sauvegarde (depuis Marketplace).
5. Vérification streams-sync + tests bout en bout.

---

## 22.8 Sécurité renforcée

### 22.8.1 Chiffrement des secrets (R05)

Champs sensibles chiffrés Fernet avant persistence :
- `password_hash` (bcrypt intrinsèque, mais aussi chiffré au repos).
- `password_camera` (RTSP credentials).
- `2fa_secret`.
- Tokens externes (LDAP bind password, OIDC client secret, MQTT broker password, webhook secrets, refresh tokens…).

Clé Fernet en var d'env `MGVMS_ENCRYPTION_KEY`, rotable (procédure de re-key documentée).

### 22.8.2 Sessions

- Token access 15 min, refresh 7 j.
- Single-use refresh (rotation à chaque usage).
- Révocation possible côté admin (invalidation immédiate de tous les tokens d'un user).
- Limite : 5 sessions simultanées par user (au-delà : plus ancienne révoquée).

### 22.8.3 Politique de mot de passe

Configurable par admin :
- Longueur min : 12 caractères (défaut).
- Complexité : score `zxcvbn` ≥ 3.
- Historique : 5 derniers mots de passe interdits.
- Expiration : optionnelle (30/60/90/365 jours ou jamais).

### 22.8.4 Anti-brute-force

- 5 échecs consécutifs sur un user → lock 15 min.
- 20 échecs consécutifs sur une IP → block IP 60 min + notif admin.
- Captcha (v3.1+) après 3 échecs.

### 22.8.5 Notification actions critiques

L'utilisateur reçoit un email de notif à :
- Chaque login depuis une nouvelle IP.
- Chaque modif de mot de passe.
- Chaque activation/désactivation 2FA.
- Chaque tentative de reset password.

---

## 22.9 Tests d'acceptation

### TA-22.1 — Deny by default

**Given** un user `viewer` sans permission `manage_cameras`.
**When** il tente `POST /cameras`.
**Then** HTTP 403 `permission_denied`. Audit log entry créé.

### TA-22.2 — Isolation par site

**Given** un user avec `sites_access: ["site_a"]`.
**When** il liste les caméras.
**Then** seules les caméras du site A sont retournées. Aucune caméra du site B n'apparaît.

### TA-22.3 — Rotation refresh token

**Given** un refresh token valide.
**When** je l'échange contre un nouveau access + refresh.
**Then** le token original est invalidé. Un usage ultérieur retourne HTTP 401 `token_invalid`.

### TA-22.4 — Audit systématique

**Given** un admin crée une caméra.
**When** l'action est réussie.
**Then** `db.audit_logs` contient une entrée `camera.create` avec `before: null, after: {camera details}`, user, IP.

### TA-22.5 — 2FA obligatoire admin

**Given** politique 2FA « forcé pour admin ».
**When** un admin sans 2FA tente de se connecter.
**Then** login réussit mais force le setup 2FA avant tout autre appel API.

### TA-22.6 — Restauration sauvegarde

**Given** une sauvegarde v3.0.2 d'une instance avec 20 caméras.
**When** je restaure sur une instance vide v3.0.5.
**Then** migration auto + 20 caméras présentes + streams-sync repair automatique.

---

## 22.10 ADR

### ADR-22 — Auth pluggable (AuthProvider)

**Contexte** : v2.22.0 auth local hard-codé.
**Décision** : plugins `AuthProvider` (chapitre 11 §11.3.7). Local reste dans le core. LDAP/OIDC via plugins.
**Conséquences** : ajout d'auth = plugin, pas de touche core.

### ADR-23 — Session token single-use rotation

**Contexte** : sécurité des refresh tokens.
**Décision** : chaque refresh → nouveau access + nouveau refresh, ancien invalidé.
**Conséquences** : détection facile de vol de token (double usage), UX inchangée si client suit le contrat.

---

## Annexes

### A. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : RBAC hiérarchique · 5 rôles bundle · auth pluggable LDAP/OIDC · 2FA · audit · sauvegardes · sécurité renforcée · 2 ADR |
